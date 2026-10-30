"""Unequal light budgets, legacy resume provenance and batch-mean accumulation."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment.artifacts import save_json
from experiment.config import load_definition, make_config
from experiment.images import write_pfm
from experiment.reference import reference_config, target
from experiment.scenes import load_scene
from experiment import reference_runner
from rtxdi_common import sha

COUNTS = {"local": 64, "environment": 8, "infinite": 4}


class ReferenceAllocationTests(unittest.TestCase):
    def setUp(self):
        self.base = make_config(load_scene("cornell-box"), load_definition(), "initial", "static", resolution=[2, 2])
        self.pose = self.base["frames"][0]

    def config(self, samples=128, **kwargs):
        return reference_config(self.base, self.pose, [samples], 64, 1001, "POWER_RIS", **kwargs)

    def totals(self, config):
        from experiment.reference_allocation import allocation_totals
        return allocation_totals(config)

    def test_fresh_budget_controls_actual_cli_and_records_requested_work(self):
        config = self.config(class_counts=COUNTS)
        self.assertEqual([config["definition"][f"initial_{c}_candidates"] for c in COUNTS], [64, 8, 4])
        self.assertEqual([config["arguments"][f"restirDI.initialSampling.num{c}Samples"]
                          for c in ("LocalLight", "Environment", "InfiniteLight")], [64, 8, 4])
        self.assertEqual(config["arguments"]["restirDI.neeLocalLightSampling.numLocalLightPowerRISSamples"], 64)
        self.assertEqual(self.totals(config), {"local": 128, "environment": 16, "infinite": 8})
        self.assertEqual(config["reference"]["allocation"]["progress_unit"], "local_samples_per_stream")
        self.assertEqual(target(config, config["frames"][-1], "assets"), target(self.base, self.pose, "assets"))

    def test_default_equal_budget_remains_legacy_compatible(self):
        config = self.config()
        before = copy.deepcopy(config)
        self.assertNotIn("allocation", config["reference"])
        self.assertEqual(self.totals(config), {"local": 128, "environment": 128, "infinite": 128})
        self.assertEqual(config, before)

    def test_legacy_uniform_sampling_keeps_its_mode_specific_budget(self):
        config = reference_config(self.base, self.pose, [128], 64, 1001, "UNIFORM")
        self.assertEqual(self.totals(config), {"local": 128, "environment": 128, "infinite": 128})

    def test_old_to_new_then_new_to_new_counts_and_rng_remain_contiguous(self):
        config = self.config(256, class_counts=COUNTS, previous_samples=128,
                             resume_image="old.pfm.gz", previous_class_samples=dict.fromkeys(COUNTS, 128))
        self.assertEqual(self.totals(config), {"local": 256, "environment": 144, "infinite": 136})
        self.assertEqual([f["frame"] for f in config["frames"]], [3, 4])
        self.assertEqual([f["sampling_frame"] for f in config["frames"]], [1049624578, 1049624579])
        self.assertEqual(config["reference"]["resume_batches"], 2)
        next_config = self.config(512, class_counts=COUNTS, previous_samples=256,
            resume_image="new.pfm.gz", previous_class_samples=self.totals(config))
        self.assertEqual(self.totals(next_config), {"local": 512, "environment": 176, "infinite": 152})

    def test_invalid_or_incomplete_positive_budgets_are_rejected(self):
        for counts in ({**COUNTS, "local": 32}, {**COUNTS, "environment": 0},
                       {**COUNTS, "infinite": True}, {**COUNTS, "environment": 65},
                       {"local": 64, "environment": 8}, {**COUNTS, "extra": 1}):
            with self.subTest(counts=counts), self.assertRaises(ValueError):
                self.config(class_counts=counts)
        with self.assertRaises(ValueError):
            self.config(256, class_counts=COUNTS, previous_samples=128, resume_image="old.pfm.gz")

    def test_diagnostic_and_mismatched_budget_metadata_cannot_be_full_references(self):
        for kind in ("diagnostic", "definition", "argument", "power_count", "brdf", "total", "previous"):
            config = self.config(class_counts=COUNTS)
            if kind == "diagnostic": config["reference"]["diagnostic_only"] = True
            elif kind == "definition": config["definition"]["initial_environment_candidates"] = 0
            elif kind == "argument": config["arguments"]["restirDI.initialSampling.numEnvironmentSamples"] = 64
            elif kind == "power_count": config["arguments"]["restirDI.neeLocalLightSampling.numLocalLightPowerRISSamples"] = 32
            elif kind == "brdf": config["definition"]["initial_brdf_candidates"] = 1
            elif kind == "total": config["reference"]["allocation"]["cumulative_samples"]["environment"] += 1
            else: config["reference"]["allocation"]["previous_samples"]["local"] = 64
            with self.subTest(kind=kind), self.assertRaises(ValueError): self.totals(config)

    def test_implicit_legacy_budget_cannot_hide_partial_light_components(self):
        config = self.config()
        config["definition"]["initial_environment_candidates"] = 0
        config["arguments"]["restirDI.initialSampling.numEnvironmentSamples"] = 0
        with self.assertRaises(ValueError): self.totals(config)

    def save_checkpoint(self, root, config, value=1.):
        root.mkdir(parents=True, exist_ok=True)
        image = root / f"frame-{config['reference']['checkpoints'][-1] // 64:04d}.pfm.gz"
        write_pfm(image, np.full((2, 2, 3), value))
        save_json(root / "config.json", config)
        save_json(root / "manifest.json", {"status": "completed", "scene": {"sha256": "assets"},
            "config_sha256": sha(root / "config.json"),
            "captures": [{"frame": config["reference"]["checkpoints"][-1] // 64, "image_sha256": sha(image)}]})
        return image

    def test_resume_binds_parent_counts_and_config_without_rewriting_legacy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            parent = self.save_checkpoint(root / "old", self.config())
            original = (parent.read_bytes(), (parent.parent / "config.json").read_bytes())
            child = self.config(256, class_counts=COUNTS, previous_samples=128, resume_image=parent,
                                previous_class_samples=dict.fromkeys(COUNTS, 128))
            child["reference"].update(resume_image_sha256=sha(parent),
                                      resume_config_sha256=sha(parent.parent / "config.json"))
            image = self.save_checkpoint(root / "new", child)
            sample = {"target": target(self.base, self.pose, "assets")}
            reference_runner.validate_checkpoint(image, sample, 1001, 256, 64,
                previous_samples=128, previous_image=parent, sampling="POWER_RIS")
            self.assertEqual((parent.read_bytes(), (parent.parent / "config.json").read_bytes()), original)
            for kind in ("parent_hash", "parent_counts"):
                bad = copy.deepcopy(child)
                if kind == "parent_hash": bad["reference"]["resume_config_sha256"] = "incorrect"
                else:
                    bad["reference"]["allocation"]["previous_samples"]["environment"] = 120
                    bad["reference"]["allocation"]["cumulative_samples"]["environment"] = 136
                self.save_checkpoint(root / "new", bad)
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    reference_runner.validate_checkpoint(image, sample, 1001, 256, 64,
                        previous_samples=128, previous_image=parent, sampling="POWER_RIS")

    def test_manager_reuses_legacy_stream_and_records_asymmetric_counts(self):
        from experiment import controlled_reference_run as controlled
        build = {"renderer_commit": "fixture", "executable_sha256": "exe",
                 "shader_sha256": {}, "integration_sha256": {}}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            baseline = root / "method.pfm.gz"
            write_pfm(baseline, np.full((2, 2, 3), 2.))
            value = target(self.base, self.pose, "assets")
            capture = {"image": baseline, "config": self.base, "frame": self.pose,
                       "target": value, "key": "target", "manifest": {"scene": {"registry": "fixture"}}}
            parent = root / "references/cornell-box/target"
            old = self.save_checkpoint(parent / "seed-1001/checkpoint-128/attempt-0", self.config())
            old_manifest = json.loads((old.parent / "manifest.json").read_text())
            old_manifest["build"] = build
            save_json(old.parent / "manifest.json", old_manifest)
            original = {p: p.read_bytes() for p in old.parent.iterdir()}
            launched = []

            def render(config, output, saved_build, assets, timeout, **kwargs):
                launched.append((config["seed"], config["reference"]["checkpoints"][0]))
                image = self.save_checkpoint(output, config)
                manifest = json.loads((output / "manifest.json").read_text())
                manifest["build"] = saved_build
                save_json(output / "manifest.json", manifest)

            with mock.patch.object(controlled, "validate_assets", return_value={"sha256": "assets"}), \
                 mock.patch.object(controlled, "validate_lighting"), \
                 mock.patch.object(controlled, "run_one", side_effect=render), \
                 mock.patch("experiment.artifacts.validate_run_outputs"):
                manager = controlled.ReferenceManager(root / "references", build, lambda **updates: None)
                manager.ensure([capture])
                self.assertNotIn((1001, 128), launched)
                self.assertEqual(len(launched), 5)
                result = json.loads((parent / "convergence.json").read_text())
                first = result["checkpoints"][0]["class_samples_by_stream"]
                self.assertEqual(first["1001"], {"local": 128, "environment": 128, "infinite": 128})
                self.assertEqual(first["2001"], {"local": 128, "environment": 16, "infinite": 8})
                record = manager.index["references"]["target"]
                self.assertEqual(record["sample_count_unit"], "local_samples_per_stream")
                self.assertEqual(record["class_samples_by_stream"]["1001"],
                                 {"local": 512, "environment": 176, "infinite": 152})
                self.assertEqual(record["class_samples_by_stream"]["2001"],
                                 {"local": 512, "environment": 64, "infinite": 32})
                snapshots = {p: p.read_bytes() for p in parent.glob("accepted-*/*")}
                extended = controlled.ReferenceManager(root / "references", build, lambda **updates: None)
                extended.ensure([capture])
                self.assertEqual(len(launched), 5)
                self.assertEqual(extended.index["references"]["target"], record)
                self.assertEqual({p: p.read_bytes() for p in parent.glob("accepted-*/*")}, snapshots)
            self.assertEqual({p: p.read_bytes() for p in old.parent.iterdir()}, original)

    def test_equal_budget_child_cannot_erase_unequal_parent_history(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            parent = self.save_checkpoint(root / "parent", self.config(class_counts=COUNTS))
            child = self.config(256, previous_samples=128, resume_image=parent)
            child["reference"]["resume_image_sha256"] = sha(parent)
            image = self.save_checkpoint(root / "child", child)
            sample = {"target": target(self.base, self.pose, "assets")}
            with self.assertRaisesRegex(ValueError, "allocation"):
                reference_runner.validate_checkpoint(image, sample, 1001, 256, 64,
                    previous_samples=128, previous_image=parent)

    def test_checkpoint_cap_cannot_extend_implicitly_after_first_precision_pass(self):
        from experiment import controlled_reference_run as controlled
        build = {"renderer_commit": "fixture", "executable_sha256": "exe",
                 "shader_sha256": {}, "integration_sha256": {}}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            baseline = root / "method.pfm.gz"
            write_pfm(baseline, np.full((2, 2, 3), 2.))
            capture = {"image": baseline, "config": self.base, "frame": self.pose,
                       "target": target(self.base, self.pose, "assets"), "key": "target",
                       "manifest": {"scene": {"registry": "fixture"}}}
            calls = []

            def render(config, output, saved_build, assets, timeout, **kwargs):
                samples = config["reference"]["checkpoints"][0]
                calls.append((config["seed"], samples))
                noise = {128: .7, 256: .2, 512: .01, 1024: 0.}[samples]
                self.save_checkpoint(output, config, 1 + (noise if config["seed"] == 1001 else -noise))
                manifest = json.loads((output / "manifest.json").read_text())
                manifest["build"] = saved_build
                save_json(output / "manifest.json", manifest)

            with mock.patch.object(controlled, "validate_assets", return_value={"sha256": "assets"}), \
                 mock.patch.object(controlled, "validate_lighting"), \
                 mock.patch.object(controlled, "run_one", side_effect=render), \
                 mock.patch("experiment.artifacts.validate_run_outputs"):
                manager = controlled.ReferenceManager(root / "references", build, lambda **updates: None,
                                                     checkpoints=[128, 256, 512])
                with self.assertRaisesRegex(RuntimeError, "precision not reached at 512"):
                    manager.ensure([capture])
                self.assertFalse(manager.index["references"]["target"]["converged"])
                self.assertEqual(len(calls), 6)
                old = {p: p.read_bytes() for p in (root / "references").glob("*/*/seed-*/checkpoint-*/*/*")}
                with self.assertRaisesRegex(ValueError, "checkpoint"):
                    controlled.ReferenceManager(root / "references", build, lambda **updates: None,
                                                checkpoints=[128, 256, 512, 1024])
                self.assertEqual(len(calls), 6)
                self.assertEqual({p: p.read_bytes() for p in old}, old)


if __name__ == "__main__":
    unittest.main()
