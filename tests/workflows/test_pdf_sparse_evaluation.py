"""Sparse reference diagnostics must remain exact local observations."""
import copy
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/run"))
sys.path.insert(0, str(ROOT))
from experiment.images import write_pfm
from experiment.controlled_temporal import check_temporal_references


# Literal approved selection: fixture expectations do not use the implementation.
DYNAMIC = {"schema_version": 1, "spatial_frames": [32, 48, 96],
           "support_frames": [31, 47, 95], "temporal_pairs": [[31, 32], [47, 48], [95, 96]],
           "reference_frames": [31, 32, 47, 48, 95, 96]}
STATIC = {"schema_version": 1, "spatial_frames": [128], "support_frames": [],
          "temporal_pairs": [], "reference_frames": [128]}
ROI = [{"name": "receiver", "x": 0, "y": 0, "width": 1, "height": 1}]


class SparseEvaluationTests(unittest.TestCase):
    def temporal_fixture(self, root):
        captures, refs = [], {}
        for frame in (31, 32, 47, 48, 95, 96):
            path = root / f"reference-{frame}.pfm.gz"
            write_pfm(path, np.full((2, 2, 3), 64.))
            refs[str(frame)] = {"image": path, "previous_image": path, "streams": [path, path]}
            for seed in (1, 2, 3):
                for method in (False, True):
                    image = root / f"capture-{seed}-{method}-{frame}.pfm.gz"
                    slope = 2 * seed - 1 + int(method)
                    write_pfm(image, np.full((2, 2, 3), 64. + slope * frame / 8.))
                    captures.append({"image": image, "key": str(frame), "frame": {"frame": frame},
                        "config": {"seed": seed, "definition": {"pdf_similarity": method}}})
        return captures, refs

    def output_fixture(self, root, scenario="motion"):
        refs_dir = root / "references"
        refs_dir.mkdir()
        reference_frames = (128,) if scenario == "static" else (31, 32, 47, 48, 95, 96)
        refs = {}
        for frame in reference_frames:
            path = refs_dir / f"frame-{frame:04d}.pfm.gz"
            write_pfm(path, np.ones((2, 2, 3)))
            refs[frame] = path
        runs = []
        for seed in (1, 2, 3):
            run = {"seed": seed}
            for method in ("off", "on"):
                directory = root / f"{method}-{seed}"
                directory.mkdir()
                run[f"{method}_dir"] = directory
                frames = (1, 128) if scenario == "static" else range(1, 97)
                for frame in frames:
                    level = {32: 2., 48: 3., 96: 4., 128: 2.}.get(frame, 1.) if method == "off" else 1.
                    write_pfm(directory / f"frame-{frame:04d}.pfm.gz", np.full((2, 2, 3), level))
                count = 128 if scenario == "static" else 96
                lines = ["frame,gpu_ms,initial_ms,spatial_ms"]
                for frame in range(1, count + 1):
                    gpu = (10 if frame <= 32 else 20 if frame <= 64 else 30) * (2 if method == "on" else 1)
                    lines.append(f"{frame},{gpu},1,3")
                (directory / "timings.csv").write_text("\n".join(lines) + "\n")
            runs.append(run)
        return {"id": "sparse", "scenario": scenario, "references": refs, "runs": runs,
                "expected_resolution": (2, 2), "rois": ROI,
                "evaluation": copy.deepcopy(STATIC if scenario == "static" else DYNAMIC)}

    def test_sparse_precision_uses_only_declared_pairs_and_representative_spatial_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            captures, refs = self.temporal_fixture(Path(folder))
            result = check_temporal_references(captures, refs, rois=ROI, evaluation=DYNAMIC)
            self.assertTrue(result["passed"])
            self.assertEqual(result["evaluation"], DYNAMIC)
            for region in ("full", "receiver"):
                self.assertEqual(set(result["regions"][region]), {"frame-32", "frame-48", "frame-96"})
                for frame, previous in ((32, 31), (48, 47), (96, 95)):
                    row = result["regions"][region][f"frame-{frame}"]
                    self.assertEqual(row["temporal_pair"], [previous, frame])
                    self.assertEqual((row["pair_count"], row["frame_count"], row["seed_count"]), (1, 1, 3))
                    self.assertAlmostEqual(row["methods"]["False"]["current"], 37.5)
                    self.assertAlmostEqual(row["threshold"], 3.75)
                    self.assertAlmostEqual(row["metrics"]["rmae"]["methods"]["False"]["current"], 3 * frame / 512.)
                    self.assertAlmostEqual(row["paired_difference"]["current"], 12.5)
            json.dumps(result, allow_nan=False)

    def test_sparse_precision_requires_all_seeds_and_each_local_support_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            captures, refs = self.temporal_fixture(Path(folder))
            for invalid in ([row for row in captures if row["config"]["seed"] != 3], captures[1:]):
                with self.assertRaises(ValueError):
                    check_temporal_references(invalid, refs, evaluation=DYNAMIC)

    def test_sparse_gradient_refinement_names_only_the_failing_local_pair(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            captures, refs = self.temporal_fixture(root)
            streams = []
            for index, level in enumerate((64.03125, 63.96875)):
                path = root / f"noisy-{index}.pfm.gz"
                write_pfm(path, np.full((2, 2, 3), level))
                streams.append(path)
            refs["47"]["streams"] = streams
            result = check_temporal_references(captures, refs, evaluation=DYNAMIC)
            self.assertFalse(result["passed"])
            self.assertEqual(result["refine_keys"], ["47", "48"])
            self.assertTrue(result["regions"]["full"]["frame-32"]["passed"])
            self.assertFalse(result["regions"]["full"]["frame-48"]["passed"])

    def test_sparse_summary_separates_local_errors_from_full_phase_gpu_costs(self):
        module = importlib.import_module("scripts.analysis.pdf_summary")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            condition = self.output_fixture(root)
            result = module.summarize_suite(root / "summary", [condition], references_accepted=True)
            off = {row["phase"]: row for row in result["summaries"]
                   if row["region"] == "full" and row["method"] == "pdf-off"}
            self.assertEqual(set(off), {"frame-32", "frame-48", "frame-96"})
            for phase, rmae, trmae, cost in (("frame-32", 1., 100., 10.), ("frame-48", 2., 200., 20.), ("frame-96", 3., 300., 30.)):
                self.assertAlmostEqual(off[phase]["rmae_mean"], rmae)
                self.assertAlmostEqual(off[phase]["trmae_mean"], trmae)
                self.assertAlmostEqual(off[phase]["gpu_ms_mean"], cost)
            self.assertEqual({row["frame"] for row in result["frame_metrics"]}, {32, 48, 96})
            self.assertEqual({row["previous_frame"] for row in result["frame_metrics"]}, {31, 47, 95})
            self.assertEqual({row["timing_frame_count"] for row in result["seed_metrics"]}, {32})
            self.assertEqual(result["conditions"][0]["evaluation"], DYNAMIC)
            self.assertIn("local", result["aggregation"])
            text = (root / "summary/summary.md").read_text(encoding="utf-8")
            self.assertIn("local", text.lower())
            self.assertIn("not a video-average", text.lower())

    def test_sparse_exports_only_representative_maps_and_exact_local_pairs(self):
        module = importlib.import_module("scripts.analysis.pdf_artifacts")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            condition = self.output_fixture(root)
            run = condition["runs"][0]
            output = root / "artifacts"
            result = module.export_condition(output, run["off_dir"], run["on_dir"], condition["references"],
                references_accepted=True, evaluation=DYNAMIC, expected_resolution=(2, 2), rois=ROI,
                write_videos=False, temporal_scale=(0, 500))
            self.assertEqual(result["frames"], [32, 48, 96])
            self.assertEqual(result["temporal_pairs"], [[31, 32], [47, 48], [95, 96]])
            self.assertEqual(result["videos"], [])
            self.assertEqual({path.name for path in (output / "maps/pdf-off").iterdir()},
                             {"frame-0032.npz", "frame-0048.npz", "frame-0096.npz"})
            with np.load(output / "maps/pdf-off/frame-0048.npz") as maps:
                np.testing.assert_allclose(maps["trmae"], np.full((2, 2), 200.))
            self.assertTrue((output / "rois/receiver/frame-0048-trmae.png").is_file())
            self.assertEqual(result["temporal_keyframes"]["48"]["pair"], [47, 48])
            self.assertFalse((output / "frames/reference/frame-0047.png").exists())

    def test_sparse_export_rejects_video_request_before_creating_output(self):
        module = importlib.import_module("scripts.analysis.pdf_artifacts")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            condition = self.output_fixture(root)
            run = condition["runs"][0]
            with self.assertRaisesRegex(ValueError, "video|Video"):
                module.export_condition(root / "bad", run["off_dir"], run["on_dir"], condition["references"],
                    references_accepted=True, evaluation=DYNAMIC, expected_resolution=(2, 2), temporal_scale=(0, 500))
            self.assertFalse((root / "bad").exists())

    def test_sparse_static_selects_only_frame_128_from_full_capture_directory(self):
        module = importlib.import_module("scripts.analysis.pdf_artifacts")
        summary = importlib.import_module("scripts.analysis.pdf_summary")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            condition = self.output_fixture(root, "static")
            run = condition["runs"][0]
            result = module.export_condition(root / "artifacts", run["off_dir"], run["on_dir"], condition["references"],
                references_accepted=True, evaluation=STATIC, expected_resolution=(2, 2), write_videos=False)
            self.assertEqual(result["frames"], [128])
            self.assertEqual(result["temporal_pairs"], [])
            result = summary.summarize_suite(root / "summary", [condition], references_accepted=True)
            self.assertEqual({row["frame"] for row in result["frame_metrics"]}, {128})


if __name__ == "__main__":
    unittest.main()
