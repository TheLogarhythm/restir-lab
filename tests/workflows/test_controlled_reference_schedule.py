"""Reference limits remain fixed across resumes and preserve saved work."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment.artifacts import save_json
from experiment.controlled_reference_run import CHECKPOINTS, ReferenceManager
from experiment.controlled_suite import build_config, conditions
from experiment.images import write_pfm
from experiment.reference import pfm_path, target, target_key

BUILD = {"renderer_commit": "renderer", "executable_sha256": "exe",
         "shader_sha256": {}, "integration_sha256": {}}


class ReferenceScheduleTests(unittest.TestCase):
    def test_accepted_count_excludes_saved_precision_cap_failures(self):
        manager = ReferenceManager.__new__(ReferenceManager)
        manager.index = {"references": {"passed": {"converged": True},
            "capped": {"converged": False}, "unfinished": {}}}
        self.assertEqual(manager.accepted_count, 1)

    def test_precision_cap_raises_typed_failure_after_preserving_checkpoints_and_receipt(self):
        from experiment import controlled_reference_run as controlled
        self.assertTrue(hasattr(controlled, "ReferencePrecisionError"),
                        "Precision cap failure needs a distinct exception type")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            condition = conditions()[0]
            config = build_config(condition, 1, False)
            frame = config["frames"][-1]
            value = target(config, frame, "assets")
            baseline = root / "baseline.pfm.gz"
            write_pfm(baseline, np.full((2, 2, 3), 1.2))
            capture = {"key": target_key(value), "target": value, "config": config,
                       "frame": frame, "image": baseline,
                       "manifest": {"scene": {"registry": "fixture"}}}
            manager = ReferenceManager(root / "references", BUILD, lambda **updates: None,
                                       checkpoints=[128, 256, 512])

            def render_checkpoint(resolved, attempt, *args, **kwargs):
                attempt.mkdir(parents=True)
                save_json(attempt / "config.json", resolved)
                save_json(attempt / "manifest.json", {"status": "completed"})
                samples = resolved["reference"]["checkpoints"][-1]
                image = np.full((2, 2, 3), 1. if resolved["seed"] == 1001 else 2.)
                write_pfm(pfm_path(attempt / f"frame-{samples // 64:04d}"), image)

            with mock.patch.object(controlled, "validate_lighting"), \
                 mock.patch.object(controlled, "validate_assets", return_value={"sha256": "assets"}), \
                 mock.patch.object(controlled, "validate_checkpoint"), \
                 mock.patch.object(controlled, "run_one", side_effect=render_checkpoint):
                with self.assertRaises(controlled.ReferencePrecisionError) as caught:
                    manager.ensure([capture])
            self.assertEqual(caught.exception.key, capture["key"])
            self.assertEqual(caught.exception.samples, 512)
            stored = manager.index["references"][capture["key"]]
            self.assertFalse(stored["converged"])
            self.assertEqual(stored["samples"], 512)
            receipt = manager.directory / stored["convergence"]
            self.assertTrue(receipt.is_file())
            self.assertEqual(len(list(manager.directory.rglob("checkpoint-*"))), 6)
            before = receipt.read_bytes()
            resumed = ReferenceManager(manager.directory, BUILD, lambda **updates: None,
                                       checkpoints=[128, 256, 512])
            self.assertEqual(resumed.index["references"], manager.index["references"])
            self.assertEqual(receipt.read_bytes(), before)

    def test_default_maximum_remains_one_million(self):
        self.assertEqual(CHECKPOINTS[-1], 1048576)

    def test_same_schedule_retains_accepted_record_and_checkpoint_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = ReferenceManager(root, BUILD, lambda **updates: None, checkpoints=[128, 256, 512])
            original.index["references"]["target"] = {"converged": True, "samples": 512, "image_sha256": "hdr"}
            save_json(original.index_path, original.index)
            checkpoint = root / "saved-checkpoint.pfm.gz"
            checkpoint.write_bytes(b"unchanged HDR payload")
            extended = ReferenceManager(root, BUILD, lambda **updates: None, checkpoints=[128, 256, 512])
            self.assertEqual(extended.checkpoints, (128, 256, 512))
            self.assertEqual(extended.index["checkpoints"], [128, 256, 512])
            self.assertEqual(extended.index["references"], original.index["references"])
            self.assertEqual(checkpoint.read_bytes(), b"unchanged HDR payload")

    def test_resume_rejects_any_checkpoint_schedule_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ReferenceManager(root, BUILD, lambda **updates: None, checkpoints=[128, 256, 512])
            before = (root / "reference-index.json").read_bytes()
            for schedule in ([128, 256], [256, 512, 1024], [128, 256, 1024], [128, 256, 512, 1024]):
                with self.subTest(schedule=schedule), self.assertRaises(ValueError):
                    ReferenceManager(root, BUILD, lambda **updates: None, checkpoints=schedule)
                self.assertEqual((root / "reference-index.json").read_bytes(), before)

    def test_budget_callback_stops_before_new_reference_launch(self):
        from experiment import controlled_reference_run as controlled
        with tempfile.TemporaryDirectory() as folder:
            guard = mock.Mock(side_effect=RuntimeError("Budget exhausted"))
            manager = ReferenceManager(Path(folder), BUILD, lambda **updates: None,
                                       before_segment=guard)
            capture = {"key": "target", "target": {"asset_sha256": "assets"},
                       "config": {"scene": {}, "scene_id": "bistro"},
                       "manifest": {"scene": {"registry": "fixture"}}}
            def try_stream(*args, **kwargs):
                args[6](1001, 128, 0, None, None)
            with mock.patch.object(controlled, "validate_lighting"), \
                 mock.patch.object(controlled, "validate_assets", return_value={"sha256": "assets"}), \
                 mock.patch.object(controlled, "run_pose", side_effect=try_stream), \
                 mock.patch.object(controlled, "run_one") as render:
                with self.assertRaisesRegex(RuntimeError, "Budget exhausted"):
                    manager.ensure([capture])
                render.assert_not_called()
                guard.assert_called_once()

    def test_invalid_new_or_saved_schedule_is_rejected(self):
        for schedule in ([], [True, 128], [0, 128], [64], [128, 257], [128, 256, 768], [2097152]):
            with self.subTest(schedule=schedule), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    ReferenceManager(Path(folder), BUILD, lambda **updates: None, checkpoints=schedule)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = ReferenceManager(root, BUILD, lambda **updates: None, checkpoints=[128, 256, 512])
            original.index["checkpoints"] = []
            save_json(original.index_path, original.index)
            with self.assertRaises(ValueError):
                ReferenceManager(root, BUILD, lambda **updates: None, checkpoints=[128, 256, 512, 1024])

    def test_extension_preserves_metric_seeds_batch_and_build_invariants(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = ReferenceManager(root, BUILD, lambda **updates: None, checkpoints=[128, 256, 512])
            for key, bad in (("convergence_metric", {"name": "different"}), ("seeds", [1002, 2001]),
                             ("batch_samples", 32), ("build", {**BUILD, "executable_sha256": "other"})):
                changed = copy.deepcopy(original.index)
                changed[key] = bad
                save_json(original.index_path, changed)
                with self.subTest(key=key), self.assertRaises(ValueError):
                    ReferenceManager(root, BUILD, lambda **updates: None, checkpoints=[128, 256, 512, 1024])


if __name__ == "__main__":
    unittest.main()
