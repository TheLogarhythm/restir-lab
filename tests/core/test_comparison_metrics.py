"""Single-frame comparison contracts, independent of GPUs and scene assets."""
from pathlib import Path
import copy
import importlib
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts/run")]
from metrics.error_metrics import smape_map

class StaticMetricsTests(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module("metrics.comparison_metrics")

    def test_errors_are_averaged_after_smape_not_before(self):
        ref = np.ones((2, 2, 3))
        images = {1: np.zeros_like(ref), 2: 2 * ref}
        result = self.api.aggregate_smape(images, ref, {"all": np.ones((2, 2), bool)})
        expected = (smape_map(images[1], ref) + smape_map(images[2], ref)) / 2
        np.testing.assert_allclose(result["error"], expected)
        self.assertGreater(result["summary"]["all"], 60)
        self.assertEqual(float(smape_map((images[1]+images[2])/2, ref).max()), 0)
        self.assertEqual(set(result["per_seed"]), {1, 2})

    def test_single_seed_sign_units_zero_and_shared_masks(self):
        ref = np.ones((2, 2, 3))
        a = ref.copy(); a[0, 0] = 3
        b = ref.copy(); b[1, 1] = 3
        masks = {"all": np.ones((2, 2), bool), "hard": np.array([[True, False], [False, False]])}
        ra = self.api.aggregate_smape({7: a}, ref, masks)
        rb = self.api.aggregate_smape({7: b}, ref, masks)
        result = self.api.compare_errors(ra["error"], rb["error"], masks)
        expected = 200 / 4.0001
        self.assertAlmostEqual(result["delta"][0, 0], expected)
        self.assertAlmostEqual(result["delta"][1, 1], -expected)
        self.assertEqual(result["summary"]["all"], 0)
        self.assertAlmostEqual(result["summary"]["hard"], expected)
        zero = self.api.aggregate_smape({7: np.zeros_like(ref)}, np.zeros_like(ref), masks)
        self.assertEqual(zero["summary"]["all"], 0)

    def test_invalid_inputs(self):
        ref = np.ones((2, 2, 3)); mask = np.ones((2, 2), bool)
        for images, masks in (({}, {"all":mask}), ({1:ref}, {"all":mask*0}),
                              ({1:ref}, {"all":mask.astype(int)}),
                              ({1:ref[:1]}, {"all":mask}),
                              ({1:ref*np.nan}, {"all":mask})):
            with self.subTest(images=list(images), masks=masks):
                with self.assertRaises(ValueError):
                    self.api.aggregate_smape(images, ref, masks)

class StaticConfigTests(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module("experiment.comparison_config")
        self.spec = self.api.load_spec(ROOT / "experiments/configs/di-comparison-static.json")

    def test_views_share_assets_and_capture_after_warmup(self):
        self.assertEqual(len(self.spec["views"]), 5)
        self.assertEqual(self.spec["views"]["bistro-interior"]["scene"], "bistro")
        self.assertEqual(self.spec["views"]["bistro-exterior"]["scene"], "bistro")
        configs = self.api.resolve_configs(self.spec)
        self.assertEqual(len(configs), 10)
        for job in configs:
            c = job["config"]
            self.assertEqual(len(c["frames"]), 41)
            self.assertEqual([f["frame"] for f in c["frames"] if f["capture"]], [41])
            self.assertEqual([f["frame"] for f in c["frames"] if f["reset"]], [1])
            self.assertFalse(c["definition"]["pdf_similarity"])

    def test_zero_warmup_and_spatial_are_supported(self):
        spec = copy.deepcopy(self.spec)
        spec.update(acquisition={"protocol":"static","warmup_frames":0,"capture_frames":[1]}, reuse_mode="spatial", seeds=[2, 5], preview_seed=5)
        jobs = self.api.resolve_configs(spec)
        self.assertEqual(len(jobs), 20)
        self.assertEqual(jobs[0]["config"]["frames"][0]["frame"], 1)
        self.assertEqual(len(jobs[0]["config"]["frames"]), 1)

    def test_reject_bad_seeds_modes_and_method_overrides(self):
        for change in ({"seeds":[1,1]}, {"seeds":[]}, {"preview_seed":99},
                       {"acquisition":{"protocol":"static","warmup_frames":-1,"capture_frames":[0]}}, {"reuse_mode":"not-a-mode"}):
            spec = copy.deepcopy(self.spec); spec.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.api.resolve_configs(spec)
        spec = copy.deepcopy(self.spec)
        spec["methods"]["di-cgns"]["settings"]["spatial_radius"] = 99
        with self.assertRaises(ValueError):
            self.api.resolve_configs(spec)

if __name__ == "__main__":
    unittest.main()
