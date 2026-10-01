"""Numerical contracts for reference convergence and portable image comparisons."""
from pathlib import Path
import importlib
import sys
import tempfile
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))


class ReferenceTests(unittest.TestCase):
    def module(self):
        from experiment import artifacts
        self.assertTrue((ROOT / "scripts/run/experiment/reference.py").exists(), "Reference measurements are not implemented")
        return importlib.import_module("experiment.reference"), artifacts

    def test_pfm_roundtrip_retains_hdr_and_orientation(self):
        module, artifacts = self.module()
        rgb = np.arange(18, dtype=np.float32).reshape(2, 3, 3) - 2
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "image.pfm"
            artifacts.write_pfm(path, rgb)
            np.testing.assert_array_equal(module.read_pfm(path), rgb)
            path.write_bytes(path.read_bytes()[:-4])
            with self.assertRaises(ValueError):
                module.read_pfm(path)

    def test_metrics_have_known_scale_and_brightness_offset(self):
        module, _ = self.module()
        reference = np.full((2, 3, 3), 2.0)
        result = module.metrics(reference * 1.5, reference)
        self.assertAlmostEqual(result["rmse"], 1.0)
        self.assertAlmostEqual(result["nrmse"], 0.5)
        self.assertAlmostEqual(result["rmae"], 0.5)
        self.assertAlmostEqual(result["relative_luminance_offset"], 0.5)
        self.assertEqual(module.metrics(reference, reference)["rmse"], 0)
        with self.assertRaises(ValueError):
            module.metrics(reference[:1], reference)
        with self.assertRaises(ValueError):
            module.metrics(reference * np.nan, reference)

    def test_reference_is_rechecked_for_a_more_accurate_method(self):
        module, _ = self.module()
        checks = [{"samples_per_class_per_stream": n, "regions": {"full": {"stream_disagreement_rmae": .001, "change_rmae": None if n == 16 else .001}}} for n in (16, 32, 64)]
        self.assertTrue(module.reference_ready(checks, {"full": .02}, .1, module.CONVERGENCE_METRIC))
        self.assertFalse(module.reference_ready(checks, {"full": .005}, .1, module.CONVERGENCE_METRIC))
        self.assertFalse(module.reference_ready(checks[:2], {"full": .02}, .1, module.CONVERGENCE_METRIC))

    def test_recheck_uses_full_image_even_when_quadrants_fail(self):
        module, _ = self.module()
        checks = [{"samples_per_class_per_stream": n, "regions": {
            "full": {"stream_disagreement_rmae": .001, "change_rmae": None if n == 16 else .001},
            "quadrant-0-0": {"stream_disagreement_rmae": .1, "change_rmae": None if n == 16 else .1}}}
            for n in (16, 32, 64)]
        for best in ({"full": .02}, {"full": .02, "quadrant-0-0": .001}):
            with self.subTest(best=best):
                self.assertTrue(module.reference_ready(checks, best, .1, module.CONVERGENCE_METRIC))
        checks[-1]["regions"]["full"]["change_rmae"] = .003
        self.assertFalse(module.reference_ready(checks, {"full": .02}, .1, module.CONVERGENCE_METRIC))
        checks[-1]["regions"].pop("full")
        with self.assertRaises(ValueError):
            module.reference_ready(checks, {"full": .02}, .1, module.CONVERGENCE_METRIC)


    def test_rmae_normalizes_after_averaging_and_handles_black_reference(self):
        module, _ = self.module()
        reference = np.array([[[0., 0., 0.], [2., 2., 2.]]])
        image = reference.copy()
        image[0, 0] = 1.
        self.assertAlmostEqual(module.metrics(image, reference)["rmae"], .5)
        black = np.zeros_like(reference)
        self.assertEqual(module.metrics(black, black)["rmae"], 0.)
        self.assertTrue(np.isfinite(module.metrics(image, black)["rmae"]))

    def test_independent_pair_uncertainty_is_for_the_average(self):
        module, _ = self.module()
        # Average is 2; difference is 2; estimated reference MSE = 2^2 / 4.
        a, b = np.ones((2, 3, 3)), np.full((2, 3, 3), 3.0)
        result = module.convergence(a, b)
        self.assertAlmostEqual(result["estimated_reference_rmse"], 1.0)
        self.assertAlmostEqual(result["estimated_reference_nrmse"], 0.5)
        self.assertIsNone(result["change_nrmse"])
        self.assertAlmostEqual(module.convergence(a, b, np.full_like(a, 1.0))["change_nrmse"], 0.5)

    def test_rmae_pair_check_is_linear_and_first_checkpoint_cannot_pass(self):
        module, _ = self.module()
        a = np.ones((20, 20, 3))
        b = a.copy()
        b[0, 0] = 101.
        result = module.convergence(a, b, (a+b)/2)
        self.assertAlmostEqual(result["stream_disagreement_rmae"], .125/1.125)
        self.assertEqual(result["change_rmae"], 0.)
        self.assertGreater(result["estimated_reference_nrmse"], result["stream_disagreement_rmae"])
        self.assertIsNone(module.convergence(a, b)["change_rmae"])
        with self.assertRaises(ValueError):
            module.reference_ready([], {}, .1, {"name": "NRMSE", "version": 1})

    def test_resume_continues_rng_and_accumulation_count(self):
        module, _ = self.module()
        from experiment.config import make_config, load_definition
        from experiment.scenes import load_scene
        base = make_config(load_scene("cornell-box"), load_definition(), "combined", "static")
        whole = module.reference_config(base, base["frames"][0], [16, 32, 64], 8, 1001, "POWER_RIS")
        tail = module.reference_config(base, base["frames"][0], [64], 8, 1001, "POWER_RIS",
                                       previous_samples=32, resume_image=Path("previous.pfm.gz"))
        expected = whole["frames"][4:]
        expected[0]["reset"] = True
        self.assertEqual(tail["frames"], expected)
        self.assertEqual(tail["reference"]["resume_batches"], 4)
        with self.assertRaises(ValueError):
            module.reference_config(base, base["frames"][0], [64], 8, 1001, "POWER_RIS", previous_samples=24)

    def test_pose_key_ignores_reuse_but_detects_camera_lighting_and_assets(self):
        module, _ = self.module()
        from experiment.config import make_config, load_definition
        from experiment.scenes import load_scene
        configs = [make_config(load_scene("cornell-box"), load_definition(), mode, "motion")
                   for mode in ("initial", "combined")]
        a = module.target(configs[0], configs[0]["frames"][0], "assets-a")
        b = module.target(configs[1], configs[1]["frames"][0], "assets-a")
        self.assertEqual(module.target_key(a), module.target_key(b))
        self.assertNotEqual(module.target_key(a), module.target_key(module.target(configs[0], configs[0]["frames"][63], "assets-a")))
        self.assertNotEqual(module.target_key(a), module.target_key(module.target(configs[0], configs[0]["frames"][0], "assets-b")))
        configs[0]["definition"]["analytic_sun"] = False
        self.assertNotEqual(module.target_key(a), module.target_key(module.target(configs[0], configs[0]["frames"][0], "assets-a")))

    def test_reference_config_freezes_pose_and_uses_distinct_streams(self):
        module, _ = self.module()
        from experiment.config import make_config, load_definition
        from experiment.scenes import load_scene
        base = make_config(load_scene("cornell-box"), load_definition(), "combined", "motion")
        a = module.reference_config(base, base["frames"][63], [16, 32, 64], 8, 1001, "POWER_RIS")
        b = module.reference_config(base, base["frames"][63], [16, 32, 64], 8, 2001, "POWER_RIS")
        self.assertEqual(len(a["frames"]), 8)
        self.assertEqual([f["frame"] for f in a["frames"] if f["capture"]], [2, 4, 8])
        self.assertTrue(all(f["position"] == base["frames"][63]["position"] for f in a["frames"]))
        self.assertTrue(set(f["sampling_frame"] for f in a["frames"]).isdisjoint(f["sampling_frame"] for f in b["frames"]))
        self.assertEqual(a["arguments"]["restirDI.diMode"], "NONE")
        with self.assertRaises(ValueError):
            module.reference_config(base, base["frames"][0], [16, 24], 8, 1001, "POWER_RIS")


if __name__ == "__main__":
    unittest.main()
