"""Independent numerical and alignment checks for bounded-memory sequence metrics."""
from pathlib import Path
import importlib
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts/run")]


class SequenceMetricTests(unittest.TestCase):
    def setUp(self):
        try:
            self.api = importlib.import_module("metrics.sequence_metrics")
        except ImportError:
            self.fail("The shared sequence metric entry point is not implemented")

    def runs(self, values, *, frames=None, resets=(), segments=None):
        # values: N,T,H,W scalar luminance, expanded to neutral RGB.
        values = np.asarray(values, dtype=float)
        frames = frames or list(range(1, values.shape[1] + 1))
        segments = segments or ["measurement"] * len(frames)
        return [self.api.SequenceRun(str(n), [
            self.api.Frame(frame, np.repeat(values[n, t, ..., None], 3, axis=-1),
                           reset=frame in resets, segment=segments[t])
            for t, frame in enumerate(frames)]) for n in range(values.shape[0])]

    @staticmethod
    def load(value):
        return value

    def analyze(self, values, **kwargs):
        return self.api.analyze_sequence(self.runs(values), image_loader=self.load, **kwargs)

    def test_run_centering_lag_and_units_match_hand_calculation(self):
        # At each t, samples [1,2,3]*(t+1): sample variance=1*(t+1)^2.
        values = np.arange(1, 4)[:, None, None, None] * np.arange(1, 6)[None, :, None, None]
        result = self.analyze(values, lag=3, radius=0)
        expected = [4 / ((2 + 1e-4) * (8 + 1e-4)),
                    10 / ((4 + 1e-4) * (10 + 1e-4))]
        self.assertEqual(result["valid_temporal_frame_pairs"], 2)
        self.assertAlmostEqual(result["summary"]["all"]["temporal_relative_autocovariance"],
                               np.mean(expected))
        self.assertEqual(result["summary"]["all"]["temporal_pixel_pairs"], 2)
        self.assertEqual(result["summary"]["all"]["run_temporal_pixel_pairs"], 6)
        self.assertIsNone(result["summary"]["all"]["smape_percent"])
        self.assertEqual(result["frames"][0]["temporal_end_frame"], 4)

    def test_smape_uses_reference_but_covariance_does_not(self):
        values = np.array([[[[1., 4.]], [[3., 2.]]], [[[3., 2.]], [[1., 4.]]]])
        a = self.analyze(values, lag=1, radius=0, references=np.ones((1, 2, 3)))
        b = self.analyze(values, lag=1, radius=0, references=np.full((1, 2, 3), 7.))
        self.assertNotEqual(a["summary"]["all"]["smape_percent"], b["summary"]["all"]["smape_percent"])
        self.assertEqual(a["summary"]["all"]["temporal_relative_autocovariance"],
                         b["summary"]["all"]["temporal_relative_autocovariance"])
        self.assertLess(a["summary"]["all"]["temporal_relative_autocovariance"], 0.)
        from metrics.error_metrics import smape
        expected = np.mean([smape(np.repeat(im[..., None], 3, axis=-1), np.ones((1, 2, 3)))
                            for run in values for im in run])
        self.assertAlmostEqual(a["summary"]["all"]["smape_percent"], expected)

    def test_mask_is_final_aggregation_and_temporal_uses_start_mask(self):
        values = np.array([[[[1., 4.]], [[4., 1.]]], [[[3., 2.]], [[2., 3.]]]])
        masks = {1: {"hard": np.array([[True, False]])},
                 2: {"hard": np.array([[False, True]])}}
        result = self.analyze(values, lag=1, radius=1, masks=masks)
        hard = result["frames"][0]["regions"]["hard"]
        expected_temporal = -2 / ((2 + 1e-4) * (3 + 1e-4))
        self.assertAlmostEqual(hard["temporal_relative_autocovariance"], expected_temporal)
        # Disk at left includes self and right, even though right isn't hard.
        expected_spatial = (2 / (2 + 1e-4)**2 - 2 / ((2 + 1e-4)*(3 + 1e-4))) / 2
        self.assertAlmostEqual(hard["spatial_relative_covariance"], expected_spatial)
        self.assertEqual(hard["pixels"], 1)
        self.assertEqual(result["summary"]["all"]["pixel_frames"], 4)

    def test_reset_and_explicit_segments_cut_pairs_even_when_endpoints_match(self):
        values = np.ones((2, 8, 1, 1))
        runs = self.runs(values, frames=[1,2,3,4,20,21,22,23],
                         resets=(3,), segments=["a"]*4 + ["b"]*4)
        result = self.api.analyze_sequence(runs, lag=2, radius=0, image_loader=self.load)
        self.assertEqual(result["valid_temporal_frame_pairs"], 2)  # 20->22,21->23 only
        self.assertIsNone(result["frames"][0]["temporal_end_frame"])
        self.assertEqual(result["frames"][4]["temporal_end_frame"], 22)

    def test_512_frame_measurement_has_509_pairs_without_hardcoded_budget(self):
        result = self.analyze(np.ones((2, 512, 1, 1)), lag=3, radius=0)
        self.assertEqual(result["valid_temporal_frame_pairs"], 509)
        self.assertEqual(result["summary"]["all"]["temporal_pixel_pairs"], 509)

    def test_blocked_spatial_matches_independent_nested_reference(self):
        rng = np.random.default_rng(4)
        values = rng.uniform(.2, 4, (3, 5, 7, 6))
        results = [self.analyze(values, lag=2, radius=2, block_rows=b) for b in (1, 3, 100)]
        centered = (values - values.mean(axis=0)) / (values.mean(axis=0) + 1e-4)
        spatial = []
        for t in range(5):
            centers = []
            for y in range(7):
                for x in range(6):
                    pairs = []
                    for yy in range(7):
                        for xx in range(6):
                            if (y-yy)**2 + (x-xx)**2 <= 4:
                                pairs.append(np.dot(centered[:,t,y,x], centered[:,t,yy,xx]) / 2)
                    centers.append(np.mean(pairs))
            spatial.append(np.mean(centers))
        temporal = np.mean(centered[:,:3] * centered[:,2:], axis=0) * 3/2
        for result in results:
            np.testing.assert_allclose([f["regions"]["all"]["spatial_relative_covariance"]
                                        for f in result["frames"]], spatial, atol=1e-14)
            self.assertAlmostEqual(result["summary"]["all"]["temporal_relative_autocovariance"],
                                   temporal.mean())

    def test_streaming_loader_never_requires_the_whole_sequence(self):
        # Tokens can only be materialized by the callback, never np.asarray(runs).
        runs = [self.api.SequenceRun(str(n), [self.api.Frame(t, (n,t))
                 for t in range(1, 11)]) for n in range(3)]
        calls = []
        def load(token):
            calls.append(token)
            return np.full((2, 3, 3), token[0] + 1.)
        result = self.api.analyze_sequence(runs, lag=3, radius=1, image_loader=load)
        self.assertEqual(result["valid_temporal_frame_pairs"], 7)
        self.assertEqual(set(calls), {(n,t) for n in range(3) for t in range(1,11)})
        self.assertLessEqual(len(calls), 2 * 3 * 10)

    def test_alignment_and_missing_data_errors_are_not_silently_filtered(self):
        values = np.ones((2, 5, 2, 2))
        bad_cases = []
        runs = self.runs(values); bad_cases.append(runs[:1])
        runs = self.runs(values); runs[1] = runs[0]; bad_cases.append(runs)
        runs = self.runs(values); runs[1].frames.pop(1); bad_cases.append(runs)
        runs = self.runs(values); runs[1].frames[1] = runs[1].frames[0]; bad_cases.append(runs)
        # Missing the same frame in every run is still a gap, not a longer lag.
        runs = self.runs(values)
        for run in runs: run.frames.pop(1)
        bad_cases.append(runs)
        runs = self.runs(values); runs[1].frames[2] = self.api.Frame(3, np.ones((2,2,3)), reset=True)
        bad_cases.append(runs)
        for runs in bad_cases:
            with self.subTest(runs=runs), self.assertRaises(ValueError):
                self.api.analyze_sequence(runs, lag=1, image_loader=self.load)

    def test_custom_loader_rejects_complex_rgb_and_reference_without_silent_projection(self):
        values = np.ones((2, 5, 2, 2))
        runs = self.runs(values)
        runs[0].frames[0] = self.api.Frame(1, np.ones((2,2,3), complex) + 100j)
        with self.assertRaises(ValueError):
            self.api.analyze_sequence(runs, lag=1, image_loader=self.load)
        with self.assertRaises(ValueError):
            self.analyze(values, lag=1, references=np.ones((2,2,3), complex) + 100j)

    def test_invalid_lag_region_reference_and_images_fail(self):
        values = np.ones((2, 5, 2, 2))
        for lag in (0, -1, 5, 1.5, True):
            with self.subTest(lag=lag), self.assertRaises(ValueError):
                self.analyze(values, lag=lag)
        for masks in ({"hard": np.zeros((2,2), bool)}, {"hard": np.ones((1,2), bool)},
                      {"hard": np.ones((2,2), int)}, {1: {"hard": np.ones((2,2), bool)}}):
            with self.subTest(masks=masks), self.assertRaises(ValueError):
                self.analyze(values, lag=1, masks=masks)
        with self.assertRaises(ValueError):
            self.analyze(values, lag=1, references={1: np.ones((2,2,3))})
        for image in (np.full((2,2,3), np.nan), np.ones((3,2,3))):
            runs = self.runs(values); runs[0].frames[2] = self.api.Frame(3, image)
            with self.assertRaises(ValueError):
                self.api.analyze_sequence(runs, lag=1, image_loader=self.load)
        with self.assertRaises(ValueError):
            self.api.analyze_sequence(self.runs(values, resets=(2,3,4,5)), lag=1,
                                      image_loader=self.load)

    def test_overall_uses_equal_frame_means_and_reports_counts_for_varying_masks(self):
        values = np.arange(1, 3)[:,None,None,None] * np.ones((2,3,1,2))
        masks = {1: {"hard": np.array([[True,False]])},
                 2: {"hard": np.array([[True,True]])},
                 3: {"hard": np.array([[False,True]])}}
        result = self.analyze(values, lag=1, radius=0, masks=masks)
        self.assertEqual(result["summary"]["hard"]["pixel_frames"], 4)
        self.assertEqual(result["summary"]["hard"]["temporal_pixel_pairs"], 3)
        self.assertEqual(result["summary"]["hard"]["valid_temporal_frame_pairs"], 2)


    def test_overall_aggregation_equal_frame_weight_with_different_metric_values(self):
        # Time-constant pixels have mean 2 and N=2 covariance 2/9,8/9 for
        # epsilon=1. Varying hard masks yield frame means 2/9,5/9,5/9.
        values = np.array([[[[1., 0.]]] * 3, [[[3., 4.]]] * 3])
        masks = {1: {"hard": np.array([[True, False]])},
                 2: {"hard": np.array([[True, True]])},
                 3: {"hard": np.array([[True, True]])}}
        result = self.analyze(values, masks=masks, lag=1, radius=0, epsilon=1.)
        summary = result["summary"]["hard"]
        self.assertAlmostEqual(summary["spatial_relative_covariance"], 4 / 9)
        self.assertAlmostEqual(summary["temporal_relative_autocovariance"], 7 / 18)
        self.assertEqual(summary["pixel_frames"], 5)
        self.assertEqual(summary["temporal_pixel_pairs"], 3)

    def test_summary_handles_finite_mean_when_sum_would_overflow(self):
        # Every frame covariance is about 8e307; their mean is representable
        # even though a naive sum of four values overflows float64.
        amplitude = np.sqrt(4e307)
        values = np.array([-amplitude, amplitude])[:, None, None, None] * np.ones((2, 4, 1, 1))
        result = self.analyze(values, lag=1, radius=0, epsilon=1.)
        summary = result["summary"]["all"]
        for name in ("spatial_relative_covariance", "temporal_relative_autocovariance"):
            self.assertTrue(np.isfinite(summary[name]))
            np.testing.assert_allclose(summary[name], 8e307, rtol=5e-15)

    def test_nonnumeric_epsilon_reports_validation_error(self):
        values = np.ones((2, 4, 1, 1))
        for epsilon in ("bad", "1", object()):
            with self.subTest(epsilon=epsilon), self.assertRaises(ValueError):
                self.analyze(values, epsilon=epsilon)


if __name__ == "__main__":
    unittest.main()
