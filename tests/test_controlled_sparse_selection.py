"""Sparse reference targets retain exact physical states and strict gates."""
import copy
import importlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment.controlled_suite import build_config, conditions
from experiment.reference import target, target_key


def captures_for(condition, seed=1, enabled=False, mode="combined", neighbors=4):
    config = build_config(condition, seed, enabled, mode, neighbors)
    records = []
    for frame in config["frames"]:
        if frame["capture"]:
            value = target(config, frame, "fixture-assets-" + config["scene_id"])
            records.append({"directory": Path(condition["id"]) / mode / str(neighbors) / str(seed) / str(enabled),
                            "condition_id": condition["id"], "config": config, "frame": frame,
                            "image": Path(condition["id"]) / f"{frame['frame']}.pfm.gz",
                            "target": value, "key": target_key(value)})
    return records


class SparseSelectionTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("experiment.controlled_evaluation"),
                             "Sparse reference selection module is required")
        return importlib.import_module("experiment.controlled_evaluation")

    def test_selection_keeps_only_final_static_and_declared_dynamic_support(self):
        module = self.module()
        for condition in conditions():
            with self.subTest(condition=condition["id"]):
                selected = module.select_reference_captures(captures_for(condition))
                expected = [128] if condition["scenario"] == "static" else [31, 32, 47, 48, 95, 96]
                self.assertEqual([capture["frame"]["frame"] for capture in selected], expected)

    def test_missing_support_frame_and_duplicate_frame_are_rejected_per_run(self):
        module = self.module()
        condition = next(c for c in conditions() if c["id"] == "arcade-motion")
        records = captures_for(condition)
        for records in ([c for c in records if c["frame"]["frame"] != 47], records + [records[30]]):
            with self.subTest(count=len(records)), self.assertRaises(ValueError):
                module.select_reference_captures(records)

    def test_frozen_conditions_share_fifteen_exact_targets_across_all_variants(self):
        module = self.module()
        records = []
        for condition in conditions():
            for seed, enabled, mode, neighbors in ((1, False, "combined", 4),
                    (2, True, "combined", 4), (3, False, "spatial", 8), (3, True, "combined", 2)):
                records.extend(captures_for(condition, seed, enabled, mode, neighbors))
        selected = module.select_reference_captures(records)
        inventory = module.target_inventory(selected)
        self.assertEqual(inventory["state_count"], 15)
        self.assertEqual(len(inventory["states"]), 15)
        self.assertEqual([next(row["condition"] for row in state["selections"] if row["scenario"] == "static")
                          for state in inventory["states"][:4]],
                         ["cornell-static", "arcade-static", "bistro-interior-static", "bistro-exterior-static"])
        self.assertEqual(len({capture["key"] for capture in selected}), 15)
        light = next(c for c in conditions() if c["id"] == "bistro-lighting")
        light_records = module.select_reference_captures(captures_for(light))
        self.assertEqual(len({capture["key"] for capture in light_records}), 3)

    def test_inventory_serialization_is_identical_when_capture_order_is_reversed(self):
        module = self.module()
        records = []
        for condition in conditions():
            records.extend(captures_for(condition))
            records.extend(captures_for(condition, seed=2, enabled=True))
        selected = module.select_reference_captures(records)
        forward = module.target_inventory(selected)
        backward = module.target_inventory(reversed(selected))
        self.assertEqual(json.dumps(forward, sort_keys=True), json.dumps(backward, sort_keys=True))

    def test_inventory_rejects_incorrect_key_stale_target_and_variant_state_drift(self):
        module = self.module()
        condition = conditions()[0]
        selected = module.select_reference_captures(captures_for(condition))
        bad_key = copy.deepcopy(selected)
        bad_key[0]["key"] = "stale-key"
        bad_target = copy.deepcopy(selected)
        bad_target[0]["frame"]["position"][0] += 1
        drift = module.select_reference_captures(captures_for(condition, seed=2, enabled=True))
        drift[0] = copy.deepcopy(drift[0])
        drift[0]["frame"]["position"][0] += 1
        drift[0]["target"] = target(drift[0]["config"], drift[0]["frame"],
                                    drift[0]["target"]["asset_sha256"])
        drift[0]["key"] = target_key(drift[0]["target"])
        for records in (bad_key, bad_target, selected + drift):
            with self.subTest(records=records), self.assertRaises(ValueError):
                module.target_inventory(records, expected_states=1)

    def test_inventory_fails_when_frozen_state_count_changes(self):
        module = self.module()
        selected = module.select_reference_captures(captures_for(conditions()[0]))
        with self.assertRaisesRegex(ValueError, "15"):
            module.target_inventory(selected)

    def test_quality_filter_retains_all_held_and_ablation_equal_time_captures(self):
        module = self.module()
        condition = next(c for c in conditions() if c["id"] == "arcade-motion")
        records = captures_for(condition)
        records += captures_for(condition, seed=2, enabled=True, mode="spatial", neighbors=8)
        selected = module.select_reference_captures(records)
        start_key = next(c["key"] for c in selected if c["frame"]["frame"] == 32)
        quality = module.quality_captures(records, [start_key])
        self.assertEqual(len(quality), 64)
        self.assertEqual({c["frame"]["frame"] for c in quality}, set(range(1, 33)))
        self.assertEqual({c["config"]["mode"] for c in quality}, {"combined", "spatial"})
        with self.assertRaises(ValueError):
            module.quality_captures(records, ["missing"])

    def test_evaluation_receipts_are_independent_and_reject_modified_selection(self):
        module = self.module()
        expected = {"schema_version": 1, "spatial_frames": [32, 48, 96],
                    "support_frames": [31, 47, 95], "temporal_pairs": [[31, 32], [47, 48], [95, 96]],
                    "reference_frames": [31, 32, 47, 48, 95, 96]}
        self.assertEqual(module.selection_spec("motion"), expected)
        receipt = module.validate_selection(expected, "lighting")
        receipt["spatial_frames"].append(64)
        self.assertEqual(module.selection_spec("lighting"), expected)
        for changed in ({**expected, "spatial_frames": [32, 64, 96]},
                        {**expected, "temporal_pairs": [[32, 48]]},
                        {**expected, "schema_version": True}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                module.validate_selection(changed, "motion")
        with self.assertRaises(ValueError):
            module.selection_spec("reset")


if __name__ == "__main__":
    unittest.main()
