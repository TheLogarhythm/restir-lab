"""Scene profiles may select local HDR maps without losing resource validation."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/run"))
from experiment.scenes import load_scene, validate_scene


class SceneEnvironmentTests(unittest.TestCase):
    def test_local_hdr_environment_is_valid(self):
        scene = load_scene("classroom")
        scene["lighting"].update(environment="file", environment_map="environment.hdr")
        validate_scene(scene)

    def test_dark_environment_is_valid(self):
        scene = load_scene("classroom")
        scene["lighting"]["environment"] = "none"
        validate_scene(scene)

    def test_map_cannot_escape_asset_root(self):
        scene = load_scene("classroom")
        scene["lighting"].update(environment="file", environment_map="../outside.hdr")
        with self.assertRaises(ValueError):
            validate_scene(scene)

    def test_no_environment_resolves_no_environment_candidates(self):
        from experiment.config import load_definition, make_config
        scene = load_scene("classroom")
        scene["lighting"]["environment"] = "none"
        definition = load_definition()
        config = make_config(scene, definition, "combined", "static")
        self.assertEqual(config["definition"]["initial_environment_candidates"], 0)
        self.assertEqual(config["arguments"]["restirDI.initialSampling.numEnvironmentSamples"], 0)
        self.assertEqual(definition["initial_environment_candidates"], 8)
