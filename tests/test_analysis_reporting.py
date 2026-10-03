"""Report aggregation, timing weighting and image reuse checks."""
from collections import Counter
import importlib
import csv
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
from experiment import artifacts, reference
from rtxdi_common import sha
from build_fixtures import lighting_build


class AnalysisReportingTests(unittest.TestCase):
    def test_analysis_decodes_each_image_once_for_metrics_and_figures(self):
        self.check_analysis_fixture()

    def test_pdf_comparison_keeps_metrics_costs_and_images_separate(self):
        self.check_analysis_fixture(pdf_comparison=True)

    def check_analysis_fixture(self, pdf_comparison=False):
        from experiment.config import make_config, load_definition
        from experiment.scenes import load_scene
        report = importlib.import_module("scripts.analysis.di_reuse")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            baseline, refs = root / "baseline", root / "references"
            refs.mkdir()
            cases = (("off", "combined", 3.), ("on", "combined", 2.1)) if pdf_comparison else (
                ("initial", "initial", 3.), ("combined", "combined", 2.1))
            for name, mode, value in cases:
                directory = baseline / name
                directory.mkdir(parents=True)
                config = make_config(load_scene("cornell-box"), load_definition(), mode, "static", resolution=[2, 2])
                if name == "on":
                    config["definition"]["pdf_similarity"] = True
                config["frames"] = [config["frames"][0], config["frames"][-1]]
                artifacts.save_json(directory / "config.json", config)
                artifacts.save_json(directory / "manifest.json", {
                    "status": "completed", "config_sha256": sha(directory / "config.json"),
                    "scene": {"sha256": "fixture-assets"}, "gpu": "fixture-gpu",
                    "build": lighting_build()})
                artifacts.save_json(directory / "resolved.json", {})
                cost = 3 if name == "on" else 1
                (directory / "timings.csv").write_text(f"frame,gpu_ms\n1,{cost}\n128,{cost}\n")
                for frame in (1, 128):
                    artifacts.write_pfm(directory / f"frame-{frame:04d}.pfm.gz",
                                        np.full((2, 2, 3), value, dtype=np.float32))
            captures = reference.suite_captures(baseline)
            image = refs / "reference.pfm.gz"
            artifacts.write_pfm(image, np.full((2, 2, 3), 2., dtype=np.float32))
            checkpoints = [{"samples_per_class_per_stream": samples,
                "regions": {name: {"stream_disagreement_rmae": .0001,
                    "change_rmae": None if samples == 16 else .0001,
                    "threshold_rmae": .01} for name in reference.regions(2, 2)}}
                for samples in (16, 32, 64)]
            convergence = refs / "convergence.json"
            artifacts.save_json(convergence, {"schema_version": reference.REFERENCE_SCHEMA_VERSION, "convergence_metric": reference.CONVERGENCE_METRIC, "converged": True, "reference_noise_ratio": .1,
                                             "checkpoints": checkpoints})
            item = {"target": captures[0]["target"], "image": image.name, "image_sha256": sha(image),
                    "convergence": convergence.name, "convergence_sha256": sha(convergence), "converged": True}
            artifacts.save_json(refs / "reference-index.json", {"schema_version": reference.REFERENCE_SCHEMA_VERSION, "convergence_metric": reference.CONVERGENCE_METRIC, "references": {captures[0]["key"]: item},
                "samples_per_class_per_stream": 64, "seeds": [1001, 2001], "build": lighting_build()})
            arguments = ["di_reuse", "--baseline"]
            arguments += [str(baseline / name) for name in ("off", "on")] if pdf_comparison else [str(baseline)]
            arguments += ["--references", str(refs), "--output", str(baseline / "analysis")]
            with mock.patch.object(sys, "argv", arguments), \
                 mock.patch.object(reference, "read_pfm", wraps=reference.read_pfm) as reader:
                report.main()
                counts = Counter(Path(call.args[0]) for call in reader.call_args_list)
                self.assertEqual(len(counts), 5)  # Four baseline images plus one shared reference.
                self.assertTrue(all(count == 1 for count in counts.values()))
            output = baseline / "analysis"
            self.assertTrue((output / "metrics.csv").is_file())
            self.assertTrue((output / "summary.md").is_file())
            self.assertEqual(len(list(output.glob("*.png"))), 2)
            summary = (output / "summary.md").read_text()
            self.assertIn("Reference acceptance", summary)
            self.assertIn("Single baseline seed", summary)
            self.assertIn("Steady GPU ms", summary)
            self.assertTrue((output / "tail-diagnostics.csv").is_file())
            if pdf_comparison:
                for filename in ("metrics.csv", "summary.csv", "timings.csv", "tail-diagnostics.csv"):
                    with (output / filename).open(newline="") as stream:
                        rows = list(csv.DictReader(stream))
                    self.assertEqual({r["method"] for r in rows}, {"restir_di", "pdf_similarity"})
                with (output / "summary.csv").open(newline="") as stream:
                    rows = [r for r in csv.DictReader(stream) if r["frame"] == "128" and r["region"] == "full"]
                self.assertEqual(len(rows), 2)
                errors = {r["method"]: float(r["rmae_mean"]) for r in rows}
                self.assertAlmostEqual(errors["restir_di"], .5)
                self.assertAlmostEqual(errors["pdf_similarity"], .05, places=6)
                self.assertIn("| PDF off | combined | 0.5000 | 0.5000 | 1.00 |", summary)
                self.assertIn("| PDF on | combined | 0.0500 | 0.0500 | 3.00 |", summary)
            self.assertEqual(list(root.rglob("*.pfm")), [])
            old = json.loads(convergence.read_text())
            old.pop("convergence_metric")
            artifacts.save_json(convergence, old)
            item["convergence_sha256"] = sha(convergence)
            artifacts.save_json(refs / "reference-index.json", {"schema_version": reference.REFERENCE_SCHEMA_VERSION, "convergence_metric": reference.CONVERGENCE_METRIC, "references": {captures[0]["key"]: item}, "build": lighting_build()})
            legacy_output = baseline / "legacy-analysis"
            with mock.patch.object(sys, "argv", arguments[:-1] + [str(legacy_output)]):
                with self.assertRaisesRegex(ValueError, "Unsupported convergence metric"):
                    report.main()
            self.assertFalse(legacy_output.exists())

    def test_seed_summary_averages_errors_not_images(self):
        sys.path.insert(0, str(ROOT))
        report = importlib.import_module("scripts.analysis.di_reuse")
        common = {"scene": "test", "scenario": "static", "mode": "initial", "frame": 1, "region": "full",
                  "reference_converged": False, "rmse": 1, "nrmse": .5, "rmae": .25, "gpu_ms": 2}
        rows = [{**common, "seed": 1, "relative_luminance_offset": .5},
                {**common, "seed": 2, "relative_luminance_offset": -.5}]
        result = report.summarize(rows)[0]
        self.assertEqual(result["nrmse_mean"], .5)
        self.assertEqual(result["rmae_mean"], .25)
        self.assertEqual(result["rmae_std"], 0)
        self.assertEqual(result["relative_luminance_offset_mean"], 0)
        self.assertEqual(result["nrmse_std"], 0)
        rows[1]["nrmse"] = 1.5
        self.assertAlmostEqual(report.summarize(rows)[0]["nrmse_std"], 2**-.5)
        self.assertIsNone(report.summarize(rows[:1])[0]["nrmse_std"])
        with self.assertRaises(ValueError):
            report.summarize(rows + rows)

    def test_summary_never_merges_methods_with_different_seeds(self):
        report = importlib.import_module("scripts.analysis.di_reuse")
        common = dict(scene="test", scenario="static", mode="combined", frame=1, region="full",
                      reference_converged=True, rmse=1, nrmse=1, relative_luminance_offset=0, gpu_ms=1)
        rows = [{**common, "method": "restir_di", "seed": 1, "rmae": 1},
                {**common, "method": "pdf_similarity", "seed": 2, "rmae": .1}]
        summaries = report.summarize(rows)
        self.assertEqual({r["method"]: r["rmae_mean"] for r in summaries},
                         {"restir_di": 1, "pdf_similarity": .1})

    def test_error_concentration_uses_pixels_and_handles_exact_match(self):
        module = importlib.import_module("scripts.analysis.di_reuse_report")
        target = np.zeros((10, 10, 3))
        image = target.copy()
        image[0, 0] = 100.
        self.assertEqual(module.error_concentration(image, target), 1.)
        self.assertEqual(module.error_concentration(target, target), 0.)
        self.assertAlmostEqual(module.error_concentration(target + 1, target), .01)

    def test_timing_summary_weights_frames_within_each_seed(self):
        module = importlib.import_module("scripts.analysis.di_reuse_report")
        rows = [dict(seed=1, frames=1, gpu_ms=100.), dict(seed=1, frames=9, gpu_ms=0.),
                dict(seed=2, frames=2, gpu_ms=30.)]
        self.assertEqual(module.mean_gpu_time(rows), 20.)


if __name__ == "__main__":
    unittest.main()
