"""Regression coverage for reference checkpoints and resume provenance."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))
sys.path.insert(0, str(ROOT))
from experiment.artifacts import save_json, write_pfm
from experiment.config import make_config, load_definition
from experiment.scenes import load_scene
from experiment.reference import CONVERGENCE_METRIC, reference_config, target
from rtxdi_common import sha


class ReferenceCheckpointTests(unittest.TestCase):
    def test_checkpoint_lookup_only_accepts_one_completed_attempt(self):
        module = importlib.import_module("experiment.reference_runner")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for directory in (root / "seed-1001", root / "seed-1001/checkpoint-16", root / "seed-1001/checkpoint-16/attempt-0"):
                directory.mkdir(parents=True, exist_ok=True)
                write_pfm(directory / "frame-0002.pfm.gz", np.ones((2, 2, 3)))
            self.assertIsNone(module.checkpoint_image(root, 1001, 16, 8))
            attempt = root / "seed-1001/checkpoint-16/attempt-0"
            save_json(attempt / "manifest.json", {"status": "failed"})
            self.assertIsNone(module.checkpoint_image(root, 1001, 16, 8))
            save_json(attempt / "manifest.json", {"status": "completed"})
            self.assertEqual(module.checkpoint_image(root, 1001, 16, 8), attempt / "frame-0002.pfm.gz")
            other = attempt.with_name("attempt-1")
            other.mkdir()
            write_pfm(other / "frame-0002.pfm.gz", np.ones((2, 2, 3)))
            save_json(other / "manifest.json", {"status": "completed"})
            with self.assertRaisesRegex(ValueError, "Multiple completed"):
                module.checkpoint_image(root, 1001, 16, 8)

    def test_checkpoint_requires_image_hash_and_exact_sample_count(self):
        module = importlib.import_module("experiment.reference_runner")
        base = make_config(load_scene("cornell-box"), load_definition(), "initial", "static", resolution=[2, 2])
        sample = {"target": target(base, base["frames"][0], "assets")}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "frame-0002.pfm.gz"
            write_pfm(image, np.ones((2, 2, 3)))
            config = reference_config(base, base["frames"][0], [16], 8, 1001, "POWER_RIS")
            save_json(root / "config.json", config)
            manifest = {"status": "completed", "config_sha256": sha(root / "config.json"), "scene": {"sha256": "assets"}, "captures": [{"frame": 2}]}
            save_json(root / "manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "image hash"):
                module.validate_checkpoint(image, sample, 1001, 16, 8)
            manifest["captures"][0]["image_sha256"] = sha(image)
            config["reference"]["checkpoints"] = [16, 32]
            save_json(root / "config.json", config)
            manifest["config_sha256"] = sha(root / "config.json")
            save_json(root / "manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "incompatible"):
                module.validate_checkpoint(image, sample, 1001, 16, 8)

    def test_checkpoint_rejects_wrong_rng_and_resume_count(self):
        module = importlib.import_module("experiment.reference_runner")
        base = make_config(load_scene("cornell-box"), load_definition(), "initial", "static", resolution=[2, 2])
        sample = {"target": target(base, base["frames"][0], "assets")}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            previous = root / "previous.pfm.gz"
            image = root / "frame-0004.pfm.gz"
            for output in (previous, image):
                write_pfm(output, np.ones((2, 2, 3)))
            config = reference_config(base, base["frames"][0], [32], 8, 1001, "POWER_RIS", previous_samples=16, resume_image=previous)
            config["reference"]["resume_image_sha256"] = sha(previous)
            for mutation in ("rng", "accumulation"):
                changed = json.loads(json.dumps(config))
                if mutation == "rng":
                    changed["frames"][0]["sampling_frame"] += 1
                else:
                    changed["reference"]["resume_batches"] = 1
                save_json(root / "config.json", changed)
                save_json(root / "manifest.json", {"status": "completed", "config_sha256": sha(root / "config.json"),
                    "scene": {"sha256": "assets"}, "captures": [{"frame": 4, "image_sha256": sha(image)}]})
                with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "accumulation or sampling"):
                    module.validate_checkpoint(image, sample, 1001, 32, 8, previous_samples=16, previous_image=previous)

    def test_invalid_convergence_records_do_not_pass(self):
        from experiment.reference import reference_ready
        checks = [{"samples_per_class_per_stream": n, "regions": {"full": {"stream_disagreement_rmae": .001,
                   "change_rmae": None if n == 16 else .001}}} for n in (16, 32, 64)]
        for value in (float("nan"), float("inf"), -.001):
            checks[-1]["regions"]["full"]["stream_disagreement_rmae"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "checkpoint error"):
                reference_ready(checks, {"full": .02}, .1, CONVERGENCE_METRIC)

    def test_resume_rejects_old_schema_and_changed_checkpoint_prefix(self):
        module = importlib.import_module("experiment.reference_runner")
        from experiment.reference import REFERENCE_SCHEMA_VERSION
        settings = {"checkpoints": [16, 32, 64], "batch_samples": 8, "local_sampling": "POWER_RIS"}
        index = {"schema_version": REFERENCE_SCHEMA_VERSION, "convergence_metric": CONVERGENCE_METRIC,
                 "seeds": [1001, 2001], "checkpoint_settings": settings, "build": {"renderer_commit": "renderer", "executable_sha256": "exe", "shader_sha256": {}, "integration_sha256": {}}}
        module.validate_resume(index, [1001, 2001], [16, 32, 64, 128], 8, "POWER_RIS")
        for kwargs in ({"checkpoints": [32, 64, 128]}, {"batch": 16}, {"sampling": "UNIFORM"}, {"seeds": [1002, 2001]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                module.validate_resume(index, kwargs.get("seeds", [1001, 2001]), kwargs.get("checkpoints", [16, 32, 64]), kwargs.get("batch", 8), kwargs.get("sampling", "POWER_RIS"))
        with self.assertRaisesRegex(ValueError, "Unsupported reference"):
            module.validate_resume({**index, "schema_version": 1}, [1001, 2001], [16, 32, 64], 8, "POWER_RIS")


if __name__ == "__main__":
    unittest.main()
