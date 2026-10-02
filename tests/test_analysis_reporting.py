"""Report aggregation, timing weighting and image reuse checks."""
from collections import Counter
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
from experiment import artifacts, reference
from rtxdi_common import sha
from build_fixtures import lighting_build


class AnalysisReportingTests(unittest.TestCase):
    def test_analysis_decodes_each_image_once_for_metrics_and_figures(self):
        from experiment.config import make_config, load_definition
        from experiment.scenes import load_scene
        report = importlib.import_module("scripts.analysis.di_reuse")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            baseline, refs = root / "baseline", root / "references"
            refs.mkdir()
            for mode, value in (("initial", 3.), ("combined", 2.1)):
                directory = baseline / mode
                directory.mkdir(parents=True)
                config = make_config(load_scene("cornell-box"), load_definition(), mode, "static", resolution=[2, 2])
                config["frames"] = [config["frames"][0], config["frames"][-1]]
                artifacts.save_json(directory / "config.json", config)
                artifacts.save_json(directory / "manifest.json", {
                    "status": "completed", "config_sha256": sha(directory / "config.json"),
                    "scene": {"sha256": "fixture-assets"}, "gpu": "fixture-gpu",
                    "build": lighting_build()})
                artifacts.save_json(directory / "resolved.json", {})
                (directory / "timings.csv").write_text("frame,gpu_ms\n1,1\n128,1\n")
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
            with mock.patch.object(sys, "argv", ["di_reuse", "--baseline", str(baseline), "--references", str(refs)]), \
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
            self.assertEqual(list(root.rglob("*.pfm")), [])
            old = json.loads(convergence.read_text())
            old.pop("convergence_metric")
            artifacts.save_json(convergence, old)
            item["convergence_sha256"] = sha(convergence)
            artifacts.save_json(refs / "reference-index.json", {"schema_version": reference.REFERENCE_SCHEMA_VERSION, "convergence_metric": reference.CONVERGENCE_METRIC, "references": {captures[0]["key"]: item}, "build": lighting_build()})
            legacy_output = baseline / "legacy-analysis"
            with mock.patch.object(sys, "argv", ["di_reuse", "--baseline", str(baseline), "--references", str(refs), "--output", str(legacy_output)]):
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
