"""The temporal-on render must actually consume its selected experiment."""
import ast
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.falcor import cgns_temporal_capture as capture
from scripts.falcor import spatial_experiment_config as settings


class TemporalConfigIntegrationTests(unittest.TestCase):
    def test_custom_graph_reaches_falcor_render_script(self):
        experiment = copy.deepcopy(settings.load_config())
        experiment['graph']['reSTIRPathTracingOptions']['spatialGatherRadius'] = 13
        graph = capture.graph_options('baseline', experiment=experiment)
        self.assertEqual(graph['reSTIRPathTracingOptions']['spatialGatherRadius'], 13)
        self.assertTrue(graph['reSTIRPathTracingOptions']['useTemporalResampling'])
        camera = {'position': [1, 2, 3], 'direction': [0, 0, -1], 'up': [0, 1, 0], 'vertical_fov': 60}
        source = capture.render_script(Path('scene.pyscene'), camera, Path('out'), 2, 2,
                                       'baseline', adapted=False, experiment=experiment)
        ast.parse(source)
        self.assertIn("'spatialGatherRadius': 13", source)
        self.assertIn("'useTemporalResampling': True", source)
        self.assertIn('if frame in [3, 4]', source)

    def test_cgns_runtime_checked_against_shader_parameters(self):
        parameters = {'candidate_count': 7, 'position_scale': 0.03,
                      'normal_exponent': 4.0, 'early_stop_score': 0.7,
                      'early_stop_count': 1}
        with patch('scripts.falcor.cgns_single_runtime.verify_prepared',
                   return_value={'source_kind': 'reference'}) as verify:
            capture.validate_runtime(Path('rt'), 'cgns', False, shader_parameters=parameters)
        verify.assert_called_once_with(Path('rt'), expected_parameters=parameters)

    def test_baseline_and_cgns_graph_use_same_configuration(self):
        experiment = copy.deepcopy(settings.load_config())
        experiment['graph']['reSTIRPathTracingOptions']['spatialGatherRadius'] = 17
        self.assertEqual(capture.graph_options('baseline', experiment=experiment),
                         capture.graph_options('cgns', experiment=experiment))


if __name__ == '__main__':
    unittest.main()
