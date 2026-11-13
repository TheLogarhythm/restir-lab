import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.falcor import spatial_experiment_config as config


class ExperimentConfigTests(unittest.TestCase):
    def setUp(self):
        self.value = config.load_config()

    def test_current_experiment_settings_are_loaded_and_modes_are_distinct(self):
        self.assertEqual(self.value['render'], {'width': 1920, 'height': 1080,
                         'warmup_frames': 40, 'capture_count': 8, 'image_accumulation': False})
        enabled = config.graph_options(self.value, 'temporal-on', 'baseline')
        disabled = config.graph_options(self.value, 'temporal-off', 'cgns')
        self.assertEqual(enabled['samplesPerPixel'], 1)
        self.assertTrue(enabled['reSTIRPathTracingOptions']['useTemporalResampling'])
        self.assertFalse(disabled['reSTIRPathTracingOptions']['useTemporalResampling'])
        self.assertEqual(enabled['reSTIRPathTracingOptions']['spatialNeighborCount'], 1)
        self.assertEqual(enabled['reSTIRPathTracingOptions']['spatialGatherRadius'], 30)
        self.assertEqual(self.value['methods']['cgns']['shader'], {
            'candidate_count': 32, 'position_scale': 0.05, 'normal_exponent': 8.0,
            'early_stop_score': 0.5, 'early_stop_count': 1})

    def test_graph_options_are_fresh_deep_copies_and_respect_settings(self):
        value = copy.deepcopy(self.value)
        value['graph']['reSTIRPathTracingOptions']['spatialGatherRadius'] = 17
        options = config.graph_options(value, 'temporal-on', 'cgns')
        self.assertEqual(options['reSTIRPathTracingOptions']['spatialGatherRadius'], 17)
        options['reSTIRPathTracingOptions']['spatialGatherRadius'] = 11
        self.assertEqual(value['graph']['reSTIRPathTracingOptions']['spatialGatherRadius'], 17)
        with self.assertRaises(ValueError): config.graph_options(value, 'temporal-on', 'unknown')
        with self.assertRaises(ValueError): config.graph_options(value, 'unknown', 'cgns')

    def test_unsupported_graph_and_budget_are_rejected(self):
        for path, item in [
            (('graph', 'samplesPerPixel'), 2),
            (('graph', 'sampleGenerator'), 1),
            (('graph', 'reSTIRPathTracingOptions', 'useAreaReservoirs'), True),
            (('graph', 'reSTIRPathTracingOptions', 'spatialNeighborCount'), 2),
            (('graph', 'reSTIRPathTracingOptions', 'spatialGatherRadius'), 2.5),
            (('graph', 'reSTIRPathTracingOptions', 'maxHistoryLength'), 101),
            (('graph', 'reSTIRPathTracingOptions', 'usePairedNeighbors'), True),
            (('graph', 'maxSurfaceBounces'), 2),
            (('graph', 'maxDiffuseBounces'), 9),
            (('graph', 'useRussianRoulette'), False),
            (('render', 'image_accumulation'), True),
            (('render', 'capture_count'), 0),
            (('render', 'width'), True),
            (('render', 'width'), 640),
            (('render', 'height'), 360),
            (('reference_catalog',), 'runs/different/manifest.json'),
        ]:
            with self.subTest(path=path):
                value = copy.deepcopy(self.value)
                current = value
                for key in path[:-1]: current = current[key]
                current[path[-1]] = item
                with self.assertRaises(ValueError): config.validate_config(value)

    def test_shader_limits_and_nonfinite_numbers(self):
        shader = self.value['methods']['cgns']['shader']
        for key, item in [('candidate_count', 33), ('candidate_count', True),
                          ('position_scale', 0), ('normal_exponent', float('nan')),
                          ('position_scale', 1e-300), ('normal_exponent', 1e-300),
                          ('early_stop_score', 1e-300),
                          ('early_stop_score', 1.1), ('early_stop_count', 33)]:
            with self.subTest(key=key):
                value = dict(shader, **{key: item})
                with self.assertRaises(ValueError): config.validate_cgns_shader(value)
        altered = dict(shader, candidate_count=4, early_stop_count=2, position_scale=0.1)
        self.assertEqual(config.validate_cgns_shader(altered), altered)

    def test_strict_keys_duplicate_json_and_snapshot_digest(self):
        value = copy.deepcopy(self.value)
        value['graph']['reSTIRPathTracingOptions']['misspelledSetting'] = 1
        with self.assertRaises(ValueError): config.validate_config(value)
        parsed, digest = config.load_config_snapshot()
        self.assertEqual(parsed, self.value)
        self.assertEqual(digest, hashlib.sha256(config.DEFAULT_CONFIG.read_bytes()).hexdigest())
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'invalid.json'
            p.write_text('{"schema_version":1,"schema_version":1}', encoding='utf-8')
            with self.assertRaises(ValueError): config.load_config(p)


if __name__ == '__main__':
    unittest.main()
