"""Portable checks for live scene selection and the registered camera contract."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
import warnings
from unittest.mock import MagicMock, patch

from scripts.falcor import live_scenes


class LiveSceneTests(unittest.TestCase):
    def test_seven_presets_follow_menu_order_and_default_exposure(self):
        self.assertEqual(live_scenes.SCENE_NAMES, (
            "Bistro Exterior", "Bistro Interior", "Classroom", "San Miguel",
            "Sun Temple", "Veach Ajar", "Zero Day Measure Seven",
        ))
        # Asset trees are optional in a clean checkout. The registered view and
        # profile files remain real so path or camera drift breaks this check.
        with patch.object(Path, "is_file", return_value=True):
            presets = [live_scenes.preset(name) for name in live_scenes.SCENE_NAMES]
        self.assertEqual([ev for _, _, ev in presets], [0, 7, 0, 8, 0, 0, 6])
        self.assertEqual([p.suffix for p, _, _ in presets], [".pyscene"] * 7)
        with self.assertRaises(ValueError):
            live_scenes.preset("Emerald Square")

    def test_custom_presets_resolve_to_renamed_scene_wrappers(self):
        with patch.object(Path, "is_file", return_value=True):
            for scene in ("bistro-interior", "san-miguel"):
                with self.subTest(scene=scene):
                    source, _, _ = live_scenes.preset(scene)
                    self.assertEqual(source, live_scenes.ROOT / "scenes/configs/falcor" / f"{scene}.pyscene")
        self.assertTrue((live_scenes.ROOT / "scenes/configs/falcor/bistro-interior.pyscene").is_file())
        self.assertTrue((live_scenes.ROOT / "scenes/configs/falcor/san-miguel.pyscene").is_file())

    def test_prepare_command_only_checks_the_sky(self):
        sky = live_scenes.ROOT / "assets/generated/san-miguel/live-default-sky.exr"
        output = StringIO()
        with (patch.object(Path, "is_file", autospec=True, side_effect=lambda path: path == sky),
              patch.dict("sys.modules", {"scripts.falcor.donut_procedural_sky": None}),
              patch("sys.argv", ["live_scenes", "--prepare"]),
              redirect_stdout(output),
              warnings.catch_warnings()):
            warnings.filterwarnings("ignore", message=".*found in sys.modules.*", category=RuntimeWarning)
            runpy.run_module("scripts.falcor.live_scenes", run_name="__main__")
        self.assertEqual(output.getvalue().splitlines(), [str(sky)])

    def test_indoor_flag_camera_and_return_to_native(self):
        falcor = SimpleNamespace(float3=lambda *v: tuple(v),
                                 SceneBuilderFlags=SimpleNamespace(DontOptimizeMaterials=123))
        renderer = MagicMock()
        renderer.scene = SimpleNamespace(camera=SimpleNamespace())
        with patch.dict("sys.modules", {"falcor": falcor}):
            self.assertEqual(live_scenes.load_scene(renderer, "bistro-interior"), 7.0)
            interior, view, _ = live_scenes.preset("Bistro Interior")
            renderer.loadScene.assert_called_once_with(str(interior), 123)
            self.assertEqual(renderer.scene.camera.nearPlane, 0.01)
            self.assertFalse(renderer.scene.animated)
            self.assertFalse(renderer.scene.camera.animated)
            renderer.scene = SimpleNamespace(camera=SimpleNamespace())
            self.assertEqual(live_scenes.load_scene(renderer, "Classroom"), 0.0)
            native, view, _ = live_scenes.preset("Classroom")
            renderer.loadScene.assert_called_with(str(native))
            camera = renderer.scene.camera
            self.assertEqual(camera.position, tuple(view["position"]))
            self.assertEqual(camera.target, tuple(a + b for a, b in zip(view["position"], view["direction"])))
            self.assertEqual(camera.up, tuple(view["up"]))
            self.assertAlmostEqual(camera.focalLength, 33.333331, places=4)
            self.assertFalse(hasattr(camera, "nearPlane"))
            self.assertEqual(renderer.clock.time, 0)

    def test_missing_scene_is_reported_before_camera_setup(self):
        renderer = MagicMock()
        renderer.scene = None
        falcor = SimpleNamespace(float3=tuple, SceneBuilderFlags=SimpleNamespace())
        with patch.dict("sys.modules", {"falcor": falcor}):
            with self.assertRaisesRegex(RuntimeError, "Classroom"):
                live_scenes.load_scene(renderer, "Classroom")
