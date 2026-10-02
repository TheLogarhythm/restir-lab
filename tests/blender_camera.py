"""Check authored camera framing with Blender; no assets or render required."""
import math
from pathlib import Path
import sys
import unittest
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/assets"))
from blender_scene import camera_record


class CameraTests(unittest.TestCase):
    def test_sensor_fit_and_pixel_aspect_preserve_vertical_fov(self):
        scene = bpy.context.scene
        data = bpy.data.cameras.new("fov-test")
        camera = bpy.data.objects.new("fov-test", data)
        scene.collection.objects.link(camera)
        data.lens, data.sensor_width, data.sensor_height = 50, 36, 24
        # Expected vertical sensor extent follows the fitted image plane.
        cases = [("HORIZONTAL", 1920, 1080, 1, 20.25),
                 ("AUTO", 1920, 1080, 1, 20.25),
                 ("VERTICAL", 1920, 1080, 1, 24),
                 ("AUTO", 1080, 1920, 1, 36),
                 ("HORIZONTAL", 1920, 1080, 2, 10.125)]
        for fit, width, height, pixel_x, sensor_extent in cases:
            with self.subTest(fit=fit, size=(width, height), pixel_x=pixel_x):
                data.sensor_fit = fit
                scene.render.resolution_x, scene.render.resolution_y = width, height
                scene.render.pixel_aspect_x, scene.render.pixel_aspect_y = pixel_x, 1
                record = camera_record(camera, scene)
                expected = math.degrees(2 * math.atan(sensor_extent / 100))
                self.assertAlmostEqual(record["vertical_fov"], expected, places=4)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CameraTests))
    if not result.wasSuccessful():
        raise RuntimeError("Camera regression failed")
