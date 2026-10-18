"""Reference limits remain fixed across resumes and preserve saved work."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment.artifacts import save_json
from experiment.controlled_reference_run import CHECKPOINTS, ReferenceManager

BUILD = {"renderer_commit": "renderer", "executable_sha256": "exe",
         "shader_sha256": {}, "integration_sha256": {}}


class ReferenceScheduleTests(unittest.TestCase):
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
