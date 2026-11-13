import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from tests.fixtures.cpp import compile_cpp

ROOT=Path(__file__).resolve().parents[2]
UPSTREAM=ROOT/'renderers/falcor/upstream/Source/Modules/ReSTIRPathTracing'

class SingleNeighborTests(unittest.TestCase):
    def module(self):
        spec=importlib.util.find_spec('scripts.falcor.cgns_single_overlay')
        self.assertIsNotNone(spec,'single-neighbor CGNS overlay must exist')
        from scripts.falcor import cgns_single_overlay
        return cgns_single_overlay

    def test_a_chao_shared_math_and_probability(self):
        mod=self.module()
        with tempfile.TemporaryDirectory(prefix='cgns-single-',dir=ROOT/'tmp') as d:
            exe=compile_cpp(ROOT/'tests/cgns_single_wrs.cpp',d,includes=(mod.CORE.parent,))
            result=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_selector_wired_to_all_consumers_and_distinct_marker(self):
        mod=self.module()
        before={n:(UPSTREAM/n).read_bytes().decode('utf8') for n in mod.FILES}
        after=mod.build_overlay(before)
        self.assertEqual(set(after),set(before))
        self.assertIn(mod.MARKER,after['ResamplingCommon.slang'])
        self.assertIn('LabCgnsSingleInsert',after['ResamplingCommon.slang'])
        self.assertNotIn(mod.LEGACY_MARKER,''.join(after.values()))
        for name,count in mod.FILES.items():
            if count:
                self.assertEqual(after[name].count('labCgnsSelected.pixels['),count)
                self.assertNotIn('getNextNeighborPixel(',after[name])
        self.assertNotEqual(before['ResamplingCommon.slang'],after['ResamplingCommon.slang'])
        with self.assertRaises(ValueError):mod.build_overlay(after)

    def test_protect_old_reference_and_m4_runtimes(self):
        mod=self.module()
        for d in ('build/falcor-reference-runtime/runtime','build/falcor-gltf-composite-runtime-v3/runtime','build/falcor-cgns-pt-reference/runtime','build/falcor-cgns-pt-gltf-v3/runtime'):
            p=ROOT/d
            if p.is_dir():
                with self.assertRaises(ValueError):mod.apply_overlay(p)

    def test_selector_explicitly_requires_single_neighbor(self):
        mod=self.module()
        text=mod.SELECTOR.read_text(encoding='utf8')
        self.assertIn('capacity != 1',text)
        self.assertIn('LabCgnsSingleInsert',text)
        self.assertIn('LAB_CGNS_EARLY_STOP_COUNT',text)
        self.assertIn('int2(-1, -1)',text)

if __name__=='__main__':unittest.main()
