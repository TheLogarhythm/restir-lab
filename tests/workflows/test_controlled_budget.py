"""The controlled suite has one persistent total wall-clock allowance."""
from datetime import datetime, timedelta, timezone
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment.controlled_budget import BudgetExceeded, ExperimentBudget


class ControlledBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "suite"
        self.directory.mkdir()
        self.current = datetime(2026, 10, 18, 0, 0, tzinfo=timezone.utc)

    def budget(self, **kwargs):
        return ExperimentBudget(self.directory, now=lambda: self.current, **kwargs)

    def manifest(self, relative, started):
        path = self.directory / relative / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"started_utc": started}), encoding="utf-8")

    def test_restart_preserves_original_allowance(self):
        first = self.budget()
        original = (self.directory / "execution-budget.json").read_bytes()
        self.current += timedelta(hours=6)
        restarted = self.budget()
        self.assertEqual(restarted.remaining_seconds(), 24 * 3600)
        self.assertEqual(restarted.record, first.record)
        self.assertEqual((self.directory / "execution-budget.json").read_bytes(), original)

    def test_earliest_nested_legacy_or_diagnostic_manifest_counts(self):
        self.manifest("runs/current", "2026-10-17T22:00:00+00:00")
        self.manifest("legacy-archive/reference/seed-1", "2026-10-17T05:00:00Z")
        self.manifest("diagnostics/check", "2026-10-17T20:00:00+00:00")
        unrelated = self.directory.parent / "retained-other-suite"
        unrelated.mkdir()
        (unrelated / "manifest.json").write_text('{"started_utc":"2020-01-01T00:00:00Z"}')
        budget = self.budget()
        self.assertEqual(budget.remaining_seconds(), 11 * 3600)
        self.assertEqual(budget.record["deadline_utc"], "2026-10-18T11:00:00+00:00")

    def test_expired_budget_never_resets_on_restart(self):
        self.budget()
        self.current += timedelta(hours=30)
        restarted = self.budget()
        self.assertEqual(restarted.remaining_seconds(), 0)
        with self.assertRaises(BudgetExceeded):
            restarted.check()
        with self.assertRaises(BudgetExceeded):
            restarted.timeout(120)
        self.current += timedelta(days=1)
        with self.assertRaises(BudgetExceeded):
            self.budget().check()

    def test_timeout_is_positive_and_capped_by_remaining_time(self):
        budget = self.budget()
        self.current += timedelta(hours=29, minutes=59, seconds=55)
        self.assertEqual(budget.timeout(120), 5)
        self.assertEqual(budget.timeout(2), 2)
        for invalid in (0, -1, float("inf"), float("nan"), True):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                budget.timeout(invalid)

    def test_saved_policy_cannot_change_duration_or_deadline(self):
        original = self.budget().record
        for key, value in (("limit_hours", 31), ("deadline_utc", "2026-10-19T07:00:00+00:00"),
                           ("started_utc", "2026-10-18T01:00:00+00:00"),
                           ("started_utc", "2026-10-18T00:00:00"),
                           ("deadline_utc", "invalid")):
            policy = {**original, key: value}
            path = self.directory / "execution-budget.json"
            path.write_text(json.dumps(policy), encoding="utf-8")
            before = path.read_bytes()
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.budget()
            self.assertEqual(path.read_bytes(), before)

    def test_policy_rejects_new_start_later_than_prior_manifest(self):
        self.manifest("legacy", "2026-10-17T05:00:00+00:00")
        original = self.budget().record
        policy = {**original, "started_utc": "2026-10-18T00:00:00+00:00",
                  "deadline_utc": "2026-10-19T06:00:00+00:00"}
        (self.directory / "execution-budget.json").write_text(json.dumps(policy), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.budget()

    def test_corrupt_policy_and_invalid_manifest_fail_closed(self):
        path = self.directory / "execution-budget.json"
        for text in ("not json", "[]", "{}"):
            path.write_text(text, encoding="utf-8")
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.budget()
        path.unlink()
        self.manifest("legacy", "2026-10-17T05:00:00")
        with self.assertRaises(ValueError):
            self.budget()
        self.assertFalse(path.exists())

    def test_requested_hours_cannot_extend_the_hard_limit(self):
        for hours in (31, 0, -1, True, float("inf"), float("nan")):
            with self.subTest(hours=hours), self.assertRaises(ValueError):
                self.budget(hours=hours)

    def window(self):
        original = self.budget().record
        path = self.directory / "reference-window.json"
        path.write_text(json.dumps({"version": 1, "scope": "sparse_references_and_analysis",
            "approved_by": "user", "approved_utc": "2026-10-18T16:15:00Z",
            "original_budget_sha256": hashlib.sha256((self.directory / "execution-budget.json").read_bytes()).hexdigest(),
            "not_before_utc": "2026-10-20T01:00:00Z", "deadline_utc": "2026-10-20T16:00:00Z"}))
        return path, original

    def test_explicit_reference_window_keeps_original_budget_and_blocks_early_start(self):
        path, original = self.window()
        window = self.budget(authorization=path)
        with self.assertRaises(BudgetExceeded):
            window.check()
        with self.assertRaises(BudgetExceeded):
            window.timeout(60)
        self.assertEqual(json.loads((self.directory / "execution-budget.json").read_text()), original)
        self.current = datetime(2026, 10, 20, 1, tzinfo=timezone.utc)
        resumed = self.budget(authorization=path)
        self.assertEqual(resumed.timeout(100000), 15 * 3600)
        self.current += timedelta(hours=14)
        self.assertEqual(self.budget(authorization=path).timeout(100000), 3600)
        self.current += timedelta(hours=1)
        with self.assertRaises(BudgetExceeded):
            self.budget(authorization=path).check()

    def test_reference_window_rejects_missing_approval_or_changed_original_budget(self):
        path, _ = self.window()
        valid = json.loads(path.read_text())
        for changes in ({"approved_by": "automatic"}, {"scope": "all_renders"},
                        {"original_budget_sha256": "different"},
                        {"deadline_utc": "2026-10-20T00:00:00Z"}):
            path.write_text(json.dumps({**valid, **changes}))
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.budget(authorization=path)


if __name__ == "__main__":
    unittest.main()
