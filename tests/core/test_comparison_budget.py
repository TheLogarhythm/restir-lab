"""Six-method target pairing and legacy DI reuse boundaries."""
import copy
import importlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts/run")]


class GroupedStaticTests(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module("experiment.comparison_config")

    def test_fixed_six_methods_and_two_targets(self):
        spec = self.api.load_spec()
        jobs = self.api.resolve_configs(spec)
        self.assertEqual(len(jobs), 30)
        self.assertEqual(set(spec["groups"]), {"DI", "GI", "PT"})
        self.assertEqual(spec["groups"]["GI"]["reference"], "full")
        self.assertEqual(spec["groups"]["PT"]["reference"], "full")
        for job in jobs:
            config = job["config"]
            self.assertEqual([config["width"], config["height"]], [1920, 1080])
            self.assertEqual(config["seed"], 1)
            self.assertEqual([f["frame"] for f in config["frames"] if f["capture"]], [41])
        altered = copy.deepcopy(spec)
        altered["groups"]["PT"]["reference"] = "direct"
        with self.assertRaises(ValueError):
            self.api.resolve_configs(altered)

    def test_di_configs_preserve_original_controls(self):
        from experiment.comparison_config import resolve_configs, load_spec, DI_SPEC
        original = resolve_configs(load_spec(DI_SPEC))
        new = self.api.resolve_configs(self.api.load_spec())
        for old in original:
            name = old["method"]
            actual = next(j["config"] for j in new if j["view"] == old["view"] and j["method"] == name)
            self.assertEqual(actual, old["config"])

    def test_formal_budget_cannot_expand_silently(self):
        for key, value in (("seeds", [1, 2]), ("resolution", [3840, 2160]), ("acquisition", {"protocol":"static","warmup_frames":20,"capture_frames":[21]})):
            spec = self.api.load_spec()
            spec[key] = value
            with self.assertRaises(ValueError):
                self.api.validate_approved_budget(spec)

    def test_grouped_error_sign_and_zero_baseline(self):
        sys.path.insert(0, str(ROOT))
        from scripts.analysis.comparison_diagnostics import comparison_summary
        result = comparison_summary({"all":20.0,"hard":0.0}, {"all":15.0,"hard":0.0})
        self.assertEqual(result["all"], {"original":20.0,"cgns":15.0,"improvement_pp":5.0,"relative_improvement_percent":25.0})
        self.assertIsNone(result["hard"]["relative_improvement_percent"])


if __name__ == "__main__":
    unittest.main()
