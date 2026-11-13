"""Contract tests for the isolated Falcor point-CGNS shader overlay."""
import unittest
from pathlib import Path
from scripts.falcor import cgns_shader_overlay as overlay
from scripts.falcor import cgns_stage_diagnostic as diag

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / 'renderers/falcor/upstream/Source/Modules/ReSTIRPathTracing'

class CgnsOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = {name: (UPSTREAM / name).read_bytes().decode('utf8') for name in overlay.FILES}
        cls.selector = overlay.SELECTOR.read_text(encoding='utf8')

    def test_every_point_neighbor_consumer_reads_selection(self):
        result = overlay.build_overlay(self.sources, self.selector)
        self.assertIn(self.selector, result['ResamplingCommon.slang'])
        for name, count in overlay.FILES.items():
            if not count:
                continue
            self.assertEqual(result[name].count('LabCgnsPointSelection labCgnsSelected'), count)
            self.assertEqual(result[name].count('labCgnsSelected.pixels['), count)
            self.assertNotIn('getNextNeighborPixel(', result[name])
            self.assertEqual(self.sources[name].count('getNextNeighborPixel('), count)
        self.assertIn('labCgnsSelected.pixels[retraceIndex / 2]', result['SpatialPathRetrace.cs.slang'])

    def test_input_is_immutable_and_baseline_is_untouched(self):
        before = dict(self.sources)
        self.assertNotIn(overlay.MARKER, ''.join(before.values()))
        overlay.build_overlay(self.sources, self.selector)
        self.assertEqual(self.sources, before)
        self.assertEqual((UPSTREAM / 'ResamplingCommon.slang').read_bytes().decode('utf8'), before['ResamplingCommon.slang'])

    def test_rejects_missing_source_and_marker(self):
        missing = dict(self.sources)
        del missing['SpatialPathRetrace.cs.slang']
        with self.assertRaises(ValueError): overlay.build_overlay(missing, self.selector)
        with self.assertRaises(ValueError): overlay.build_overlay(self.sources, 'empty')

    def test_rejects_already_patched_and_source_drift(self):
        result = overlay.build_overlay(self.sources, self.selector)
        with self.assertRaises(ValueError): overlay.build_overlay(result, self.selector)
        changed = dict(self.sources)
        changed['SpatialResampling.cs.slang'] += '\ngetNextNeighborPixel(extra)\n'
        with self.assertRaises(ValueError): overlay.build_overlay(changed, self.selector)

    def test_diagnostic_instruments_all_stages_and_rejects_reentry(self):
        patched = overlay.build_overlay(self.sources, self.selector)
        for slot in range(4):
            diagnostic = diag.build_diagnostic(patched, slot)
            self.assertIn('labCgnsSelected.pixels[' + str(slot) + ']', diagnostic['GenerateRetraceWorkload.cs.slang'])
            self.assertIn('int(retraceIndex / 2) == ' + str(slot), diagnostic['SpatialPathRetrace.cs.slang'])
            self.assertIn('labMismatch', diagnostic['SpatialResampling.cs.slang'])
            with self.assertRaises(ValueError): diag.build_diagnostic(diagnostic, slot)
        with self.assertRaises(ValueError): diag.build_diagnostic(patched, 4)
        with self.assertRaises(ValueError): diag.build_diagnostic(self.sources, 0)

    def test_diagnostic_fault_injection_is_confined_to_retrace(self):
        patched = overlay.build_overlay(self.sources, self.selector)
        good = diag.build_diagnostic(patched, 2)
        bad = diag.build_diagnostic(patched, 2, inject_fault=True)
        differences = [name for name in diag.FILES if good[name] != bad[name]]
        self.assertEqual(differences, ['SpatialPathRetrace.cs.slang'])
        self.assertIn('(labCgnsSelected.pixels[2] + int2(1, 0))', bad[differences[0]])

    def test_private_runtime_required_and_base_runtime_protected(self):
        with self.assertRaises(ValueError): overlay.apply_overlay(ROOT)
        base = ROOT / 'build/falcor-reference-runtime/runtime'
        if base.is_dir():
            with self.assertRaisesRegex(ValueError, 'frozen runtime'): overlay.apply_overlay(base)

if __name__ == '__main__': unittest.main()
