"""Static FBX publication keeps pose, visibility and camera provenance together."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/assets"))
import convert_scene as converter


class StaticFrameTests(unittest.TestCase):
    CAMERA = {"position": [1, 2, 3], "direction": [0, 0, -1],
              "up": [0, 1, 0], "vertical_fov": 45}

    def export_fixture(self, output, frame):
        Image.new("RGB", (2, 2), (255, 128, 0)).save(output.parent / "packed.png")
        raw = {"asset": {"version": "2.0"}, "scenes": [{"nodes": []}],
               "nodes": [], "meshes": [],
               "materials": [{"extensions": {"KHR_materials_specular": {
                   "specularTexture": {"index": 0}}}}],
               "images": [{"uri": "packed.png"}], "textures": [{"source": 0}]}
        output.write_text(json.dumps(raw), encoding="utf-8")
        metadata = {"camera": self.CAMERA, "source_frame": frame,
                    "visibility_filter": "visible_and_renderable", "excluded_meshes": 2}
        output.with_suffix(".import.json").write_text(json.dumps(metadata), encoding="utf-8")
        return "fixture exporter"

    def test_invalid_options_cannot_publish_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fbx, gltf = root / "source.fbx", root / "source.gltf"
            fbx.write_bytes(b"placeholder")
            gltf.write_text("{}")
            for source, frame in ((fbx, -1), (fbx, True), (fbx, 1.5), (gltf, 1)):
                with self.subTest(source=source.name, frame=frame), self.assertRaises(ValueError):
                    converter.convert_scene(source, root / "output/scene.gltf", "orca", static_frame=frame)
                self.assertFalse((root / "output").exists())
            with self.assertRaises(ValueError):
                converter.convert_scene(fbx, root / "output/scene.gltf", "orca", visible_only=True)
            self.assertFalse((root / "output").exists())

    def test_camera_and_visibility_survive_staging_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.fbx"
            source.write_bytes(b"placeholder")

            def export(source, output, profile, **options):
                self.assertEqual(options["static_frame"], 17)
                self.assertTrue(options["visible_only"])
                return self.export_fixture(output, 17)

            with patch.object(converter, "export_scene", side_effect=export):
                record = converter.convert_scene(source, root / "output/scene.gltf", "orca",
                                                 static_frame=17, visible_only=True)
            self.assertEqual(record["source_frame"], 17)
            self.assertEqual(record["camera"], self.CAMERA)
            saved = json.loads((root / "output/scene.conversion.json").read_text())
            self.assertEqual(saved["camera"], self.CAMERA)
            self.assertEqual(saved["visibility_filter"], "visible_and_renderable")
            self.assertTrue(all((root / "output" / rel).is_file() for rel in saved["resources"]))

    def test_wrong_exported_frame_never_publishes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.fbx"
            source.write_bytes(b"unchanged source")
            with patch.object(converter, "export_scene",
                              side_effect=lambda source, output, profile, **kw:
                              self.export_fixture(output, 18)):
                with self.assertRaisesRegex(ValueError, "pose differs"):
                    converter.convert_scene(source, root / "output/scene.gltf", "orca", static_frame=17)
            self.assertFalse((root / "output").exists())
            self.assertEqual(source.read_bytes(), b"unchanged source")


    def test_unconfirmed_visibility_never_publishes(self):
        for policy, excluded in ((None, 2), ("all", 2), ("visible_and_renderable", -1)):
            with self.subTest(policy=policy, excluded=excluded), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                source = root / "source.fbx"
                source.write_bytes(b"source")

                def export(source, output, profile, **options):
                    version = self.export_fixture(output, 17)
                    metadata_path = output.with_suffix(".import.json")
                    metadata = json.loads(metadata_path.read_text())
                    metadata.update(visibility_filter=policy, excluded_meshes=excluded)
                    metadata_path.write_text(json.dumps(metadata))
                    return version

                with patch.object(converter, "export_scene", side_effect=export):
                    with self.assertRaisesRegex(ValueError, "visibility"):
                        converter.convert_scene(source, root / "output/scene.gltf", "orca",
                                                static_frame=17, visible_only=True)
                self.assertFalse((root / "output").exists())

    def test_animated_export_cannot_be_published_as_static(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.fbx"
            source.write_bytes(b"source")

            def export(source, output, profile, **options):
                version = self.export_fixture(output, 17)
                document = json.loads(output.read_text())
                document["animations"] = [{"channels": [], "samplers": []}]
                output.write_text(json.dumps(document))
                return version

            with patch.object(converter, "export_scene", side_effect=export):
                with self.assertRaisesRegex(ValueError, "animation"):
                    converter.convert_scene(source, root / "output/scene.gltf", "orca", static_frame=17)
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()
