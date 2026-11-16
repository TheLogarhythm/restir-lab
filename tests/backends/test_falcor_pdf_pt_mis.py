"""Execute the patched Falcor confidence/MIS path on CPU with fixed shift results.

The production DoPass, spatial shift/merge, reservoir merge and finalization are
compiled intact. Scene, replay and GPU resources are deterministic CPU fixtures.
The literal fixtures detect stale cSum, missing reverse or forward confidence,
extra division by M, lost failed-shift confidence, and accidental h-squared.
"""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests.fixtures.cpp import compile_cpp, shader_function

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / "renderers/falcor/upstream/Source/Modules/ReSTIRPathTracing"
NAMES = ("PathReservoir.slang", "GenerateRetraceWorkload.cs.slang",
         "SpatialResampling.cs.slang", "Shift.slang")


def sources():
    return {name: (UPSTREAM / name).read_text(encoding="utf8") for name in NAMES}


def load_patch(test):
    path = ROOT / "scripts/falcor/pdf_pt_mis.py"
    test.assertTrue(path.is_file(), "PDF PT effective-confidence overlay is missing")
    spec = importlib.util.spec_from_file_location("pdf_pt_mis_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cpp_method(text, name, return_type):
    return shader_function(text, name, return_type).replace("this.", "this->")


def generated_header(patched, original):
    path = patched["PathReservoir.slang"]
    mask = path[path.index("struct NeighborValidMask"):path.index("struct PrecomputedShiftData")]
    mask = mask.replace("[mutating]", "").strip() + ";\n"
    helper = shader_function(path, "labPdfEffectiveNeighborM", "float")
    # Execute the workload's actual assignment/acceptance block, not a duplicate
    # implementation of the effective-M formula from the CPU fixture.
    work = patched["GenerateRetraceWorkload.cs.slang"]
    init_begin = work.index("float cSum = centralReservoir.M;")
    init_end = work.index("float doFReconnectionShiftProbability", init_begin)
    initialize = work[init_begin:init_end]
    begin = work.index("// LAB_PDF_PT_EFFECTIVE_M_ACCEPT")
    end = work.index("if (ReSTIRPT::ShiftMapping", begin)
    accept = work[begin:end].replace("continue;", "return;")
    work_function = """
void workload(NeighborValidMask& mask, PathReservoir center, PathReservoir neighbor) {
    const int centralOffset=0, i=0;
    auto& neighborValidMask=gMasks;
    PathReservoir centralReservoir=center, neighborReservoir=neighbor;
    neighborValidMask[0]=mask;
    WORK_INITIALIZE
    WORK_ACCEPT
    neighborValidMask[0].setCSum(cSum);
    mask=neighborValidMask[0];
}
""".replace("WORK_INITIALIZE", initialize).replace("WORK_ACCEPT", accept)
    # The early return above must publish the mask as the GPU storage does.
    work_function = work_function.replace("return;", "mask=neighborValidMask[0]; mask.setCSum(cSum); return;")
    merge = cpp_method(path, "merge", "bool")
    entry = merge.index("{") + 1
    probe = "\n    if (inReservoir.initRandomSeed == 11) seenCenter = misWeight; else seenNeighbor = misWeight;\n"
    members = merge[:entry] + probe + merge[entry:] + "\n" + cpp_method(path, "finalizeReservoirWeight", "void")
    shift = cpp_method(patched["Shift.slang"], "shiftAndMergeReservoirSpatial", "bool")
    shift_precomputed = cpp_method(patched["Shift.slang"], "shiftAndMergeReservoirSpatialWithPrecomputedInfo", "bool")
    spatial = cpp_method(patched["SpatialResampling.cs.slang"], "DoPass", "void").replace(", EXTRA_SHIFT_ARGS", "")
    baseline = cpp_method(original["SpatialResampling.cs.slang"], "DoPass", "void").replace("void DoPass(", "void BaselinePass(").replace(", EXTRA_SHIFT_ARGS", "")
    return {"pdf_pt_mis_under_test.h": "#pragma once\n" + mask + helper,
            "pdf_pt_reservoir_methods.h": members,
            "pdf_pt_workload.h": work_function,
            "pdf_pt_shift.h": shift + "\n" + shift_precomputed,
            "pdf_pt_spatial.h": spatial + "\n" + baseline}


class FalcorPdfPtMisTests(unittest.TestCase):
    def compile_and_run(self, changed, original, folder):
        for name, text in generated_header(changed, original).items():
            (folder / name).write_text(text, encoding="utf8")
        executable = compile_cpp(ROOT / "tests/falcor_pdf_pt_mis.cpp", folder, includes=(folder,))
        return subprocess.run([str(executable)], capture_output=True, text=True)

    def test_production_shader_normalization_and_fractional_confidence(self):
        patch = load_patch(self)
        original = sources()
        before = dict(original)
        changed = patch.apply(original)
        self.assertEqual(original, before, "Overlay must leave caller input unchanged")
        self.assertEqual(set(changed), set(original))
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            run = self.compile_and_run(changed, original, folder)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_numeric_oracle_rejects_normalization_mutants(self):
        patch = load_patch(self)
        original = sources()
        changed = patch.apply(original)
        mutations = (
            ("stale_cSum", "GenerateRetraceWorkload.cs.slang", "cSum += labPdfMi;", "cSum += neighborReservoir.M;"),
            ("raw_M_in_merge", "SpatialResampling.cs.slang", "neighborReservoir.M = neighborValidMask[centralOffset].labPdfNeighborM;", "neighborReservoir.M = prevReservoirs[neighborOffset].M;"),
            ("missing_reverse_M", "SpatialResampling.cs.slang", "canonicalWeight += neighborReservoir.M / C.c_sum * currentWeightTerm;", "canonicalWeight += 1.f / C.c_sum * currentWeightTerm;"),
            ("missing_forward_M", "Shift.slang", "? srcReservoir.M / C.c_sum * srcTerm", "? 1.f / C.c_sum * srcTerm"),
            ("h_squared", "SpatialResampling.cs.slang", "neighborReservoir.M = neighborValidMask[centralOffset].labPdfNeighborM;", "neighborReservoir.M = neighborValidMask[centralOffset].labPdfNeighborM * neighborValidMask[centralOffset].labPdfH;"),
            ("extra_M_division", "PathReservoir.slang", "this.weight / p_hat", "this.weight / (p_hat * this.M)"),
            ("failed_shift_loses_M", "Shift.slang", "bool selected = dstReservoir.merge(dstIntegrand, Jacobian, srcReservoir, sg, misWeight);", "bool selected = dstReservoir.merge(dstIntegrand, Jacobian, srcReservoir, sg, misWeight); if (PathRISState::toScalar(dstIntegrand) == 0.f) dstReservoir.M -= srcReservoir.M;"),
        )
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for label, name, before, after in mutations:
                with self.subTest(mutation=label):
                    self.assertIn(before, changed[name])
                    broken = dict(changed)
                    broken[name] = broken[name].replace(before, after)
                    run = self.compile_and_run(broken, original, folder)
                    self.assertNotEqual(run.returncode, 0, "Numeric oracle accepted " + label)

    def test_rejects_missing_or_already_patched_sources(self):
        patch = load_patch(self)
        original = sources()
        with self.assertRaises(ValueError):
            patch.apply({name: text for name, text in original.items() if name != "PathReservoir.slang"})
        with self.assertRaises(ValueError):
            patch.apply(patch.apply(original))


if __name__ == "__main__":
    unittest.main()
