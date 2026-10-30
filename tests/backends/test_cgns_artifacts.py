"""CGNS diagnostic counts and reports retain their algorithm identity and cost."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/run"))
sys.path.insert(0, str(ROOT))
from experiment import artifacts
from experiment.config import load_definition, make_config
from experiment.scenes import load_scene
from scripts.analysis import di_methods, di_reuse, di_reuse_report


class CgnsDiagnosticTests(unittest.TestCase):
    def stats(self, data, width=2, height=2):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "frame.cgns"
            path.write_bytes(data)
            return artifacts.cgns_stats(path, width, height, 8, 4)

    def test_means_exclude_background_and_count_empty_selections(self):
        # (tried, scored, selected): background, (8,6,4), (4,2,2), (8,0,0).
        values = np.array([0, 8 | (6 << 8) | (4 << 16), 4 | (2 << 8) | (2 << 16), 8], dtype="<u4")
        result = self.stats(values.tobytes())
        self.assertEqual(result["cgns_active_pixel_fraction"], .75)
        self.assertAlmostEqual(result["cgns_tried_mean_active"], 20 / 3)
        self.assertAlmostEqual(result["cgns_scored_mean_active"], 8 / 3)
        self.assertEqual(result["cgns_selected_mean_active"], 2)
        self.assertAlmostEqual(result["cgns_zero_selected_fraction_active"], 1 / 3)
        self.assertEqual(len(result["cgns_diagnostic_sha256"]), 64)

    def test_background_only_is_explicitly_empty(self):
        result = self.stats(bytes(16))
        self.assertEqual(result["cgns_active_pixel_fraction"], 0)
        for key in ("tried_mean", "scored_mean", "selected_mean", "zero_selected_fraction"):
            self.assertIsNone(result[f"cgns_{key}_active"])

    def test_rejects_truncation_extra_data_and_impossible_counts(self):
        for data in (bytes(15), bytes(17), bytes(20)):
            with self.subTest(size=len(data)), self.assertRaisesRegex(RuntimeError, "CGNS"):
                self.stats(data)
        for invalid in (9, 4 | (5 << 8), 4 | (2 << 8) | (3 << 16),
                        8 | (8 << 8) | (5 << 16), 1 << 24):
            with self.subTest(word=invalid), self.assertRaisesRegex(RuntimeError, "CGNS"):
                self.stats(np.array([invalid, 0, 0, 0], dtype="<u4").tobytes())

    def test_finalize_retains_diagnostics_and_saves_verified_counts(self):
        definition = load_definition()
        definition.update(cgns=True, cgns_candidates=8)
        config = make_config(load_scene("cornell-box"), definition, "combined", "static",
                             resolution=[2, 2], diagnostics=True)
        config["frames"] = config["frames"][:1]
        config["frames"][0]["capture"] = True
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            np.ones((2, 2, 4), dtype="<f2").tofile(output / "frame-0001.rgba16f")
            np.zeros((256, 6), dtype="<u4").tofile(output / "frame-0001.reservoir")
            diagnostic = output / "frame-0001.cgns"
            np.full(4, 8 | (6 << 8) | (4 << 16), dtype="<u4").tofile(diagnostic)
            with mock.patch.object(artifacts, "validate_run_outputs"):
                records = artifacts.finalize_outputs(output, config)
            self.assertEqual(records[0]["cgns_selected_mean_active"], 4)
            self.assertTrue(diagnostic.is_file())
            self.assertEqual(json.loads((output / "captures.json").read_text()), records)




class CgnsAnalysisTests(unittest.TestCase):
    def config(self, enabled):
        definition = load_definition()
        definition["cgns"] = enabled
        return make_config(load_scene("cornell-box"), definition, "combined", "static")

    def test_cgns_is_distinct_in_metrics_and_presentation(self):
        self.assertEqual(di_methods.method(self.config(True)), "cgns")
        self.assertEqual(di_methods.method(self.config(False)), "restir_di")
        self.assertEqual(di_reuse_report.variant_label(("cgns", "combined")), "CGNS / Combined")
        rows = [{"scene": "scene", "scenario": "static", "method": name, "mode": "combined",
                 "frame": 1, "region": "full", "seed": 1, "reference_converged": False,
                 "rmse": error, "nrmse": error, "rmae": error, "relative_luminance_offset": 0, "gpu_ms": cost}
                for name, error, cost in (("restir_di", 1, 2), ("cgns", .5, 3))]
        summary = di_reuse.summarize(rows)
        self.assertEqual({row["method"] for row in summary}, {"restir_di", "cgns"})
        self.assertEqual(next(row["gpu_ms_mean"] for row in summary if row["method"] == "cgns"), 3)

    def test_comparison_allows_cgns_toggle_but_rejects_candidate_budget_changes(self):
        base = {"config": self.config(False), "manifest": {"gpu": "gpu", "build": {}},
                "frame": {"frame": 1}, "key": "same-pose"}
        cgns = deepcopy(base)
        cgns["config"] = self.config(True)
        di_reuse.validate_comparison([base, cgns])
        changed = deepcopy(cgns)
        changed["config"]["definition"]["cgns_candidates"] = 8
        with self.assertRaisesRegex(ValueError, "Compared"):
            di_reuse.validate_comparison([base, changed])

    def test_phase_timings_retain_neighbor_selection_cost_and_full_frame_cost(self):
        config = self.config(True)
        config["frames"] = config["frames"][:2]
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "timings.csv").write_text(
                "frame,gpu_ms,initial_ms,spatial_ms,neighbor_selection_ms\n1,5,1,2,.5\n2,7,1,3,1.5\n")
            frames, phases = di_reuse.read_timings(directory, config)
        self.assertEqual(phases[0]["method"], "cgns")
        self.assertEqual(phases[0]["neighbor_selection_ms"], 1)
        self.assertEqual(phases[0]["gpu_ms"], 6)
        self.assertEqual(frames[1]["neighbor_selection_ms"], .5)


if __name__ == "__main__":
    unittest.main()
