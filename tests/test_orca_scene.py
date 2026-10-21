"""ORCA scene settings remain data and keep their authored lighting."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/assets"))
from profiles.orca_scene import source_settings, finish_scene

class OrcaSceneTests(unittest.TestCase):
    def test_reads_environment_and_emission_without_executing_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "Temple.fbx"
            source.with_suffix(".pyscene").write_text('sceneBuilder.importScene("Temple.fbx")\nsceneBuilder.envMap = EnvMap("sky.hdr")\nfor m in sceneBuilder.materials:\n    m.emissiveFactor *= 1000\nraise RuntimeError("never execute")\n')
            (root / "sky.hdr").write_bytes(b"HDR fixture")
            settings = source_settings(source)
            self.assertEqual(settings["emissive_scale"], 1000)
            self.assertEqual(settings["environment"].name, "sky.hdr")

    def test_environment_cannot_escape_source_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "Scene.fbx"
            source.with_suffix(".pyscene").write_text('sceneBuilder.envMap = EnvMap("../sky.hdr")')
            with self.assertRaises(ValueError):
                source_settings(source)

    def test_wrapper_contains_environment_and_scales_emission_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "Temple.fbx"
            source.with_suffix(".pyscene").write_text('sceneBuilder.envMap = EnvMap("sky.hdr")\nm.emissiveFactor *= 1000')
            (root / "sky.hdr").write_bytes(b"HDR fixture")
            output = root / "converted/temple.gltf"
            output.parent.mkdir()
            output.write_text(json.dumps({"materials": [{"emissiveFactor": [1, .5, 0]}]}))
            metadata = {"camera": {"position": [1,2,3]}}
            record = finish_scene(source, output, metadata)
            material = json.loads(output.read_text())["materials"][0]
            self.assertEqual(material["extensions"]["KHR_materials_emissive_strength"]["emissiveStrength"], 1000)
            wrapper = json.loads(output.with_suffix(".scene.json").read_text())
            self.assertEqual(wrapper["environmentMaps"], ["environment.hdr"])
            self.assertEqual(record["camera"], metadata["camera"])
            self.assertEqual((output.parent / "environment.hdr").read_bytes(), b"HDR fixture")
