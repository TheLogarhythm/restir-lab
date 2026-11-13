import unittest
from scripts.falcor import reference_runner as runner


class ReferenceRunnerTests(unittest.TestCase):
    def test_eight_seed_ranges_are_disjoint_and_exact(self):
        sequences = [list(runner.sample_seeds(i, 1024)) for i in range(8)]
        self.assertTrue(all(len(s) == 1024 for s in sequences))
        self.assertEqual(len(set().union(*map(set, sequences))), 8192)

    def test_reject_invalid_sample_range(self):
        for seed, count in [(-1, 1), (0, 0), (8, 1024), (0, 1025)]:
            with self.subTest(seed=seed, count=count), self.assertRaises(ValueError):
                list(runner.sample_seeds(seed, count))

    def test_camera_target_is_position_plus_direction(self):
        camera = {'position': [1, 2, 3], 'direction': [-1, 0, 2], 'up': [0, 1, 0], 'vertical_fov': 60}
        self.assertEqual(runner.camera_target(camera), [0, 2, 5])

    def test_script_captures_only_after_all_frames(self):
        camera = {'position': [1, 2, 3], 'direction': [-1, 0, 2], 'up': [0, 1, 0], 'vertical_fov': 60}
        script = runner.render_script('scene.pyscene', camera, 'output', 7, 1024)
        compile(script, '<render>', 'exec')
        self.assertIn('range(1024)', script)
        self.assertIn('7168 + sample', script)
        self.assertLess(script.index('m.renderFrame()'), script.index('m.frameCapture.capture()'))

if __name__ == '__main__':
    unittest.main()

class SceneQualificationTests(unittest.TestCase):
    def test_explicit_unqualified_scene_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'not qualified'):
            runner.validate_scene_qualification({'ready_for_reference': False})

    def test_missing_qualification_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'not qualified'):
            runner.validate_scene_qualification({})

    def test_explicit_qualified_scene_is_accepted(self):
        runner.validate_scene_qualification({'ready_for_reference': True})

class BudgetTests(unittest.TestCase):
    def test_formal_requires_exact_approved_budget(self):
        runner.validate_render_budget(1024, 1920, 1080, scout=False)
        for samples, width, height in [(512, 1920, 1080), (1024, 640, 360)]:
            with self.subTest(samples=samples, width=width), self.assertRaises(ValueError):
                runner.validate_render_budget(samples, width, height, scout=False)

    def test_scout_limits(self):
        runner.validate_render_budget(16, 640, 360, scout=True)
        for samples, width, height in [(17, 640, 360), (16, 641, 360), (16, 640, 361)]:
            with self.subTest(samples=samples, width=width), self.assertRaises(ValueError):
                runner.validate_render_budget(samples, width, height, scout=True)

class AccumulationCheckTests(unittest.TestCase):
    def test_detects_correct_and_reset_accumulation(self):
        import numpy as np
        raw = [np.full((2, 2, 3), n, dtype=np.float32) for n in (1, 2, 4, 8)]
        cumulative = [np.mean(raw[:i], axis=0) for i in range(1, 5)]
        runner.validate_accumulation(raw, cumulative)
        cumulative[2] = raw[2].copy()
        with self.assertRaisesRegex(ValueError, 'accumulation mismatch'):
            runner.validate_accumulation(raw, cumulative)

    def test_detects_repeated_random_samples(self):
        import numpy as np
        same = np.ones((2, 2, 3), dtype=np.float32)
        with self.assertRaisesRegex(ValueError, 'repeated'):
            runner.validate_accumulation([same, same], [same, same])

class AssetInventoryTests(unittest.TestCase):
    def test_recursively_records_content_and_rejects_missing_files(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'scene.pyscene').write_text('scene')
            (root / 'assets').mkdir()
            (root / 'assets' / 'texture.bin').write_bytes(b'texture')
            config = {'scene_source': 'scene.pyscene', 'asset_roots': ['assets']}
            hashes = runner.asset_inventory(config, root)
            self.assertEqual(set(hashes), {'scene.pyscene', 'assets/texture.bin'})
            (root / 'assets' / 'texture.bin').unlink()
            config['asset_roots'] = ['assets/missing']
            with self.assertRaises(FileNotFoundError):
                runner.asset_inventory(config, root)

    def test_rejects_assets_outside_workspace(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'scene.pyscene').write_text('scene')
            with self.assertRaises(ValueError):
                runner.asset_inventory({'scene_source': 'scene.pyscene', 'asset_roots': ['..']}, root)

class IsolatedRuntimePatchTests(unittest.TestCase):
    def test_patch_changes_only_expected_call(self):
        from scripts.falcor import reference_runtime
        source = 'before SampleGenerator(neeSeed) after'
        self.assertEqual(reference_runtime.patch_shader(source),
                         'before SampleGenerator(uint2(0, 0), neeSeed) after')
        with self.assertRaises(ValueError):
            reference_runtime.patch_shader('unexpected upstream content')
        with self.assertRaises(ValueError):
            reference_runtime.patch_shader(source + source)

class CameraFrameValidationTests(unittest.TestCase):
    def setUp(self):
        import copy
        self.camera = {'position': [1, 2, 3], 'direction': [-1, 0, 2], 'up': [0, 1, 0], 'vertical_fov': 60}
        state = {'position': [1, 2, 3], 'target': [0, 2, 5], 'up': [0, 1, 0],
                 'frameHeight': 24, 'focalLength': 20.784609690826528, 'apertureRadius': 0,
                 'nearPlane': 0.01, 'farPlane': 100, 'animated': False}
        self.record = {key: copy.deepcopy(state) for key in ('initial', 'first_frame', 'last_frame')}
        self.record['first_frame']['frame'] = 1
        self.record['last_frame']['frame'] = 4

    def test_validates_initial_and_rendered_camera_against_requested_pose(self):
        runner.validate_camera_records(self.camera, self.record, 4)
        self.record['first_frame']['position'][0] += 1
        with self.assertRaisesRegex(ValueError, 'camera'):
            runner.validate_camera_records(self.camera, self.record, 4)

    def test_rejects_missing_frame_and_enabled_animation(self):
        self.record['last_frame']['frame'] = 3
        with self.assertRaisesRegex(ValueError, 'camera'):
            runner.validate_camera_records(self.camera, self.record, 4)
        self.record['last_frame']['frame'] = 4
        self.record['first_frame']['animated'] = True
        with self.assertRaisesRegex(ValueError, 'camera'):
            runner.validate_camera_records(self.camera, self.record, 4)

    def test_script_disables_animation_and_records_post_render_camera(self):
        script = runner.render_script('scene.pyscene', self.camera, 'output', 0, 4)
        self.assertIn('camera.animated = False', script)
        self.assertIn("camera_records['first_frame']", script)
        self.assertIn("camera_records['last_frame']", script)
        self.assertLess(script.index('m.renderFrame()'), script.index("camera_records['first_frame']"))
        compile(script, '<render>', 'exec')
