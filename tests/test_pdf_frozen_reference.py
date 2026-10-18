"""Dynamic target identity and fixed-state reference accumulation."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment.config import load_definition, make_config
from experiment.scenes import load_scene
from experiment.reference import reference_config, target, target_key


class FrozenReferenceTests(unittest.TestCase):
    def base(self):
        return make_config(load_scene("bistro"), load_definition(), "combined", "static")

    def test_light_state_changes_reference_identity_but_time_alone_does_not(self):
        config = self.base()
        a = copy.deepcopy(config["frames"][0])
        a.update(lighting={"material": "pink", "emissive_intensity_multiplier": 1.0},
                 logical_time_seconds=0.0)
        b = copy.deepcopy(a)
        b["lighting"]["emissive_intensity_multiplier"] = 2.0
        self.assertNotEqual(target_key(target(config, a, "assets")),
                            target_key(target(config, b, "assets")))
        b = copy.deepcopy(a)
        b["logical_time_seconds"] = 2.0
        self.assertEqual(target_key(target(config, a, "assets")),
                         target_key(target(config, b, "assets")))

    def test_every_accumulation_batch_freezes_the_captured_lighting_and_time(self):
        base = self.base()
        pose = copy.deepcopy(base["frames"][0])
        pose.update(lighting={"material": "pink", "emissive_intensity_multiplier": 1.5},
                    logical_time_seconds=1.25)
        original = copy.deepcopy(base)
        config = reference_config(base, pose, [16, 32, 64], 8, 1001, "POWER_RIS")
        for frame in config["frames"]:
            self.assertEqual(frame.get("lighting"), pose["lighting"])
            self.assertEqual(frame.get("logical_time_seconds"), 1.25)
            self.assertEqual(target(config, frame, "assets"), target(base, pose, "assets"))
        self.assertEqual(base, original)
        config["frames"][0]["lighting"]["emissive_intensity_multiplier"] = 9.0
        self.assertEqual(config["frames"][1]["lighting"], pose["lighting"])

    def test_identity_material_multiplier_reuses_the_unmodified_target(self):
        config = self.base()
        original = copy.deepcopy(config["frames"][0])
        identity = copy.deepcopy(original)
        identity["lighting"] = {"material": "pink", "emissive_intensity_multiplier": 1.0}
        self.assertEqual(target(config, original, "assets"), target(config, identity, "assets"))


if __name__ == "__main__":
    unittest.main()
