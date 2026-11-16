"""CPU contracts for the separate, bounded reset/fresh GPU diagnostic."""

import ast
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np


class PdfResetCheckTests(unittest.TestCase):
    def module(self):
        from scripts.falcor import pdf_pt_reset_check
        return pdf_pt_reset_check

    def test_plan_uses_six_warm_frames_then_reset_and_a_fresh_graph_with_the_same_seed(self):
        check = self.module()
        plan = check.frame_plan(100)
        self.assertEqual(len(plan), 11)
        self.assertEqual([row['path_seed'] for row in plan[:6]], list(range(100, 106)))
        self.assertTrue(plan[6]['reset'])
        self.assertEqual(plan[6]['path_seed'], plan[7]['path_seed'])
        self.assertNotEqual(plan[6]['graph'], plan[7]['graph'])
        self.assertEqual([row['clock_frame'] for row in plan], list(range(1, 12)))
        self.assertEqual(plan[8]['capture'], 'before-replacement')
        self.assertTrue(plan[9]['replace'])
        self.assertEqual(plan[9]['path_seed'], plan[10]['path_seed'])
        self.assertNotEqual(plan[9]['graph'], plan[10]['graph'])
        self.assertNotIn('reuse_seed', plan[6])
        extended = check.frame_plan(100, camera_cut=True)
        self.assertEqual(len(extended), 19)
        self.assertEqual(extended[-2]['pose'], 'cut')
        self.assertEqual(extended[-1]['pose'], 'cut')
        self.assertEqual(extended[-2]['path_seed'], extended[-1]['path_seed'])
        self.assertNotEqual(extended[-2]['graph'], extended[-1]['graph'])

    def test_script_reads_actual_seed_and_switches_graph_without_touching_production_capture(self):
        check = self.module()
        camera = dict(position=[0, 0, 0], direction=[0, 0, 1], up=[0, 1, 0], vertical_fov=45)
        source = check.render_script(Path('scene'), camera, check.frame_plan(100, camera_cut=True))
        ast.parse(source)
        self.assertIn('tracer.reset()', source)
        self.assertIn('m.setActiveGraph(graph)', source)
        self.assertIn('m.removeGraph(graphs.pop(event[\'graph\']))', source)
        self.assertIn("'fixed_seed_before_assignment': previous_fixed_seed", source)
        self.assertIn('graph.markOutput(output, TextureChannelFlags.RGBA)', source)
        self.assertIn("'actual_fixed_seed': int(tracer.fixedSeed)", source)
        self.assertIn("m.frameCapture.baseFilename = event['capture']", source)
        self.assertNotIn('reuse_seed', source)
        self.assertEqual(camera['position'], [0, 0, 0])

    def test_raw_moment_and_count_equality_detects_stale_or_rescaled_history(self):
        check = self.module()
        moment = np.ones((2, 3, 4), dtype=np.float32)
        count = np.ones((2, 3), dtype=np.float32)
        result = check.compare_statistics(moment, count, moment.copy(), count.copy())
        self.assertEqual(result['raw_moment_changed_pixels'], 0)
        self.assertEqual(result['direction_max_abs_difference'], 0)
        for changed_moment, changed_count in ((moment * 2, count), (moment, count * 2)):
            with self.subTest(count=changed_count[0, 0]), self.assertRaises(ValueError):
                check.compare_statistics(changed_moment, changed_count, moment, count)

    def test_invalid_controls_fail_before_runtime_verification(self):
        check = self.module()
        for offset in (-1, True, 2**32 - 10):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                check.frame_plan(offset, camera_cut=True)
        with self.assertRaises(ValueError):
            check.frame_plan(0, camera_cut=1)

    def test_full_system_comparison_is_bitwise_for_hdr_and_all_reservoir_scalars(self):
        check = self.module()
        color = np.ones((2, 3, 3), dtype=np.float32)
        reservoir = np.ones((2, 3, 4), dtype=np.float32)
        result = check.compare_system_state(color, reservoir, color.copy(), reservoir.copy())
        self.assertEqual(result['hdr_changed_pixels'], 0)
        self.assertEqual(result['reservoir_m_w_phat_changed_pixels'], 0)
        for index in range(3):
            changed = reservoir.copy()
            changed[0, 0, index] = np.nextafter(changed[0, 0, index], np.float32(2))
            with self.subTest(channel=index), self.assertRaises(ValueError):
                check.compare_system_state(color, changed, color, reservoir)
        changed = color.copy()
        changed[0, 0, 2] = np.nextafter(changed[0, 0, 2], np.float32(2))
        with self.assertRaises(ValueError):
            check.compare_system_state(changed, reservoir, color, reservoir)

    def test_real_diagnostic_exrs_and_runtime_seed_records_are_verified(self):
        import OpenEXR
        check = self.module()
        plan = check.frame_plan(100, camera_cut=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executed = []
            graph_seeds, graph_frames = {}, {}
            for event in plan:
                created = event['replace'] or event['graph'] not in graph_seeds
                if created:
                    graph_seeds[event['graph']], graph_frames[event['graph']] = 0, 0
                previous_seed = graph_seeds[event['graph']]
                graph_seeds[event['graph']] = event['path_seed']
                graph_frames[event['graph']] += 1
                camera = {'position': [int(event['pose'] == 'cut'), 0, 0], 'target': [0, 0, 1], 'up': [0, 1, 0]}
                executed.append({**event, 'actual_fixed_seed': event['path_seed'],
                                 'actual_clock_frame': event['clock_frame'], 'camera': camera,
                                 'graph_created': created, 'renders_on_graph': graph_frames[event['graph']],
                                 'fixed_seed_before_assignment': previous_seed})
                if event['capture'] is None:
                    continue
                for name in ('color', 'nrdEmission', 'nrdDiffuseRadianceHitDist',
                             'nrdSpecularRadianceHitDist', 'nrdResidualRadianceHitDist'):
                    rgba = np.ones((2, 3, 4), dtype=np.float32)
                    if name == 'nrdEmission' and event['capture'].startswith('before-'):
                        rgba[..., 3] = 2
                    channels = {channel: rgba[..., index] for index, channel in enumerate('RGBA')}
                    filename = f"{event['capture']}.PathTracer.{name}.{event['clock_frame']}.exr"
                    OpenEXR.File({}, channels).write(str(root / filename))
            log = root / 'executed-frames.json'
            log.write_text(json.dumps(executed))
            before = {path: path.read_bytes() for path in root.glob('*.exr')}
            result = check.verify_results(root, plan, 3, 2)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(set(result['comparisons']), {'reset', 'cut', 'replacement'})
            self.assertEqual(len(result['artifacts']), 45)
            self.assertEqual({path: path.read_bytes() for path in before}, before)
            altered = deepcopy(executed)
            altered[6]['actual_fixed_seed'] += 1
            log.write_text(json.dumps(altered))
            with self.assertRaises(ValueError):
                check.verify_results(root, plan, 3, 2)
            for field, value in (('graph_created', False), ('renders_on_graph', 2),
                                 ('fixed_seed_before_assignment', 1234)):
                altered = deepcopy(executed)
                altered[9][field] = value
                log.write_text(json.dumps(altered))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    check.verify_results(root, plan, 3, 2)
            altered = deepcopy(executed)
            for row in altered:
                row['camera']['position'] = [0, 0, 0]
            log.write_text(json.dumps(altered))
            with self.assertRaises(ValueError):
                check.verify_results(root, plan, 3, 2)
            log.write_text(json.dumps(executed))
            (root / 'unexpected.PathTracer.color.99.exr').write_bytes(b'extra frame')
            with self.assertRaises(ValueError):
                check.verify_results(root, plan, 3, 2)


if __name__ == '__main__':
    unittest.main()
