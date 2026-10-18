"""Bounded interpolation uses independent measured seed curves, never extrapolation."""
import copy
import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class EqualTimeTests(unittest.TestCase):
    def analyzer(self):
        spec = importlib.util.find_spec("scripts.analysis.pdf_equal_time")
        self.assertIsNotNone(spec, "the bounded equal-time analyzer must exist")
        from scripts.analysis.pdf_equal_time import analyze_equal_time
        return analyze_equal_time

    def fixture(self, directory, *, reference_change=None, disjoint=False):
        directory.mkdir()
        rows, conditions = [], []
        for view in ("interior", "exterior"):
            for budget, base_time in ((2, 2.), (4, 4.), (8, 8.)):
                condition_id = f"bistro-{view}-static-neighbors-{budget}"
                methods = {key: {"per_seed": {}} for key in ("False", "True")}
                metric_methods = {metric: copy.deepcopy(methods) for metric in ("smape", "rmae", "nrmse")}
                for seed in (1, 2, 3):
                    for method in ("pdf-off", "pdf-on"):
                        on = method == "pdf-on"
                        time = base_time + (seed - 1) * .25 + int(on)
                        error = 40 - 2 * time + seed - (2 * seed - 1 if on else 0)
                        row = {"condition": condition_id, "scenario": "static", "phase": "static-final",
                               "region": "full", "seed": seed, "method": method,
                               "gpu_ms": time + (20 if disjoint and on else 0),
                               "smape": error, "rmae": error / 10, "nrmse": error / 20}
                        rows.append(row)
                        if reference_change is not None:
                            for metric in metric_methods:
                                current = row[metric]
                                scale = 1 if metric == "smape" else .1 if metric == "rmae" else .05
                                change = reference_change * scale if on else 0
                                metric_methods[metric][str(on)]["per_seed"][str(seed)] = {
                                    "current": current, "half_a": current + change,
                                    "half_b": current - change, "previous": current + change / 2}
                assessment = None if reference_change is None else {"differences": {"passed": True,
                    "regions": {"full": {"static": {"metrics": {metric: {"methods": values}
                        for metric, values in metric_methods.items()}}}}}}
                conditions.append({"id": condition_id, "scenario": "static", "reference_assessment": assessment})
        analysis = {"schema_version": 1, "references_accepted": True, "seeds": [1, 2, 3],
                    "conditions": conditions, "seed_metrics": rows}
        self.write(directory, analysis)
        return analysis

    def write(self, directory, analysis):
        (directory / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
        with (directory / "seed-metrics.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(analysis["seed_metrics"][0]))
            writer.writeheader()
            writer.writerows(analysis["seed_metrics"])

    def test_known_linear_curves_use_all_six_time_ranges_and_paired_sample_sd(self):
        analyze = self.analyzer()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root / "summary")
            result = analyze(root / "summary", root / "equal-time")
            self.assertEqual(len(result["views"]), 2)
            for view in result["views"]:
                self.assertEqual(view["status"], "interpolated")
                self.assertEqual(view["shared_gpu_ms"], [3.5, 8.])
                self.assertEqual(view["target_gpu_ms"], 5.75)
                self.assertEqual(len(view["measured_points"]), 18)
                self.assertEqual(len(view["estimates"]), 6)
                off = [row for row in view["estimates"] if row["method"] == "pdf-off"]
                on = [row for row in view["estimates"] if row["method"] == "pdf-on"]
                self.assertEqual([row["smape"] for row in off], [29.5, 30.5, 31.5])
                self.assertEqual([row["smape"] for row in on], [28.5, 27.5, 26.5])
                smape = view["paired_differences"]["smape"]
                self.assertEqual(smape["seed_differences"], [-1., -3., -5.])
                self.assertEqual((smape["mean"], smape["sd"]), (-3., 2.))
                self.assertEqual(smape["reference_status"], "unassessed")
                self.assertEqual(smape["direction"], "no resolved difference")
                self.assertAlmostEqual(view["paired_differences"]["rmae"]["mean"], -.3)
                self.assertAlmostEqual(view["paired_differences"]["rmae"]["sd"], .2)
                self.assertAlmostEqual(view["paired_differences"]["nrmse"]["sd"], .1)
            output = root / "equal-time"
            for filename in ("analysis.json", "measured-points.csv", "interpolated-estimates.csv",
                             "paired-differences.csv", "summary.md", "frontier.png"):
                self.assertTrue((output / filename).is_file(), filename)
            report = (output / "summary.md").read_text(encoding="utf-8")
            self.assertIn("interpolated", report.lower())
            self.assertIn("on minus off", report)
            self.assertIn("no resolved difference", report)

    def test_disjoint_ranges_save_an_explicit_no_comparison_without_estimates(self):
        analyze = self.analyzer()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root / "summary", disjoint=True)
            result = analyze(root / "summary", root / "equal-time")
            for view in result["views"]:
                self.assertEqual(view["status"], "no-overlap")
                self.assertIsNone(view["target_gpu_ms"])
                self.assertEqual(view["estimates"], [])
                self.assertEqual(view["paired_differences"], {})
            self.assertIn("no equal-time comparison", (root / "equal-time/summary.md").read_text(encoding="utf-8"))

    def test_each_interpolation_bracket_contains_the_target_and_closest_measurement_is_retained(self):
        analyze = self.analyzer()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root / "summary")
            result = analyze(root / "summary", root / "equal-time")
            for view in result["views"]:
                for estimate in view["estimates"]:
                    self.assertLessEqual(estimate["lower_gpu_ms"], estimate["target_gpu_ms"])
                    self.assertGreaterEqual(estimate["upper_gpu_ms"], estimate["target_gpu_ms"])
                    self.assertGreaterEqual(estimate["interpolation_weight"], 0)
                    self.assertLessEqual(estimate["interpolation_weight"], 1)
                    self.assertIn(estimate["closest_neighbors"], (2, 4, 8))
                first = view["estimates"][0]
                self.assertEqual((first["seed"], first["method"], first["closest_neighbors"], first["closest_gpu_ms"]),
                                 (1, "pdf-off", 4, 4.))

    def test_reference_variants_are_interpolated_per_seed_before_interpreting_direction(self):
        analyze = self.analyzer()
        for change, status, direction in ((.1, "resolved", "improves"), (5., "inconclusive", "no resolved difference")):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.fixture(root / "summary", reference_change=change)
                result = analyze(root / "summary", root / "equal-time")
                paired = result["views"][0]["paired_differences"]["smape"]
                self.assertEqual(paired["reference_status"], status)
                self.assertEqual(paired["direction"], direction)
                self.assertAlmostEqual(paired["reference_variants"]["half_a"]["mean"], -3 + change)
                self.assertAlmostEqual(paired["reference_max_change"], change)

    def test_piecewise_interpolation_uses_the_adjacent_points_around_the_target(self):
        analyze = self.analyzer()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            analysis = self.fixture(root / "summary")
            analysis["seed_metrics"][6]["smape"] = 10.
            self.write(root / "summary", analysis)
            result = analyze(root / "summary", root / "equal-time")
            first = result["views"][0]["estimates"][0]
            self.assertEqual((first["lower_neighbors"], first["upper_neighbors"]), (4, 8))
            self.assertEqual(first["interpolation_weight"], .4375)
            self.assertEqual(first["smape"], 16.5625)

    def test_reference_stable_worsening_is_reported_without_assuming_pdf_helps(self):
        analyze = self.analyzer()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            analysis = self.fixture(root / "summary", reference_change=.1)
            conditions = {condition["id"]: condition for condition in analysis["conditions"]}
            for row in analysis["seed_metrics"]:
                if row["method"] != "pdf-on":
                    continue
                metrics = conditions[row["condition"]]["reference_assessment"]["differences"]["regions"]["full"]["static"]["metrics"]
                for metric, amount in (("smape", 10.), ("rmae", 1.), ("nrmse", .5)):
                    row[metric] += amount
                    values = metrics[metric]["methods"]["True"]["per_seed"][str(row["seed"])]
                    for variant in values:
                        values[variant] += amount
            self.write(root / "summary", analysis)
            result = analyze(root / "summary", root / "equal-time")
            for view in result["views"]:
                paired = view["paired_differences"]["smape"]
                self.assertEqual((paired["mean"], paired["sd"]), (7., 2.))
                self.assertEqual((paired["reference_status"], paired["direction"]), ("resolved", "worsens"))

    def test_missing_or_mismatched_per_seed_receipt_does_not_claim_a_direction(self):
        analyze = self.analyzer()
        for mismatch in (False, True):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                analysis = self.fixture(root / "summary", reference_change=.1)
                methods = analysis["conditions"][0]["reference_assessment"]["differences"]["regions"]["full"]["static"]["metrics"]["smape"]["methods"]
                if mismatch:
                    methods["False"]["per_seed"]["1"]["current"] = 999
                else:
                    methods["False"].pop("per_seed")
                self.write(root / "summary", analysis)
                result = analyze(root / "summary", root / "equal-time")
                paired = result["views"][0]["paired_differences"]["smape"]
                self.assertEqual(paired["reference_status"], "unassessed")
                self.assertEqual(paired["direction"], "no resolved difference")

    def test_incomplete_budget_seed_matrix_and_duplicate_times_fail_before_output(self):
        analyze = self.analyzer()
        for mutation in ("missing-seed", "duplicate-time", "nonfinite"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                analysis = self.fixture(root / "summary")
                if mutation == "missing-seed":
                    analysis["seed_metrics"].pop()
                elif mutation == "duplicate-time":
                    analysis["seed_metrics"][6]["gpu_ms"] = 2.
                else:
                    analysis["seed_metrics"][0]["gpu_ms"] = float("nan")
                self.write(root / "summary", analysis)
                with self.assertRaises(ValueError):
                    analyze(root / "summary", root / "equal-time")
                self.assertFalse((root / "equal-time").exists())

    def test_conflicting_csv_and_json_measurements_are_rejected(self):
        analyze = self.analyzer()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            analysis = self.fixture(root / "summary")
            csv_path = root / "summary/seed-metrics.csv"
            csv_path.write_text(csv_path.read_text().replace(
                str(analysis["seed_metrics"][0]["smape"]), "999", 1), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "CSV|JSON|disagree"):
                analyze(root / "summary", root / "equal-time")
            self.assertFalse((root / "equal-time").exists())


if __name__ == "__main__":
    unittest.main()
