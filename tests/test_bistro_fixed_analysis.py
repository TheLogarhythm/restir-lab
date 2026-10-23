"""Fixed Bistro reference provenance must never imply dual-stream precision."""
import copy
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment.controlled_evaluation import selection_spec
from experiment.images import write_pfm
from scripts.analysis.pdf_artifacts import export_condition
from scripts.analysis.pdf_summary import summarize_suite
from scripts.analysis.pdf_equal_time import analyze_equal_time

POLICY = {"policy_id": "user_fixed_single_stream_262144_v1", "scene_id": "bistro",
          "seeds": [1001], "local_samples_per_stream": 262144,
          "batch_counts": {"local": 64, "environment": 8, "infinite": 4},
          "resolution": [1920, 1080], "precision_checks": "not_evaluated",
          "label": "User-specified fixed-sample single-stream reference"}
REASON = ("User-authorized fixed-sample single-stream Bistro reference; "
          "uncertainty not evaluated under original dual-stream standard")


def assessment():
    return {key: {"status": "not_evaluated", "passed": None, "reason": REASON,
                  "policy_id": POLICY["policy_id"]} for key in ("temporal", "differences")}


class BistroFixedAnalysisTests(unittest.TestCase):
    def condition(self, root, *, scenario="motion", name="bistro-interior-motion"):
        root.mkdir()
        evaluation = selection_spec(scenario)
        refs = {}
        reference_dir = root / "references"
        reference_dir.mkdir()
        for frame in evaluation["reference_frames"]:
            path = reference_dir / f"frame-{frame:04d}.pfm.gz"
            write_pfm(path, np.ones((2, 2, 3)))
            refs[frame] = path
        runs = []
        for seed in (1, 2, 3):
            run = {"seed": seed}
            for method in ("off", "on"):
                directory = root / f"{method}-{seed}"
                directory.mkdir()
                run[f"{method}_dir"] = directory
                for frame in evaluation["reference_frames"]:
                    value = 1. if method == "on" or frame in evaluation["support_frames"] else 1. + seed
                    write_pfm(directory / f"frame-{frame:04d}.pfm.gz", np.full((2, 2, 3), value))
                count = 128 if scenario == "static" else 96
                timing = ["frame,gpu_ms,initial_ms,spatial_ms"]
                timing += [f"{frame},{seed * 10 * (2 if method == 'on' else 1)},1,3" for frame in range(1, count + 1)]
                (directory / "timings.csv").write_text("\n".join(timing) + "\n")
            runs.append(run)
        return {"id": name, "scenario": scenario, "references": refs, "runs": runs,
                "expected_resolution": (2, 2), "rois": [dict(name="receiver", x=0, y=0, width=1, height=1)],
                "evaluation": evaluation, "reference_policy": copy.deepcopy(POLICY),
                "reference_assessment": assessment()}

    def test_single_reference_summary_preserves_all_seeds_and_labels_uncertainty_not_evaluated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            condition = self.condition(root / "input")
            result = summarize_suite(root / "summary", [condition], references_accepted=True)
            self.assertFalse(result["reference_precision_verified"])
            self.assertEqual(result["conditions"][0]["reference_policy"], POLICY)
            self.assertFalse(result["conditions"][0]["reference_precision_verified"])
            self.assertEqual(result["conditions"][0]["reference_assessment"], assessment())
            self.assertEqual({row["seed"] for row in result["seed_metrics"]}, {1, 2, 3})
            self.assertEqual({row["frame"] for row in result["frame_metrics"]}, {32, 48, 96})
            self.assertEqual({row["previous_frame"] for row in result["frame_metrics"]}, {31, 47, 95})
            self.assertEqual({row["region"] for row in result["frame_metrics"]}, {"full", "receiver"})
            off = next(row for row in result["summaries"] if row["method"] == "pdf-off")
            self.assertAlmostEqual(off["rmae_mean"], 2.)
            self.assertAlmostEqual(off["trmae_mean"], 200.)
            self.assertEqual({row["timing_frame_count"] for row in result["seed_metrics"]}, {32})
            for row in result["paired_differences"]:
                for metric in ("smape", "rmae", "nrmse", "trmae"):
                    self.assertEqual(row[f"{metric}_reference_status"], "not_evaluated")
                    self.assertEqual(row[f"{metric}_direction"], "not_evaluated")
                    self.assertIsNone(row[f"{metric}_reference_max_change"])
            with (root / "summary/paired-differences.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual({row["smape_reference_status"] for row in rows}, {"not_evaluated"})
            saved = json.loads((root / "summary/analysis.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["conditions"][0]["reference_policy"], POLICY)
            text = (root / "summary/summary.md").read_text(encoding="utf-8")
            self.assertIn("NOT EVALUATED", text)
            self.assertIn("262144", text)
            self.assertIn("1001", text)
            self.assertNotIn("improvement resolved", text)

    def test_policy_export_retains_only_representative_artifacts_and_explicit_caption(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            condition = self.condition(root / "input")
            run = condition["runs"][0]
            result = export_condition(root / "artifacts", run["off_dir"], run["on_dir"], condition["references"],
                references_accepted=True, reference_policy=condition["reference_policy"],
                evaluation=condition["evaluation"], expected_resolution=(2, 2),
                temporal_scale=(0, 400), write_videos=False, rois=condition["rois"])
            self.assertEqual(result["reference_policy"], POLICY)
            self.assertFalse(result["reference_precision_verified"])
            self.assertIn("NOT EVALUATED", result["reference_caption"])
            self.assertIn("262144", result["reference_caption"])
            self.assertIn("1001", result["reference_caption"])
            self.assertEqual(result["videos"], [])
            self.assertEqual(result["frames"], [32, 48, 96])
            self.assertEqual(result["temporal_pairs"], [[31, 32], [47, 48], [95, 96]])
            self.assertEqual(len(result["inputs"]["reference"]), 6)
            self.assertFalse((root / "artifacts/videos").exists())
            with np.load(root / "artifacts/maps/pdf-off/frame-0048.npz") as maps:
                np.testing.assert_allclose(maps["trmae"], np.full((2, 2), 100.))
            saved = json.loads((root / "artifacts/manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["reference_policy"], POLICY)
            self.assertIn("NOT EVALUATED", (root / "artifacts/reference-caption.txt").read_text(encoding="utf-8"))

    def test_mixed_suite_keeps_legacy_receipts_separate_from_bistro_policy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixed = self.condition(root / "fixed", scenario="static", name="bistro-interior-static")
            legacy = self.condition(root / "legacy", scenario="static", name="cornell-static")
            legacy.pop("reference_policy")
            legacy["reference_assessment"] = {"differences": {"passed": True}}
            result = summarize_suite(root / "summary", [fixed, legacy], references_accepted=True)
            conditions = {row["id"]: row for row in result["conditions"]}
            self.assertFalse(conditions[fixed["id"]]["reference_precision_verified"])
            self.assertNotIn("reference_precision_verified", conditions[legacy["id"]])
            self.assertNotIn("reference_policy", conditions[legacy["id"]])
            pairs = {row["condition"]: row for row in result["paired_differences"] if row["region"] == "full"}
            self.assertEqual(pairs[fixed["id"]]["smape_reference_status"], "not_evaluated")
            self.assertEqual(pairs[legacy["id"]]["smape_reference_status"], "unassessed")
            self.assertEqual(pairs[fixed["id"]]["trmae_reference_status"], "not-applicable")
            text = (root / "summary/summary.md").read_text(encoding="utf-8")
            fixed_line = next(line for line in text.splitlines() if line.startswith("| bistro-"))
            legacy_line = next(line for line in text.splitlines() if line.startswith("| cornell-"))
            self.assertIn("NOT EVALUATED", fixed_line)
            self.assertNotIn("NOT EVALUATED", legacy_line)

    def test_malformed_fixed_policy_cannot_enable_the_uncertainty_exception(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            condition = self.condition(root / "input")
            condition["reference_policy"]["seeds"] = [1001, 2003]
            with self.assertRaises(ValueError):
                summarize_suite(root / "summary", [condition], references_accepted=True)
            run = condition["runs"][0]
            with self.assertRaises(ValueError):
                export_condition(root / "artifacts", run["off_dir"], run["on_dir"], condition["references"],
                    references_accepted=True, reference_policy=condition["reference_policy"],
                    evaluation=condition["evaluation"], expected_resolution=(2, 2),
                    temporal_scale=(0, 400), write_videos=False)
            self.assertFalse((root / "summary").exists())
            self.assertFalse((root / "artifacts").exists())

    def test_fixed_policy_does_not_bypass_image_seed_or_timing_integrity(self):
        for fault in ("missing-reference", "missing-seed", "bad-timing", "bad-image"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                condition = self.condition(root / "input")
                if fault == "missing-reference":
                    condition["references"].pop(47)
                elif fault == "missing-seed":
                    condition["runs"].pop()
                elif fault == "bad-timing":
                    path = condition["runs"][0]["off_dir"] / "timings.csv"
                    path.write_text(path.read_text().replace("1,10,1,3", "1,nan,1,3", 1))
                else:
                    write_pfm(condition["runs"][0]["on_dir"] / "frame-0032.pfm.gz", np.ones((1, 2, 3)))
                with self.assertRaises(ValueError):
                    summarize_suite(root / "summary", [condition], references_accepted=True)
                self.assertFalse((root / "summary").exists())

    def test_equal_time_rejects_mixed_reference_policies_and_changed_fixed_reference_hashes(self):
        from test_pdf_equal_time import EqualTimeTests
        for fault in ("mixed-policy", "changed-reference", "missing-reference-hash"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                source = root / "source"
                fixture = EqualTimeTests()
                analysis = fixture.fixture(source)
                for condition in analysis["conditions"]:
                    if fault != "mixed-policy" or condition["id"].endswith("-2"):
                        condition["reference_policy"] = copy.deepcopy(POLICY)
                    if fault != "mixed-policy":
                        digest = "a" * 64
                        if fault == "changed-reference" and condition["id"] == "bistro-interior-static-neighbors-8":
                            digest = "b" * 64
                        refs = {"128": {"path": "single-reference.pfm.gz", "sha256": digest}}
                        condition["inputs"] = {"references": refs}
                        if fault == "missing-reference-hash" and condition["id"] == "bistro-interior-static-neighbors-8":
                            refs["128"].pop("sha256")
                fixture.write(source, analysis)
                with self.assertRaisesRegex(ValueError, "policy|policies|reference|Reference"):
                    analyze_equal_time(source, root / "equal-time")
                self.assertFalse((root / "equal-time").exists())

    def test_equal_time_retains_fixed_policy_and_never_invents_reference_variants(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            rows, conditions = [], []
            for view in ("interior", "exterior"):
                for budget in (2, 4, 8):
                    name = f"bistro-{view}-static-neighbors-{budget}"
                    conditions.append({"id": name, "scenario": "static", "reference_policy": copy.deepcopy(POLICY),
                                       "reference_precision_verified": False, "reference_assessment": assessment()})
                    for seed in (1, 2, 3):
                        for method in ("pdf-off", "pdf-on"):
                            on = method == "pdf-on"
                            time = budget + (seed - 1) * .25 + int(on)
                            error = 40 - 2 * time + seed - (2 * seed - 1 if on else 0)
                            rows.append({"condition": name, "scenario": "static", "phase": "static-final", "region": "full",
                                         "seed": seed, "method": method, "gpu_ms": time,
                                         "smape": error, "rmae": error / 10, "nrmse": error / 20})
            analysis = {"references_accepted": True, "conditions": conditions, "seed_metrics": rows}
            (source / "analysis.json").write_text(json.dumps(analysis))
            with (source / "seed-metrics.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            result = analyze_equal_time(source, root / "equal-time")
            self.assertFalse(result["reference_precision_verified"])
            self.assertEqual(result["source"]["reference_policies"][conditions[0]["id"]], POLICY)
            for view in result["views"]:
                self.assertEqual(view["shared_gpu_ms"], [3.5, 8.])
                self.assertEqual(view["target_gpu_ms"], 5.75)
                self.assertEqual(len(view["estimates"]), 6)
                for row in view["paired_differences"].values():
                    self.assertEqual(row["reference_status"], "not_evaluated")
                    self.assertEqual(row["direction"], "not_evaluated")
                    self.assertIsNone(row["reference_variants"])
            self.assertIn("NOT EVALUATED", (root / "equal-time/summary.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
