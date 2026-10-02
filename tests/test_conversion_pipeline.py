"""Conversion publication must be all-or-nothing and preserve existing assets."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/assets"))
from convert_scene import convert_scene


class ConversionPipelineTests(unittest.TestCase):
    def fixture(self, root):
        raw = root / "source.gltf"
        raw.write_text(json.dumps({"asset": {"version": "2.0"},
            "buffers": [{"uri": "mesh.bin", "byteLength": 4}]}))
        (root / "mesh.bin").write_bytes(b"mesh")
        return raw, root / "converted" / "scene.gltf"

    def test_raw_conversion_copies_and_validates_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw, output = self.fixture(root)
            before = raw.read_bytes()
            convert_scene(raw, output, "san-miguel")
            doc = json.loads(output.read_text())
            self.assertEqual((output.parent / doc["buffers"][0]["uri"]).read_bytes(), b"mesh")
            record = json.loads(output.with_suffix(".conversion.json").read_text())
            self.assertTrue(record["resources"])
            self.assertEqual(record["profile"], "san-miguel")
            self.assertEqual(raw.read_bytes(), before)

    def test_missing_resource_does_not_publish_partial_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw, output = self.fixture(root)
            (root / "mesh.bin").unlink()
            with self.assertRaises((ValueError, OSError)):
                convert_scene(raw, output, "san-miguel")
            self.assertFalse(output.parent.exists())

    def test_existing_resource_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw, output = self.fixture(root)
            output.parent.mkdir()
            sentinel = output.parent / "mesh.bin"
            sentinel.write_bytes(b"keep")
            with self.assertRaises(FileExistsError):
                convert_scene(raw, output, "san-miguel")
            self.assertEqual(sentinel.read_bytes(), b"keep")

    def test_blender_failure_does_not_publish_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "scene.blend"
            source.write_bytes(b"fixture")
            output = root / "converted/scene.gltf"
            with patch("convert_scene.export_scene", side_effect=RuntimeError("export failed")):
                with self.assertRaisesRegex(RuntimeError, "export failed"):
                    convert_scene(source, output, "classroom")
            self.assertFalse(output.parent.exists())
