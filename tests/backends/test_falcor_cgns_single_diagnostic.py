import importlib.util
from pathlib import Path
import unittest
from scripts.falcor import cgns_single_overlay as overlay
ROOT=Path(__file__).resolve().parents[2]
UPSTREAM=ROOT/'renderers/falcor/upstream/Source/Modules/ReSTIRPathTracing'
class SingleDiagnosticTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.falcor.cgns_single_diagnostic'))
        from scripts.falcor import cgns_single_diagnostic
        return cgns_single_diagnostic
    def test_stage_capture_fault_and_production_isolation(self):
        mod=self.module();base={n:(UPSTREAM/n).read_bytes().decode('utf8') for n in overlay.FILES};patched=overlay.build_overlay(base)
        good=mod.build_diagnostic(patched);bad=mod.build_diagnostic(patched,inject_fault=True)
        self.assertIn('labCgnsSelected.pixels[0]',good['GenerateRetraceWorkload.cs.slang'])
        self.assertIn('int(retraceIndex / 2) == 0',good['SpatialPathRetrace.cs.slang'])
        self.assertIn('labMismatch',good['SpatialResampling.cs.slang'])
        self.assertEqual([n for n in good if good[n]!=bad[n]],['SpatialPathRetrace.cs.slang'])
        self.assertIn('labCgnsSelected.pixels[0] + int2(1, 0)',bad['SpatialPathRetrace.cs.slang'])
        with self.assertRaises(ValueError):mod.build_diagnostic(good)
        with self.assertRaises(ValueError):mod.build_diagnostic(base)
    def test_production_runtime_is_rejected(self):
        mod=self.module()
        for name in ('build/falcor-cgns-single-reference/runtime','build/falcor-cgns-single-gltf-v3/runtime'):
            p=ROOT/name
            if p.is_dir() and (p.parent/'receipt.json').exists():
                with self.assertRaises(ValueError):mod.apply_diagnostic(p)
if __name__=='__main__':unittest.main()
