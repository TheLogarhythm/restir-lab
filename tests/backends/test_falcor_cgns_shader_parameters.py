import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.falcor import cgns_single_overlay as overlay
from scripts.falcor import cgns_single_runtime as runtime


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / 'renderers/falcor/upstream/Source/Modules/ReSTIRPathTracing'


class CgnsShaderParameterTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        sources = {}
        for kind in ('reference', 'gltf-v3'):
            destination = root / kind
            destination.mkdir()
            (destination / 'receipt.json').write_text('{"fixture": "' + kind + '"}', encoding='utf8')
            sources[kind] = SimpleNamespace(DEST=destination)
        self.enterContext(patch.dict(runtime.SOURCES, sources))

    def test_parameter_values_change_generated_shader_without_changing_source(self):
        original = overlay.SELECTOR.read_bytes()
        params = {'candidate_count': 7, 'position_scale': 0.1, 'normal_exponent': 4.0,
                  'early_stop_score': 0.75, 'early_stop_count': 2}
        generated = overlay.parameterize_selector(params)
        self.assertIn('#define LAB_CGNS_CANDIDATE_COUNT 7', generated)
        self.assertIn('#define LAB_CGNS_POSITION_SCALE 0.1', generated)
        self.assertIn('#define LAB_CGNS_NORMAL_EXPONENT 4', generated)
        self.assertIn('#define LAB_CGNS_EARLY_STOP_SCORE 0.75', generated)
        self.assertIn('#define LAB_CGNS_EARLY_STOP_COUNT 2', generated)
        self.assertEqual(original, overlay.SELECTOR.read_bytes())

    def test_bad_parameters_are_rejected_before_shader_generation(self):
        params = {'candidate_count': 32, 'position_scale': 0.05, 'normal_exponent': 8.0,
                  'early_stop_score': 0.5, 'early_stop_count': 1}
        for key, value in [('candidate_count', 33), ('position_scale', float('nan')),
                           ('normal_exponent', -1), ('early_stop_score', 1.1),
                           ('early_stop_count', 33)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                overlay.parameterize_selector({**params, key: value})

    def test_different_parameters_produce_different_integrated_shader(self):
        sources = {name: (UPSTREAM / name).read_bytes().decode('utf8') for name in overlay.FILES}
        common = {'position_scale': 0.05, 'normal_exponent': 8.0,
                  'early_stop_score': 0.5, 'early_stop_count': 1}
        a = overlay.build_overlay(sources, parameters={**common, 'candidate_count': 32})
        b = overlay.build_overlay(sources, parameters={**common, 'candidate_count': 4})
        self.assertNotEqual(a['ResamplingCommon.slang'], b['ResamplingCommon.slang'])
        self.assertEqual({n for n in a if a[n] != b[n]}, {'ResamplingCommon.slang'})

    def test_variant_identity_tracks_parameters_and_source(self):
        params = {'candidate_count': 32, 'position_scale': 0.05, 'normal_exponent': 8,
                  'early_stop_score': 0.5, 'early_stop_count': 1}
        a = runtime.variant_destination('reference', params)
        self.assertEqual(a, runtime.variant_destination('reference', dict(reversed(list(params.items())))))
        self.assertNotEqual(a, runtime.variant_destination('gltf-v3', params))
        self.assertNotEqual(a, runtime.variant_destination('reference', {**params, 'candidate_count': 4}))

    def test_variant_identity_changes_for_shader_implementation_and_source_receipt(self):
        params = {'candidate_count': 32, 'position_scale': 0.05, 'normal_exponent': 8,
                  'early_stop_score': 0.5, 'early_stop_count': 1}
        baseline = runtime.variant_destination('reference', params)
        original_sha = runtime.sha
        tracked = (overlay.SELECTOR, overlay.CORE, Path(overlay.__file__), Path(overlay.legacy.__file__),
                   runtime.SOURCES['reference'].DEST / 'receipt.json')
        for target in tracked:
            def altered(path, target=target):
                return '0' * 64 if Path(path) == target else original_sha(path)
            with self.subTest(path=target), patch.object(runtime, 'sha', side_effect=altered):
                self.assertNotEqual(baseline, runtime.variant_destination('reference', params))

    def test_ensure_uses_operation_lock_and_verifies_requested_parameters(self):
        params = {'candidate_count': 32, 'position_scale': 0.05, 'normal_exponent': 8,
                  'early_stop_score': 0.5, 'early_stop_count': 1}
        expected = ROOT / 'build' / 'mock-variant'
        calls = []
        class FakePath:
            def is_symlink(self): return False
            def exists(self): return True
            def __truediv__(self, name): return expected / name
        with patch.object(runtime, 'variant_destination', return_value=FakePath()), \
             patch.object(runtime, 'exclusive_operation', side_effect=lambda _: nullcontext()), \
             patch.object(runtime, 'check_renderer_idle', side_effect=lambda: calls.append('idle')), \
             patch.object(runtime, '_prepare_locked', side_effect=AssertionError('must not overwrite')), \
             patch.object(runtime, 'verify_prepared', side_effect=lambda p, **kw: calls.append((p, kw))):
            self.assertEqual(runtime.ensure_variant('reference', params), expected / 'runtime')
        self.assertEqual(calls, ['idle', (expected / 'runtime', {'expected_parameters': params})])


if __name__ == '__main__':
    unittest.main()
