"""Controlled matrix resolution and fail-closed completed-run reuse."""
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/run"))


class ControlledSuiteTests(unittest.TestCase):
    def suite(self):
        spec = importlib.util.find_spec("experiment.controlled_suite")
        self.assertIsNotNone(spec, "the controlled suite API must exist")
        from experiment import controlled_suite
        return controlled_suite

    def test_campaign_rejects_ambiguous_condition_ids_and_execution_order(self):
        suite = self.suite()
        campaign = suite.load_campaign()
        for fault in ("duplicate-id", "missing-execution", "duplicate-execution", "unknown-view"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as folder:
                changed = copy.deepcopy(campaign)
                if fault == "duplicate-id":
                    changed["conditions"][1]["id"] = changed["conditions"][0]["id"]
                elif fault == "missing-execution":
                    changed["execution"]["order"].pop()
                elif fault == "duplicate-execution":
                    changed["execution"]["order"][1] = changed["execution"]["order"][0]
                else:
                    changed["conditions"][0]["view"] = "missing-view"
                path = Path(folder) / "campaign.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    suite.load_campaign(path)

    def test_matrix_resolves_eight_conditions_with_matched_off_on_controls(self):
        suite = self.suite()
        conditions = suite.conditions()
        self.assertEqual([c["id"] for c in conditions], [
            "cornell-static", "arcade-static", "bistro-interior-static", "bistro-exterior-static",
            "arcade-motion", "bistro-interior-motion", "bistro-exterior-motion", "bistro-lighting"])
        self.assertEqual(sum(c["scene"]["scene_id"] == "bistro" for c in conditions), 5)
        for condition in conditions:
            with self.subTest(condition=condition["id"]):
                before = copy.deepcopy(condition)
                off = suite.build_config(condition, 2, False)
                on = suite.build_config(condition, 2, True)
                self.assertEqual(condition, before)
                self.assertFalse(off["definition"].pop("pdf_similarity"))
                self.assertTrue(on["definition"].pop("pdf_similarity"))
                self.assertEqual(off, on)
                self.assertEqual((off["width"], off["height"], off["mode"], off["seed"]),
                                 (1920, 1080, "combined", 2))
                self.assertEqual(off["definition"]["pdf_history_mode"], 0)
                self.assertEqual([off["definition"][key] for key in (
                    "initial_local_candidates", "initial_environment_candidates", "initial_infinite_candidates",
                    "initial_brdf_candidates", "max_history_length", "spatial_neighbors", "spatial_radius")],
                    [24, 8, 1, 0, 20, 4, 32])
                self.assertEqual([f["frame"] for f in off["frames"] if f["reset"]], [1])
                self.assertEqual(len(condition["rois"]), 2)

    def test_static_captures_and_temporal_hold_transition_recovery_are_exact(self):
        suite = self.suite()
        for condition in suite.conditions():
            with self.subTest(condition=condition["id"]):
                config = suite.build_config(condition, 1, True)
                frames = config["frames"]
                if config["scenario"] == "static":
                    self.assertEqual(len(frames), 128)
                    self.assertEqual([f["frame"] for f in frames if f["capture"]], [1, 20, 40, 128])
                    self.assertTrue(all(f["position"] == frames[0]["position"] for f in frames))
                else:
                    self.assertEqual(len(frames), 96)
                    self.assertEqual([f["frame"] for f in frames if f["capture"]], list(range(1, 97)))
                    self.assertEqual([f["logical_time_seconds"] for f in frames], [i / 30 for i in range(96)])
                    self.assertEqual(config["definition"]["motion"], {"start_frame": 32, "end_frame": 64})
                    self.assertEqual(frames[31]["position"], frames[0]["position"])
                    self.assertEqual(frames[64]["position"], frames[63]["position"])
                    self.assertEqual(frames[95]["position"], frames[63]["position"])
                    if config["scenario"] == "motion":
                        self.assertNotEqual(frames[32]["position"], frames[31]["position"])
                        self.assertNotEqual(frames[63]["position"], frames[31]["position"])
                    else:
                        self.assertEqual(len({tuple(f["position"]) for f in frames}), 1)
                        multipliers = [f["lighting"]["emissive_intensity_multiplier"] for f in frames]
                        self.assertEqual(multipliers[:32], [1.] * 32)
                        self.assertEqual(multipliers[47], 2.)
                        self.assertEqual(multipliers[63:], [1.] * 33)
                        self.assertEqual(len(set(multipliers)), 17)

    def test_bistro_views_and_turns_are_different_before_method_selection(self):
        suite = self.suite()
        values = {c["id"]: c for c in suite.conditions()}
        interior = suite.build_config(values["bistro-interior-motion"], 1, False)
        exterior = suite.build_config(values["bistro-exterior-motion"], 1, False)
        self.assertNotEqual(interior["scene"]["camera"], exterior["scene"]["camera"])
        self.assertEqual(exterior["frames"][0]["position"], [-20., 1.8, 12.])
        self.assertEqual(exterior["frames"][63]["position"], [-19., 1.8, 12.5])
        self.assertAlmostEqual(exterior["frames"][63]["direction"][0], math.cos(math.radians(10)))
        self.assertAlmostEqual(abs(exterior["frames"][63]["direction"][2]), math.sin(math.radians(10)))
        for config in (interior, exterior):
            self.assertNotEqual(config["frames"][0]["direction"], config["frames"][63]["direction"])
            self.assertEqual(config["frames"][64]["direction"], config["frames"][63]["direction"])
        light = suite.build_config(values["bistro-lighting"], 1, False)
        self.assertEqual(light["scene"]["camera"], exterior["scene"]["camera"])
        self.assertEqual(light["definition"]["lighting"]["material"],
                         "LMBR_000019a_Paris_StringLights_01_Pink_Color")

    def test_ablation_parameters_and_validation_reach_resolved_configuration(self):
        suite = self.suite()
        condition = suite.conditions()[2]
        config = suite.build_config(condition, 3, True, mode="spatial", neighbors=8)
        self.assertEqual(config["mode"], "spatial")
        self.assertEqual(config["arguments"]["restirDI.spatialResampling.numSamples"], 8)
        self.assertEqual(config["arguments"]["restirDI.spatialResampling.numDisocclusionBoostSamples"], 8)
        for enabled in (0, 1, "false"):
            with self.subTest(enabled=enabled), self.assertRaises(ValueError):
                suite.build_config(condition, 1, enabled)
        for neighbors in (0, True, 33):
            with self.subTest(neighbors=neighbors), self.assertRaises(ValueError):
                suite.build_config(condition, 1, False, neighbors=neighbors)

    def test_condition_results_do_not_share_mutable_scene_definition_or_rois(self):
        suite = self.suite()
        values = suite.conditions()
        pristine = copy.deepcopy(values)
        values[2]["scene"]["camera"]["position"][0] = 999
        values[2]["definition"]["captures"]["static"].append(99)
        values[2]["rois"][0]["x"] = 999
        self.assertEqual(values[3:], pristine[3:])
        self.assertEqual(suite.conditions(), pristine)

    def test_motion_holds_share_exact_static_target_without_changing_the_later_trajectory(self):
        suite = self.suite()
        from experiment.config import make_config
        from experiment.reference import target, target_key
        conditions = {condition["id"]: condition for condition in suite.conditions()}
        for prefix in ("arcade", "bistro-interior", "bistro-exterior"):
            with self.subTest(view=prefix):
                condition = conditions[f"{prefix}-motion"]
                motion = suite.build_config(condition, 1, False)
                static = suite.build_config(conditions[f"{prefix}-static"], 1, False)
                asset_hash = condition["scene"]["registry"]["runtime_assets"]["sha256"]
                static_key = target_key(target(static, static["frames"][0], asset_hash))
                held_keys = [target_key(target(motion, frame, asset_hash)) for frame in motion["frames"][:32]]
                self.assertEqual(held_keys, [static_key] * 32)
                self.assertNotEqual(target_key(target(motion, motion["frames"][32], asset_hash)), static_key)
                original = make_config(condition["scene"], condition["definition"], "combined", "motion", 1,
                                       resolution=(1920, 1080))
                self.assertEqual(motion["frames"][32:], original["frames"][32:])
                self.assertEqual(len({tuple(frame["position"]) for frame in motion["frames"]}), 33)
                self.assertEqual(motion["frames"][63]["position"], condition["scene"]["motion"]["end_position"])
                self.assertEqual(motion["frames"][64:], original["frames"][64:])
                motion["frames"][0]["direction"][0] = 999
                motion["frames"][0]["up"][0] = 999
                self.assertEqual(motion["frames"][1]["direction"], static["frames"][0]["direction"])
                self.assertEqual(motion["frames"][1]["up"], static["frames"][0]["up"])
                self.assertNotEqual(condition["scene"]["camera"]["direction"][0], 999)


class CompletedRunTests(unittest.TestCase):
    def suite(self):
        return ControlledSuiteTests.suite(self)

    def record(self, directory, status="completed"):
        # A tiny file fixture is enough: reuse validates recorded bytes, not image decoding.
        expected = {"seed": 1, "definition": {"pdf_similarity": False},
                    "frames": [{"frame": 1, "capture": True}, {"frame": 2, "capture": False}]}
        config = {**expected, "output": ".", "repository_root": "../.."}
        config_path = directory / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        image = directory / "frame-0001.pfm.gz"
        image.write_bytes(b"recorded HDR bytes")
        captures = [{"frame": 1, "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest()}]
        (directory / "captures.json").write_text(json.dumps(captures), encoding="utf-8")
        manifest = {"status": status, "captures": captures,
                    "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest()}
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return expected

    def test_completed_capture_can_be_reused_in_a_different_run_directory(self):
        suite = self.suite()
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            expected = self.record(directory)
            expected.update(output="an/irrelevant/path", repository_root="a/different/root")
            before = copy.deepcopy(expected)
            self.assertTrue(suite.completed_run(directory, expected))
            self.assertEqual(expected, before)

    def test_missing_failed_and_interrupted_attempts_are_not_completed(self):
        suite = self.suite()
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            self.assertFalse(suite.completed_run(directory / "missing", {}))
            for status in ("failed", "interrupted", "running"):
                with self.subTest(status=status):
                    expected = self.record(directory, status)
                    self.assertFalse(suite.completed_run(directory, expected))

    def test_saved_or_expected_configuration_changes_are_rejected(self):
        suite = self.suite()
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            expected = self.record(directory)
            changed = copy.deepcopy(expected)
            changed["definition"]["pdf_similarity"] = True
            with self.assertRaisesRegex(ValueError, "config"):
                suite.completed_run(directory, changed)
            config_path = directory / "config.json"
            saved = json.loads(config_path.read_text())
            saved["seed"] = 2
            config_path.write_text(json.dumps(saved), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "config"):
                suite.completed_run(directory, expected)
            manifest_path = directory / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["config_sha256"] = hashlib.sha256(config_path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "config"):
                suite.completed_run(directory, expected)

    def test_modified_or_missing_images_are_rejected(self):
        suite = self.suite()
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            expected = self.record(directory)
            image = directory / "frame-0001.pfm.gz"
            image.write_bytes(b"changed HDR bytes")
            with self.assertRaisesRegex(ValueError, "image"):
                suite.completed_run(directory, expected)
            image.unlink()
            with self.assertRaisesRegex(ValueError, "image"):
                suite.completed_run(directory, expected)

    def test_capture_hash_list_and_exact_schedule_are_required(self):
        suite = self.suite()
        mutations = [lambda m: m["captures"].clear(),
                     lambda m: m["captures"].append(dict(m["captures"][0])),
                     lambda m: m["captures"][0].pop("image_sha256"),
                     lambda m: m["captures"][0].update(image_sha256="0" * 64)]
        for mutate in mutations:
            with self.subTest(mutation=mutate), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                expected = self.record(directory)
                path = directory / "manifest.json"
                manifest = json.loads(path.read_text())
                mutate(manifest)
                path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(ValueError):
                    suite.completed_run(directory, expected)
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            expected = self.record(directory)
            (directory / "captures.json").write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "capture"):
                suite.completed_run(directory, expected)


if __name__ == "__main__":
    unittest.main()
