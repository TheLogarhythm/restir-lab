"""One-shot launch plans check time, disk, inputs and duplicate consumption."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/run"))


class LaunchTests(unittest.TestCase):
    def test_launch_plan_rechecks_inputs_disk_window_and_one_shot_claim(self):
        from experiment.controlled_launch import validate_launch_plan, claim_launch
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.py"
            source.write_text("pinned")
            plan = root / "launch.json"
            plan.write_text(json.dumps({"version": 1, "suite_root": str(root),
                "not_before_utc": "2026-10-20T01:00:00Z", "deadline_utc": "2026-10-20T16:00:00Z",
                "minimum_free_bytes": 100, "inputs": {str(source): hashlib.sha256(source.read_bytes()).hexdigest()}}))
            now = datetime(2026, 10, 20, 1, tzinfo=timezone.utc)
            validate_launch_plan(root, plan, now=now, free_bytes=100)
            with self.assertRaisesRegex(ValueError, "disk"):
                validate_launch_plan(root, plan, now=now, free_bytes=99)
            with self.assertRaisesRegex(ValueError, "window"):
                validate_launch_plan(root, plan, now=datetime(2026, 10, 20, 0, tzinfo=timezone.utc), free_bytes=100)
            source.write_text("changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                validate_launch_plan(root, plan, now=now, free_bytes=100)
            claim_launch(plan)
            with self.assertRaises(FileExistsError):
                claim_launch(plan)


if __name__ == "__main__":
    unittest.main()
