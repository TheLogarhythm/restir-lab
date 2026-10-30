"""Extension workflow tests; no renderer, assets, or GPU required."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/run"))
from scripts.gallery.gallery_tools import catalog
from scripts.gallery.gallery_tools.site import build_html

CAMERA = {"position": [0, 2, -8], "direction": [0, 0, 1], "up": [0, 1, 0], "vertical_fov": 60}

def profile(sid):
    return {"source": {}, "camera": copy.deepcopy(CAMERA), "lighting": {},
            "registry": {"license": "test"}, "config_sha256": "profile-hash"}

def native(plan, view):
    return {"camera": view["camera"], "resolution": plan["resolution"],
            "settings": {**plan["render_settings"], **view.get("render_overrides", {})}}

class ExtensionTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / "tmp"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch, prefix="gallery-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "scenes").mkdir()
        self.settings = {"schema_version": 1, "resolution": [1920, 1080],
                         "scene_order": ["first"], "oidn_library": "local.dll",
                         "render_settings": {"frames": 128, "averaged_tail_frames": 32},
                         "definition_snapshot": {}}
        self.write("gallery.json", self.settings)
        self.scene = {"schema_version": 1, "scene_id": "first", "title": "First", "credit": "test",
                      "views": [{"id": "view-a", "title": "A", "camera": copy.deepcopy(CAMERA), "exposure_ev": 0}]}
        self.write("scenes/first.json", self.scene)

    def write(self, name, data):
        (self.root / name).write_text(json.dumps(data), encoding="utf-8")

    def plan(self):
        return catalog.load_plan(self.root, native, scene_loader=profile)

    def complete(self):
        plan = self.plan()
        view = plan["views"][0]
        view.update(status="completed", render_input_sha256=view["requested_input_sha256"],
                    outputs={"raw": {"path": "first/view-a/raw.png"},
                             "processed": {"path": "first/view-a/processed.png"}},
                    record="first/view-a/render-record.json")
        self.write("manifest.json", plan)
        return plan

    def test_new_scene_is_discovered_without_editing_code_or_order(self):
        self.complete()
        added = copy.deepcopy(self.scene)
        added.update(scene_id="second", title="Second")
        self.write("scenes/second.json", added)
        plan = self.plan()
        self.assertEqual(list(plan["scenes"]), ["first", "second"])
        self.assertEqual([v["status"] for v in plan["views"]], ["completed", "pending"])

    def test_camera_change_marks_only_that_view_stale(self):
        self.complete()
        self.scene["views"][0]["camera"]["position"][0] = 3
        self.write("scenes/first.json", self.scene)
        self.assertEqual(self.plan()["views"][0]["status"], "stale")

    def test_title_change_keeps_existing_render(self):
        self.complete()
        self.scene["views"][0]["title"] = "A clearer title"
        self.write("scenes/first.json", self.scene)
        self.assertEqual(self.plan()["views"][0]["status"], "completed")

    def test_missing_camera_is_planned_and_bad_selection_is_rejected(self):
        self.scene["views"].append({"id": "view-b", "title": "Choose camera", "camera": None})
        self.write("scenes/first.json", self.scene)
        plan = self.plan()
        self.assertEqual(plan["views"][1]["status"], "needs-camera")
        with self.assertRaisesRegex(ValueError, "Unknown view"):
            catalog.select_views(plan, ["first/misspelled"])

    def test_duplicate_and_path_like_ids_are_rejected(self):
        self.scene["views"].append(copy.deepcopy(self.scene["views"][0]))
        self.write("scenes/first.json", self.scene)
        with self.assertRaises(ValueError):
            self.plan()
        self.scene["views"] = [{"id": "../escape", "title": "bad", "camera": CAMERA}]
        self.write("scenes/first.json", self.scene)
        with self.assertRaises(ValueError):
            self.plan()

    def test_duplicate_camera_positions_are_rejected(self):
        other = copy.deepcopy(self.scene["views"][0])
        other["id"] = "view-b"
        other["camera"]["vertical_fov"] = 45
        self.scene["views"].append(other)
        self.write("scenes/first.json", self.scene)
        with self.assertRaisesRegex(ValueError, "position"):
            self.plan()

    def test_page_counts_follow_catalog_and_pending_views_do_not_show_old_images(self):
        self.complete()
        added = copy.deepcopy(self.scene)
        added.update(scene_id="second", title="Second")
        self.write("scenes/second.json", added)
        plan = self.plan()
        build_html(plan, self.root)
        page = (self.root / "index.html").read_text(encoding="utf-8")
        self.assertIn("2 个场景", page)
        self.assertIn("1 / 2 个机位", page)
        self.assertEqual(page.count("<img "), 2)
        self.assertIn("尚未渲染", page)
        self.scene["views"][0]["camera"]["position"][0] = 3
        self.write("scenes/first.json", self.scene)
        build_html(self.plan(), self.root)
        self.assertNotIn("<img ", (self.root / "index.html").read_text(encoding="utf-8"))

    def test_add_scene_creates_two_slots_without_overwriting_existing_config(self):
        path = catalog.add_scene(self.root, "new-scene", profile)
        doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(doc["views"]), 2)
        self.assertIsNone(doc["views"][1]["camera"])
        with self.assertRaisesRegex(ValueError, "already configured"):
            catalog.add_scene(self.root, "new-scene", profile)

    def test_unrecognized_setting_is_rejected(self):
        self.settings["render_settings"]["framess"] = 128
        self.write("gallery.json", self.settings)
        with self.assertRaisesRegex(ValueError, "Unknown render setting"):
            self.plan()


class RenderPathTests(unittest.TestCase):
    def test_native_capture_reaches_a_paired_png_without_gpu(self):
        """Exercise orchestration and float->PNG pairing with a mocked native process/OIDN."""
        from scripts.gallery import render as renderer
        import numpy as np
        from PIL import Image
        from unittest.mock import patch
        from types import SimpleNamespace
        scratch = ROOT / "tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch, prefix="gallery-render-test-") as temporary:
            here = Path(temporary)
            from experiment.config import load_definition
            from experiment.scenes import load_scene
            scene = load_scene("cornell-box")
            plan = {"resolution": [640, 360], "render_settings": {"frames": 128, "averaged_tail_frames": 1},
                    "definition_snapshot": load_definition(), "oidn_library": "fixture.dll",
                    "scenes": {"cornell-box": {}}, "views": [{"scene_id": "cornell-box", "id": "view-a",
                    "camera": scene["camera"], "exposure_ev": None}]}
            plan["resolution"] = [8, 4]
            plan["render_settings"].update(frames=128, averaged_tail_frames=1)
            view = copy.deepcopy(plan["views"][0])
            view.update(status="pending", exposure_ev=None, requested_input_sha256="fixture-input")
            view.pop("outputs", None)
            plan["views"] = [view]
            def fake_process(command, *, cwd, **kwargs):
                config = json.loads((cwd / "config.json").read_text(encoding="utf-8"))
                for frame in config["frames"]:
                    if frame["capture"]:
                        data = np.ones((config["height"], config["width"], 4), dtype="<f2")
                        data.tofile(cwd / f"frame-{frame['frame']:04d}.rgba16f")
                (cwd / "resolved.json").write_text("{}", encoding="utf-8")
                (cwd / "timings.csv").write_text("fixture", encoding="utf-8")
                return SimpleNamespace(returncode=0)
            with patch.object(renderer, "tool_sources", return_value={}), \
                 patch.object(renderer.subprocess, "run", side_effect=fake_process), \
                 patch.object(renderer, "validate_run_outputs"), patch.object(renderer, "OIDN") as oidn:
                oidn.return_value.denoise.side_effect = lambda rgb: (rgb.copy(), {"name": "test-only"})
                renderer.render(plan, view, scout=False, force=False, output_dir=here)
            output = here / view["scene_id"] / view["id"]
            with Image.open(output / "raw.png") as raw, Image.open(output / "processed.png") as processed:
                self.assertEqual(raw.size, (8, 4))
                self.assertEqual(raw.info["Linear source SHA256"], processed.info["Linear source SHA256"])
                self.assertEqual(raw.info["Display"], processed.info["Display"])
            self.assertEqual(view["render_input_sha256"], "fixture-input")
            self.assertIsNone(view["exposure_ev"])
            self.assertIsNotNone(view["rendered_exposure_ev"])
            self.assertFalse(list(here.rglob("*.rgba16f")))



class OutputDirectoryTests(unittest.TestCase):
    def test_sync_from_another_directory_only_writes_requested_gallery(self):
        import subprocess
        from experiment.config import load_definition
        from experiment.scenes import load_scene
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "gallery"
            (root / "scenes").mkdir(parents=True)
            scene = load_scene("cornell-box")
            settings = {"schema_version": 1, "resolution": [640, 360],
                        "scene_order": ["cornell-box"], "oidn_library": "unused.dll",
                        "render_settings": {"frames": 128, "averaged_tail_frames": 1},
                        "definition_snapshot": load_definition()}
            (root / "gallery.json").write_text(json.dumps(settings), encoding="utf-8")
            (root / "scenes/cornell-box.json").write_text(json.dumps({"schema_version": 1,
                "scene_id": "cornell-box", "title": "Cornell", "credit": "fixture",
                "views": [{"id": "view-a", "title": "A", "camera": scene["camera"], "exposure_ev": 0}]}), encoding="utf-8")
            result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/gallery/render.py"),
                                     "--output-dir", str(root), "--sync", "--html"],
                                    cwd=temporary, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(list(manifest["scenes"]), ["cornell-box"])
            self.assertEqual(manifest["views"][0]["status"], "pending")
            self.assertIn("Cornell", (root / "index.html").read_text(encoding="utf-8"))
            self.assertFalse((Path(temporary) / "manifest.json").exists())

if __name__ == "__main__":
    unittest.main()
