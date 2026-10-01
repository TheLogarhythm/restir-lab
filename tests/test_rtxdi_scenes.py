"""Scene-independent contracts for the RTXDI reuse experiment."""
import copy
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))


class SceneExperimentTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / "scripts/run/experiment/scenes.py").is_file(),
                        "scene-independent configuration is not implemented")
        self.scenes = importlib.import_module("experiment.scenes")
        self.config = importlib.import_module("experiment.config")

    def test_all_registered_scenes_share_mode_controls(self):
        definition = self.config.load_definition()
        for name in ("cornell-box", "arcade", "bistro", "zero-day-measure-one"):
            scene = self.scenes.load_scene(name)
            values = []
            for mode in self.config.MODES:
                config = self.config.make_config(scene, definition, mode, "static")
                self.assertEqual(config["width"], 1920)
                self.assertEqual(config["height"], 1080)
                self.assertEqual(config["frames"][0]["position"], scene["camera"]["position"])
                self.assertEqual(config["frames"][-1]["direction"], scene["camera"]["direction"])
                settings = dict(config["arguments"])
                settings.pop("restirDI.diMode")
                values.append(settings)
            self.assertTrue(all(value == values[0] for value in values))

    def test_scene_camera_drives_all_motion_frames(self):
        scene = self.scenes.load_scene("arcade")
        definition = self.config.load_definition()
        run = self.config.make_config(scene, definition, "combined", "motion", seed=7)
        self.assertEqual(run["frames"][31]["position"], scene["camera"]["position"])
        self.assertEqual(run["frames"][95]["position"], scene["motion"]["end_position"])
        self.assertEqual(run["frames"][127]["position"], scene["motion"]["end_position"])
        self.assertTrue(all(f["direction"] == scene["camera"]["direction"] for f in run["frames"]))
        self.assertEqual(run["frames"][0]["sampling_frame"], 7 * 1048576)
        reset = self.config.make_config(scene, definition, "combined", "reset")
        self.assertEqual([f["frame"] for f in reset["frames"] if f["reset"]], [1, 65])

    def test_dependency_closure_includes_wrapper_and_nested_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "model").mkdir()
            (root / "model/model.gltf").write_text(json.dumps({
                "buffers": [{"uri": "geometry.bin"}], "images": [{"uri": "color.png"}]}))
            (root / "model/geometry.bin").write_bytes(b"geometry")
            (root / "model/color.png").write_bytes(b"texture")
            (root / "ies-profiles").mkdir()
            (root / "ies-profiles/test.ies").write_bytes(b"photometry")
            entry = root / "test.scene.json"
            entry.write_text('{"models": ["model/model.gltf",], /* comment */ "graph": '
                             '[{"profile": "test.ies", "name": "https://example.com/,] /* string */"},],}')
            files = self.scenes.asset_files(entry, root)
            self.assertEqual(set(files), {"test.scene.json", "model/model.gltf",
                                         "model/geometry.bin", "model/color.png", "ies-profiles/test.ies"})

    def test_donut_dds_override_is_hashed_instead_of_png(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "color.png").write_bytes(b"unused png")
            (root / "color.dds").write_bytes(b"runtime dds")
            entry = root / "scene.gltf"
            entry.write_text(json.dumps({"images": [{"uri": "color.png"}]}))
            self.assertEqual(set(self.scenes.asset_files(entry, root)),
                             {"scene.gltf", "color.dds"})

    def test_external_uri_and_escaped_path_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / "bad.gltf"
            for uri in ("../private.bin", "https://example.com/texture.png"):
                entry.write_text(json.dumps({"buffers": [{"uri": uri}]}))
                with self.assertRaises(ValueError):
                    self.scenes.asset_files(entry, root)

    def test_invalid_camera_and_experiment_ranges_rejected(self):
        scene = self.scenes.load_scene("cornell-box")
        definition = self.config.load_definition()
        for seed in (-1, 4096):
            with self.assertRaises(ValueError):
                self.config.make_config(scene, definition, "initial", "static", seed=seed)
        broken = copy.deepcopy(definition)
        broken["motion"]["end_frame"] = broken["motion"]["start_frame"]
        with self.assertRaises(ValueError):
            self.config.make_config(scene, broken, "initial", "motion")
        bad_scene = copy.deepcopy(scene)
        bad_scene["camera"]["direction"] = [0, 0, 0]
        with self.assertRaises(ValueError):
            self.config.make_config(bad_scene, definition, "initial", "static")

    def test_new_scene_is_data_only(self):
        base = self.scenes.load_scene("cornell-box")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scenes/configs/rtxdi").mkdir(parents=True)
            scene = {k: copy.deepcopy(base[k]) for k in (
                "schema_version", "scene_id", "source", "camera", "motion", "lighting", "preview")}
            scene["scene_id"] = "future-scene"
            scene["source"] = {"kind": "file", "root": "assets/new", "entry": "new.gltf"}
            scene["camera"]["direction"] = [1, 0, 0]
            path = root / "scenes/configs/rtxdi/future-scene.json"
            path.write_text(json.dumps(scene))
            (root / "scenes/manifest.yaml").write_text(json.dumps({"scenes": [{
                "id": "future-scene", "backend_configs": {"rtxdi": "scenes/configs/rtxdi/future-scene.json"}}]}))
            loaded = self.scenes.load_scene("future-scene", root=root)
            run = self.config.make_config(loaded, self.config.load_definition(), "initial", "static")
            self.assertEqual(run["scene_id"], "future-scene")
            self.assertEqual(run["frames"][0]["direction"], [1, 0, 0])

if __name__ == "__main__":
    unittest.main()
