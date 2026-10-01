"""Bounded image reuse for reference generation and baseline capture lookup."""
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment import artifacts, reference
from rtxdi_common import sha


class CompressedImageTests(unittest.TestCase):
    def test_cache_reuses_decoded_pixels_and_evicts_by_memory(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / f"image-{n}.pfm.gz" for n in (1, 2)]
            for n, path in enumerate(paths, 1):
                artifacts.write_pfm(path, np.full((2, 2, 3), n, dtype=np.float32))
            cache = reference.ImageCache(max_bytes=96)  # One float64 RGB image.
            with mock.patch.object(reference, "read_pfm", wraps=reference.read_pfm) as reader:
                first = cache(paths[0])
                self.assertIs(cache(paths[0]), first)
                self.assertEqual(reader.call_count, 1)
                np.testing.assert_array_equal(cache(paths[1]), np.full((2, 2, 3), 2))
                np.testing.assert_array_equal(cache(paths[0]), np.ones((2, 2, 3)))
                self.assertEqual(reader.call_count, 3)

    def test_suite_discovers_compressed_baseline_images(self):
        from experiment.config import make_config, load_definition
        from experiment.scenes import load_scene
        config = make_config(load_scene("cornell-box"), load_definition(), "initial", "static")
        config["frames"] = config["frames"][:1]
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            artifacts.save_json(directory / "config.json", config)
            artifacts.save_json(directory / "manifest.json", {
                "status": "completed", "config_sha256": sha(directory / "config.json"),
                "scene": {"sha256": "fixture-assets"}})
            image = directory / "frame-0001.pfm.gz"
            artifacts.write_pfm(image, np.ones((2, 2, 3), dtype=np.float32))
            self.assertEqual(reference.suite_captures(directory)[0]["image"], image)

    def test_convergence_reuses_baselines_with_current_segmented_checkpoints(self):
        report = importlib.import_module("experiment.reference_runner")
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            baseline = directory / "baseline.pfm.gz"
            artifacts.write_pfm(baseline, np.full((2, 2, 3), 3, dtype=np.float32))
            for seed, value in ((1001, 1), (2001, 3)):
                for samples in (16, 32, 64):
                    attempt = directory / f"seed-{seed}/checkpoint-{samples}/attempt-0"
                    attempt.mkdir(parents=True)
                    artifacts.save_json(attempt / "manifest.json", {"status": "completed"})
                    artifacts.write_pfm(attempt / f"frame-{samples//8:04d}.pfm.gz",
                                        np.full((2, 2, 3), value, dtype=np.float32))
            captures = [{"image": baseline, "config": {"preview": {"exposure_ev": 0}}}]
            with mock.patch.object(reference, "read_pfm", wraps=reference.read_pfm) as reader:
                result = report.run_pose(directory, captures, [16, 32, 64], 8, [1001, 2001], .1, None)
                self.assertEqual(reader.call_count, 1)
            np.testing.assert_array_equal(reference.read_pfm(directory / "reference.pfm.gz"),
                                          np.full((2, 2, 3), 2))
            self.assertFalse(result["converged"])





if __name__ == "__main__":
    unittest.main()
