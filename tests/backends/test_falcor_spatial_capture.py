from pathlib import Path
from unittest import TestCase
from scripts.falcor import cgns_paper_capture as off, cgns_temporal_capture as on


class SpatialCaptureTests(TestCase):
    def test_temporal_contrast_uses_identical_static_clock_and_path_seeds(self):
        camera = dict(position=[0, 0, 0], direction=[0, 0, 1], up=[0, 1, 0], vertical_fov=45)
        for mode in (off, on):
            with self.subTest(mode=mode.__name__):
                script = mode.render_script(
                    Path("scene"), camera, Path("out"), 2, 2, "baseline", adapted=False
                )
                self.assertIn("m.clock.framerate = 0", script)
                self.assertIn("tracer.fixedSeed = frame - 1", script)
                self.assertIn("if frame in [3, 4]", script)

    def test_resource_preflight_has_a_separate_bounded_budget(self):
        from scripts.falcor import spatial_capture as capture

        capture.validate_budget(1920, 1080, 0, 2, resource_preflight=True)
        for width, height, warmup, count in [
            (1920, 1080, 1, 1),
            (1920, 1080, 0, 3),
            (32, 18, 0, 1),
        ]:
            with self.subTest(count=count), self.assertRaises(ValueError):
                capture.validate_budget(width, height, warmup, count, resource_preflight=True)
        with self.assertRaises(ValueError):
            capture.validate_budget(1920, 1080, 0, 2)
