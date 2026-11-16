"""Execute production history reprojection and rejection with CPU scene stubs."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.falcor import pdf_pt_shader as shader
from tests.fixtures.cpp import compile_cpp, shader_function


ROOT = Path(__file__).resolve().parents[2]


class PdfHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Only the hardware unroll attribute and Slang inout spelling change.
        # Both function bodies come from the production shader composition.
        upstream = ROOT / 'renderers/falcor/upstream/Source'
        sources = {}
        for name in shader.FILES:
            relative = name.removeprefix('shaders/')
            if relative.startswith('ReSTIRPathTracing/'):
                relative = 'Modules/' + relative
            sources[name] = (upstream / relative).read_text(encoding='utf8')
        changed = shader.build_overlay(sources, {'history_limit': 20, 'history_decay': .95})
        restir = changed[shader.MODULE + 'ReSTIRPT.slang']
        temporal = changed[shader.MODULE + 'TemporalResampling.cs.slang']
        functions = (shader_function(restir, 'labCameraStamp', 'uint').replace('[unroll]', ''),
                     shader_function(temporal, 'labCombineHistory', 'void'))
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        (folder / 'pdf_pt_history_under_test.inl').write_text('\n'.join(functions), encoding='utf8')
        cls.executable = compile_cpp(ROOT / 'tests/pdf_pt_history.cpp', folder, includes=(folder,))

    def execute(self, scenario):
        result = subprocess.run([str(self.executable), scenario], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_exact_decay_empty_current_history_cap_and_nearest_reprojection(self):
        output = self.execute('updates')
        self.assertIn('updates=5', output)
        self.assertIn('half: A=(2,2,2), B=8, count=4, A/B=(0.25,0.25,0.25)', output)
        self.assertIn('default: A=(2.9,2,3.8), B=11.6, count=6.7', output)
        self.assertIn('empty: A=(1,0,2), B=4, count=3, A/B=(0.25,0,0.5)', output)

    def test_initialization_disocclusion_stamps_invalid_reprojection_and_nonfinite_history(self):
        output = self.execute('rejections')
        self.assertIn('rejections=27', output)
        self.assertIn('camera_stamp_changed', output)
        self.assertIn('resolution_stamp_changed', output)
        self.assertIn('nonfinite_total', output)


if __name__ == '__main__':
    unittest.main()
