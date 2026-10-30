"""Fixed Bistro policy and single-stream checkpoint provenance regressions."""
import copy
import gzip
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment.artifacts import save_json
from experiment.config import load_definition, make_config
from experiment.images import write_pfm
from experiment.reference import reference_config, target, target_key
from experiment.reference_allocation import allocation_totals
from experiment.scenes import load_scene
from rtxdi_common import sha

try:
    fixed = importlib.import_module("experiment.bistro_fixed_reference")
except ModuleNotFoundError:
    fixed = None

COUNTS = {"local": 64, "environment": 8, "infinite": 4}
BUILD = {"renderer_commit": "renderer", "executable_sha256": "exe", "shader_sha256": {},
    "integration_sha256": {name: "integration" for name in (
        "scripts/run/build_rtxdi_experiments.py", "scripts/run/rtxdi_experiments.patch",
        "scripts/run/rtxdi_experiments/LabExperiment.h", "scripts/run/rtxdi_emission.py")},
    "donut": {"commit": "donut", "source_sha256": {"src/engine/GltfImporter.cpp": "importer"}}}


class FixedBistroReferenceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(fixed, "The fixed Bistro reference implementation is required")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.base = make_config(load_scene("bistro"), load_definition(),
                                "initial", "static", resolution=[1920, 1080])
        self.base["definition"]["renderer_commit"] = "renderer"
        self.pose = self.base["frames"][0]
        value = target(self.base, self.pose, "assets")
        self.capture = {"key": target_key(value), "target": value, "config": self.base,
            "frame": self.pose, "image": self.root / "baseline.pfm.gz",
            "manifest": {"scene": {"registry": "fixture"}, "build": BUILD}}
        write_pfm(self.capture["image"], np.ones((1080, 1920, 3), dtype=np.float32))
        self.notifications, self.launches = [], []
        directory = self.root / "references"
        directory.mkdir()
        self.manager = SimpleNamespace(directory=directory, build=BUILD,
            notify=lambda **updates: self.notifications.append(updates), timeout=60,
            before_segment=None, assets={}, index={"references": {}},
            index_path=directory / "reference-index.json")
        self.directory = directory / "bistro" / self.capture["key"]
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(fixed, "validate_assets", return_value={"sha256": "assets"}).start()
        # These fixtures retain real config/manifest/HDR validation; only GPU-output
        # receipts and the renderer process are outside this unit's boundary.
        mock.patch("experiment.artifacts.validate_run_outputs").start()
        mock.patch.object(fixed, "run_one", side_effect=self.render).start()

    def config(self, samples=262144, *, previous=None, counts=COUNTS):
        previous_samples = 0 if previous is None else json.loads(
            previous.with_name("config.json").read_text())["reference"]["checkpoints"][0]
        config = reference_config(self.base, self.pose, [samples], 64, 1001, "POWER_RIS",
            previous_samples=previous_samples, resume_image=previous, class_counts=counts,
            previous_class_samples=None if previous is None else allocation_totals(
                json.loads(previous.with_name("config.json").read_text())))
        if previous is not None:
            config["reference"].update(resume_image_sha256=sha(previous),
                resume_config_sha256=sha(previous.with_name("config.json")))
        return config

    def checkpoint(self, config, output=None):
        samples = config["reference"]["checkpoints"][0]
        output = output or self.directory / f"seed-1001/checkpoint-{samples}/attempt-0"
        output.mkdir(parents=True, exist_ok=False)
        image = output / f"frame-{samples // 64:04d}.pfm.gz"
        write_pfm(image, np.full((1080, 1920, 3), samples / 262144, dtype=np.float32))
        saved = copy.deepcopy(config)
        if saved["reference"].get("resume_image"):
            source = Path(saved["reference"]["resume_image"]).resolve()
            import os
            saved["reference"]["resume_image"] = Path(os.path.relpath(source, output)).as_posix()
        save_json(output / "config.json", saved)
        save_json(output / "manifest.json", {"status": "completed", "build": BUILD,
            "scene": {"sha256": "assets"}, "config_sha256": sha(output / "config.json"),
            "captures": [{"frame": samples // 64, "image_sha256": sha(image)}]})
        return image

    def replace_checkpoint_hdr(self, image, rgb):
        # Deliberately write malformed pixels without the production writer's
        # finite-value guard, then bind the actual payload in the real manifest.
        rgb = np.asarray(rgb, dtype="<f4")
        with gzip.open(image, "wb") as stream:
            stream.write(f"PF\n{rgb.shape[1]} {rgb.shape[0]}\n-1.0\n".encode("ascii"))
            stream.write(rgb[::-1].tobytes())
        manifest_path = image.with_name("manifest.json")
        manifest = json.loads(manifest_path.read_text())
        manifest["captures"][0]["image_sha256"] = sha(image)
        save_json(manifest_path, manifest)

    def render(self, config, output, build, assets, timeout, **kwargs):
        self.launches.append({"seed": config["seed"], "samples": config["reference"]["checkpoints"],
            "counts": config["reference"]["allocation"]["batch_counts"], "config": copy.deepcopy(config),
            "timeout": timeout() if callable(timeout) else timeout})
        self.assertEqual(build, BUILD)
        self.assertEqual(assets["sha256"], "assets")
        self.checkpoint(config, output)

    def ensure(self, captures=None):
        return fixed.ensure_fixed_bistro(self.manager, [self.capture] if captures is None else captures)

    def poison_excluded_sources(self):
        for seed, count in ((2001, 262144), (1001, 524288)):
            directory = self.directory / f"seed-{seed}/checkpoint-{count}/attempt-0"
            directory.mkdir(parents=True)
            (directory / "manifest.json").write_text("must not be read", encoding="utf-8")

    def test_policy_rejects_budget_seed_scene_resolution_or_precision_drift(self):
        metadata = fixed.policy_metadata()
        self.assertEqual(metadata, {"policy_id": "user_fixed_single_stream_262144_v1",
            "scene_id": "bistro", "seeds": [1001], "local_samples_per_stream": 262144,
            "batch_counts": {"local": 64, "environment": 8, "infinite": 4},
            "resolution": [1920, 1080], "precision_checks": "not_evaluated",
            "label": "User-specified fixed-sample single-stream reference"})
        normalized = fixed.validate_bistro_policy(metadata)
        self.assertEqual(normalized, metadata)
        self.assertIsNot(normalized, metadata)
        metadata["batch_counts"]["local"] = 1
        self.assertEqual(fixed.policy_metadata()["batch_counts"]["local"], 64)
        for name, value in (("seeds", [1001, 2001]), ("seeds", [1001.0]),
                ("local_samples_per_stream", 524288), ("scene_id", "arcade"),
                ("batch_counts", {"local": 64, "environment": 64, "infinite": 64}),
                ("resolution", [960, 540]), ("precision_checks", "passed"),
                ("unexpected", True)):
            bad = fixed.policy_metadata()
            bad[name] = value
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                fixed.validate_bistro_policy(bad)

    def test_reuses_only_exact_completed_checkpoint_and_keeps_sources(self):
        image = self.checkpoint(self.config())
        self.poison_excluded_sources()
        before = {p: p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        paths = self.ensure()[self.capture["key"]]
        self.assertEqual(self.launches, [])
        self.assertEqual(paths["image"], image)
        self.assertEqual(paths["streams"], [image])
        self.assertNotIn("previous_image", paths)
        self.assertNotIn("convergence", paths)
        self.assertEqual(paths["reference_policy"]["precision_checks"], "not_evaluated")
        record = self.manager.index["references"][self.capture["key"]]
        self.assertIs(record["ready"], True)
        self.assertIsNone(record["converged"])
        self.assertIs(record["precision_verified"], False)
        self.assertEqual(record["seeds"], [1001])
        self.assertEqual(record["samples"], 262144)
        self.assertEqual(record["class_samples_by_stream"],
                         {"1001": {"local": 262144, "environment": 32768, "infinite": 16384}})
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        self.assertEqual(fixed.fixed_record_paths(self.manager.directory, record), paths)
        self.ensure()
        self.assertEqual(self.launches, [])

    def test_missing_target_renders_one_capped_seed1001_segment_from_highest_parent(self):
        self.checkpoint(self.config(128))
        parent = self.checkpoint(self.config(512))
        self.poison_excluded_sources()
        preserved = {p: p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        result = self.ensure()[self.capture["key"]]
        self.assertEqual(len(self.launches), 1)
        launch = self.launches[0]
        self.assertEqual((launch["seed"], launch["samples"], launch["counts"]),
                         (1001, [262144], {"local": 64, "environment": 8, "infinite": 4}))
        self.assertEqual(launch["config"]["reference"]["resume_batches"], 8)
        self.assertEqual(Path(launch["config"]["reference"]["resume_image"]), parent)
        self.assertEqual(launch["config"]["reference"]["resume_image_sha256"], sha(parent))
        self.assertEqual(len(launch["config"]["frames"]), 4088)
        self.assertEqual(result["image"].parent.name, "attempt-0")
        self.assertEqual({p: p.read_bytes() for p in preserved}, preserved)

    def test_no_saved_checkpoint_starts_at_zero_and_preserves_failed_attempt(self):
        attempt = self.directory / "seed-1001/checkpoint-262144/attempt-0"
        attempt.mkdir(parents=True)
        save_json(attempt / "manifest.json", {"status": "failed", "error": "interrupted"})
        original = (attempt / "manifest.json").read_bytes()
        result = self.ensure()[self.capture["key"]]
        self.assertEqual(len(self.launches), 1)
        self.assertEqual(self.launches[0]["seed"], 1001)
        self.assertEqual(self.launches[0]["samples"], [262144])
        self.assertNotIn("resume_batches", self.launches[0]["config"]["reference"])
        self.assertEqual(result["image"].parent.name, "attempt-1")
        self.assertEqual((attempt / "manifest.json").read_bytes(), original)

    def test_deadline_guard_prevents_launch_and_retains_remaining_time_callback(self):
        def exhausted():
            raise RuntimeError("Budget exhausted")
        self.manager.before_segment = exhausted
        with self.assertRaisesRegex(RuntimeError, "Budget exhausted"):
            self.ensure()
        self.assertEqual(self.launches, [])
        self.assertEqual(self.manager.index["references"], {})
        calls = []
        def remaining():
            calls.append(True)
            return 17
        self.manager.before_segment = remaining
        self.ensure()
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.launches[0]["timeout"], 17)

    def test_rejects_non_bistro_wrong_resolution_and_mismatched_physical_keys(self):
        for kind in ("scene", "resolution", "key", "target"):
            capture = copy.deepcopy(self.capture)
            if kind == "scene":
                capture["config"]["scene_id"] = "arcade"
            elif kind == "resolution":
                capture["config"]["width"] = 960
            elif kind == "key":
                capture["key"] = "alias"
            else:
                capture["frame"]["position"][0] += 1
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.ensure([capture])
        self.assertEqual(self.launches, [])
        self.assertEqual(self.manager.index["references"], {})

    def test_checkpoint_tampering_and_final_allocation_drift_fail_closed(self):
        image = self.checkpoint(self.config())
        original = image.read_bytes()
        image.write_bytes(original + b"tamper")
        with self.assertRaisesRegex(ValueError, "modified"):
            self.ensure()
        image.write_bytes(original)
        config_path = image.with_name("config.json")
        config = json.loads(config_path.read_text())
        equal = self.config(counts={"local": 64, "environment": 64, "infinite": 64})
        save_json(config_path, equal)
        manifest_path = image.with_name("manifest.json")
        manifest = json.loads(manifest_path.read_text())
        manifest["config_sha256"] = sha(config_path)
        save_json(manifest_path, manifest)
        with self.assertRaises(ValueError):
            self.ensure()
        self.assertEqual(self.launches, [])

    def test_final_checkpoint_requires_actual_1080p_rgb_before_ready(self):
        image = self.checkpoint(self.config())
        self.replace_checkpoint_hdr(image, np.ones((2, 2, 3), dtype=np.float32))
        with self.assertRaisesRegex(ValueError, "resolution"):
            self.ensure()
        self.assertEqual(self.launches, [])
        self.assertEqual(self.manager.index["references"], {})
        self.assertFalse(self.manager.index_path.exists())
        self.assertFalse((self.directory / "fixed-policy.json").exists())

    def test_final_checkpoint_rejects_nonfinite_hdr_before_ready(self):
        image = self.checkpoint(self.config())
        for value in (float("nan"), float("inf"), -float("inf")):
            pixels = np.ones((1080, 1920, 3), dtype=np.float32)
            pixels[517, 931, 2] = value
            self.replace_checkpoint_hdr(image, pixels)
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Non-finite"):
                self.ensure()
            self.assertEqual(self.manager.index["references"], {})
            self.assertFalse(self.manager.index_path.exists())
        self.assertEqual(self.launches, [])

    def test_completed_target_rejects_wrong_actual_shape_in_required_parent(self):
        parent = self.checkpoint(self.config(128))
        self.replace_checkpoint_hdr(parent, np.ones((2, 2, 3), dtype=np.float32))
        self.checkpoint(self.config(previous=parent))
        with self.assertRaisesRegex(ValueError, "resolution"):
            self.ensure()
        self.assertEqual(self.launches, [])
        self.assertEqual(self.manager.index["references"], {})
        self.assertFalse(self.manager.index_path.exists())

    def test_nonfinite_resume_source_stops_before_new_segment_or_ready(self):
        parent = self.checkpoint(self.config(128))
        pixels = np.ones((1080, 1920, 3), dtype=np.float32)
        pixels[517, 931, 2] = float("nan")
        self.replace_checkpoint_hdr(parent, pixels)
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            self.ensure()
        self.assertEqual(self.launches, [])
        self.assertEqual(self.manager.index["references"], {})
        self.assertFalse(self.manager.index_path.exists())
        self.assertFalse((self.directory / "seed-1001/checkpoint-262144").exists())

    def test_record_reader_verifies_every_artifact_and_policy(self):
        self.checkpoint(self.config())
        self.ensure()
        record = self.manager.index["references"][self.capture["key"]]
        for name in ("image", "config", "manifest", "policy_metadata"):
            path = self.manager.directory / record[name]
            before = path.read_bytes()
            path.write_bytes(before + b"tamper")
            with self.subTest(name=name), self.assertRaises(ValueError):
                fixed.fixed_record_paths(self.manager.directory, record)
            path.write_bytes(before)
        for mutation in ({"seeds": [1001, 2001]}, {"samples": 524288},
                         {"precision_verified": True}, {"converged": True},
                         {"ready": False}, {"stream_images": ["averaged.pfm.gz"]}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                fixed.fixed_record_paths(self.manager.directory, {**record, **mutation})

    def test_resume_chain_cannot_cross_seed_or_cap(self):
        parent = self.checkpoint(self.config(128))
        image = self.checkpoint(self.config(previous=parent))
        config_path = image.with_name("config.json")
        config = json.loads(config_path.read_text())
        for source in (self.directory / "seed-2001/checkpoint-128/attempt-0/frame-0002.pfm.gz",
                       self.directory / "seed-1001/checkpoint-524288/attempt-0/frame-8192.pfm.gz"):
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"excluded source must not be used")
            config["reference"]["resume_image"] = str(source)
            save_json(config_path, config)
            manifest_path = image.with_name("manifest.json")
            manifest = json.loads(manifest_path.read_text())
            manifest["config_sha256"] = sha(config_path)
            save_json(manifest_path, manifest)
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.ensure()
        self.assertEqual(self.launches, [])

    def test_existing_fixed_record_is_not_silently_rebound_after_receipt_tampering(self):
        self.checkpoint(self.config())
        self.ensure()
        record = self.manager.index["references"][self.capture["key"]]
        metadata = self.manager.directory / record["policy_metadata"]
        metadata.write_bytes(metadata.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "modified"):
            self.ensure()
        self.assertEqual(self.launches, [])

    def test_record_rejects_excluded_paths_before_reading_any_forbidden_artifact(self):
        self.checkpoint(self.config())
        self.ensure()
        original = self.manager.index["references"][self.capture["key"]]
        real_sha = fixed.sha
        for name, value in (("image", "seed-2001/checkpoint-262144/attempt-0/frame-4096.pfm.gz"),
                ("image", "seed-1001/checkpoint-524288/attempt-0/frame-8192.pfm.gz"),
                ("image", "reference.pfm.gz"), ("config", "seed-2001/config.json"),
                ("manifest", "seed-2001/manifest.json"),
                ("policy_metadata", "seed-2001/fixed-policy.json")):
            path = self.directory / value
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"must not be read")
            record = copy.deepcopy(original)
            record[name] = path.relative_to(self.manager.directory).as_posix()
            record[f"{name}_sha256"] = sha(path)
            def guarded_sha(candidate):
                if Path(candidate).resolve() == path.resolve():
                    raise AssertionError("Forbidden reference artifact was read")
                return real_sha(candidate)
            with self.subTest(name=name, value=value), \
                 mock.patch.object(fixed, "sha", side_effect=guarded_sha), \
                 self.assertRaises(ValueError):
                fixed.fixed_record_paths(self.manager.directory, record)

    def test_resume_validation_reaches_every_ancestor(self):
        oldest = self.checkpoint(self.config(128))
        parent = self.checkpoint(self.config(256, previous=oldest))
        image = self.checkpoint(self.config(previous=parent))
        for current in (oldest, parent, image):
            config_path = current.with_name("config.json")
            config = json.loads(config_path.read_text())
            if current == oldest:
                config["frames"][0]["sampling_frame"] += 1
            else:
                previous = oldest if current == parent else parent
                config["reference"]["resume_config_sha256"] = sha(previous.with_name("config.json"))
            save_json(config_path, config)
            manifest_path = current.with_name("manifest.json")
            manifest = json.loads(manifest_path.read_text())
            manifest["config_sha256"] = sha(config_path)
            save_json(manifest_path, manifest)
        with self.assertRaisesRegex(ValueError, "accumulation or sampling"):
            self.ensure()
        self.assertEqual(self.launches, [])

    def test_valid_legacy_parent_totals_are_preserved_without_rewriting(self):
        parent = self.checkpoint(self.config(128, counts=None))
        before = {p: p.read_bytes() for p in parent.parent.iterdir()}
        self.ensure()
        record = self.manager.index["references"][self.capture["key"]]
        self.assertEqual(record["class_samples_by_stream"]["1001"],
                         {"local": 262144, "environment": 32880, "infinite": 16504})
        self.assertEqual({p: p.read_bytes() for p in before}, before)


if __name__ == "__main__":
    unittest.main()
