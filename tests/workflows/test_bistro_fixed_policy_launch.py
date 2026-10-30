"""Pinned launch selection must not silently restore the superseded Bistro policy."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/run"))
from experiment import controlled_launch as launch
from experiment.bistro_fixed_reference import policy_metadata


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BistroPolicyLaunchTests(unittest.TestCase):
    def fixture(self, root):
        (root / "reference-window.json").write_text("unchanged-window")
        (root / "execution-budget.json").write_text("unchanged-budget")
        value = {"version": 1, "scope": "bistro_fixed_single_stream_reference", "approved_by": "user",
                 "approved_utc": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                 "scene_reference_policies": {"bistro": policy_metadata()},
                 "reference_window_sha256": digest(root / "reference-window.json"),
                 "execution_budget_sha256": digest(root / "execution-budget.json")}
        path = root / "reference-policy.json"
        path.write_text(json.dumps(value))
        plan = {"reference_policy_file": str(path), "inputs": {str(path): digest(path)}}
        return path, value, plan

    def load(self, *args, **kwargs):
        self.assertTrue(hasattr(launch, "load_scene_reference_policies"), "explicit policy launch loader required")
        return launch.load_scene_reference_policies(*args, **kwargs)

    def test_legacy_defaults_only_when_no_new_policy_exists(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(self.load(root), {})
            self.fixture(root)
            with self.assertRaisesRegex(ValueError, "explicit"):
                self.load(root)

    def test_selected_pinned_policy_is_bistro_only_and_returns_fresh_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path, value, plan = self.fixture(root)
            result = self.load(root, plan)
            self.assertEqual(result, {"bistro": policy_metadata()})
            result["bistro"]["seeds"].append(2001)
            self.assertEqual(self.load(root, plan)["bistro"]["seeds"], [1001])
            self.assertEqual(self.load(root, policy_path=path), {"bistro": policy_metadata()})

    def test_new_policy_requires_declared_matching_launch_pin(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path, value, plan = self.fixture(root)
            for bad in ({"inputs": plan["inputs"]}, {**plan, "inputs": {}},
                        {**plan, "inputs": {str(path): "bad"}}):
                with self.subTest(plan=bad), self.assertRaises(ValueError):
                    self.load(root, bad)
            with self.assertRaises(ValueError):
                self.load(root, plan, policy_path=root / "other.json")

    def test_budget_window_and_policy_drift_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path, value, plan = self.fixture(root)
            changes = [{**value, "reference_window_sha256": "bad"},
                       {**value, "execution_budget_sha256": "bad"},
                       {**value, "approved_by": "unknown"},
                       {**value, "version": True},
                       {**value, "scene_reference_policies": {"arcade": policy_metadata()}},
                       {**value, "scene_reference_policies": {"bistro": {**policy_metadata(), "seeds": [1001, 2001]}}},
                       {**value, "scene_reference_policies": {"bistro": {**policy_metadata(), "local_samples_per_stream": 1048576}}}]
            for changed in changes:
                path.write_text(json.dumps(changed))
                plan["inputs"][str(path)] = digest(path)
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    self.load(root, plan)

    def test_policy_path_cannot_escape_suite(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            root = parent / "suite"
            root.mkdir()
            path, value, plan = self.fixture(parent)
            with self.assertRaises(ValueError):
                self.load(root, plan)


if __name__ == "__main__":
    unittest.main()
