"""Numeric contracts for the PDF comparison's linear HDR error metrics."""
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts/run")]
from metrics import error_metrics as metric


class PdfErrorMetricTests(unittest.TestCase):
    def test_luminance_uses_linear_rgb_without_clipping(self):
        image = np.array([[[1., 0., 0.], [0., 1., 0.], [0., 0., 1.],
                           [2., 2., 2.], [-1., -1., -1.]]], dtype=np.float32)
        result = metric.luminance(image)
        np.testing.assert_allclose(result, [[.2126, .7152, .0722, 2., -1.]], atol=1e-15)
        self.assertEqual(result.dtype, np.float64)

    def test_smape_exact_black_and_near_black_are_finite(self):
        black = np.zeros((1, 2, 3))
        image = np.array([[[0., 0., 0.], [1e-4, 1e-4, 1e-4]]])
        np.testing.assert_allclose(metric.smape_map(image, black), [[0., 50.]])
        self.assertAlmostEqual(metric.smape(image, black), 25.)
        self.assertEqual(metric.smape(black, black), 0.)

    def test_smape_has_percent_scale_without_a_factor_of_two(self):
        image = np.full((1, 1, 3), 3.)
        reference = np.full_like(image, 1.)
        self.assertAlmostEqual(metric.smape(image, reference), 49.99875003124922)
        self.assertAlmostEqual(metric.smape(reference, image), 49.99875003124922)

    def test_smape_normalizes_each_pixel_before_averaging(self):
        image = np.array([[[1., 1., 1.], [2., 2., 2.]]])
        reference = np.array([[[0., 0., 0.], [2., 2., 2.]]])
        np.testing.assert_allclose(metric.smape_map(image, reference), [[99.9900009999, 0.]])
        self.assertAlmostEqual(metric.smape(image, reference), 49.99500049995)

    def test_smape_uses_absolute_luminance_for_negative_radiance(self):
        image = np.full((1, 1, 3), -1.)
        reference = np.full_like(image, 1.)
        self.assertAlmostEqual(metric.smape(image, reference), 99.9950002499875)

    def test_signed_relative_residual_keeps_sign_and_unclipped_values(self):
        image = np.array([[[0., 0., 0.], [3., 3., 3.], [1e-4, 1e-4, 1e-4]]])
        reference = np.array([[[1., 1., 1.], [1., 1., 1.], [0., 0., 0.]]])
        np.testing.assert_allclose(metric.signed_relative_map(image, reference),
                                   [[-99.9900009999, 199.9800019998, 100.]])

    def test_signed_relative_residual_uses_absolute_reference_luminance(self):
        image = np.zeros((1, 1, 3))
        reference = np.full_like(image, -1.)
        self.assertAlmostEqual(metric.signed_relative_map(image, reference)[0, 0],
                               99.9900009999)
        np.testing.assert_array_equal(metric.signed_relative_map(image, image), [[0.]])

    def test_trmae_matching_reference_motion_has_zero_temporal_error(self):
        previous = np.array([[[1., 2., 3.], [4., 5., 6.]]])
        image = np.array([[[5., 0., 8.], [2., 9., 1.]]])
        np.testing.assert_array_equal(metric.trmae_map(image, previous, image, previous), [[0., 0.]])
        self.assertEqual(metric.trmae(image, previous, image, previous), 0.)

    def test_trmae_does_not_penalize_constant_bias(self):
        previous_reference = np.array([[[1., 2., 3.]]])
        reference = np.array([[[4., 0., 5.]]])
        bias = np.array([[[10., -4., 2.]]])
        self.assertEqual(metric.trmae(reference + bias, previous_reference + bias,
                                      reference, previous_reference), 0.)

    def test_trmae_uses_rgb_l1_norms_and_one_third_scale(self):
        previous = np.zeros((1, 1, 3))
        image = np.array([[[3., 1., 0.]]])
        reference = np.array([[[1., -2., 0.]]])
        # Error delta L1 = |2| + |3|; reference delta L1 = |1| + |-2|.
        self.assertAlmostEqual(metric.trmae(image, previous, reference, previous),
                               .5537098560354374)

    def test_trmae_normalizes_each_pixel_before_averaging(self):
        previous = np.zeros((1, 2, 3))
        image = np.array([[[.01, .01, .01], [2., 0., 0.]]])
        reference = np.array([[[0., 0., 0.], [1., 0., 0.]]])
        np.testing.assert_allclose(metric.trmae_map(image, previous, reference, previous),
                                   [[1., .33003300330033003]])
        self.assertAlmostEqual(metric.trmae(image, previous, reference, previous),
                               .665016501650165)

    def test_trmae_static_reference_keeps_epsilon_and_unclipped_error(self):
        black = np.zeros((1, 1, 3))
        self.assertEqual(metric.trmae(black, black, black, black), 0.)
        self.assertAlmostEqual(metric.trmae(np.ones_like(black), black, black, black), 100.)

    def test_trmae_computes_differences_in_float64(self):
        previous = np.zeros((1, 1, 3), dtype=np.uint8)
        image = np.full((1, 1, 3), 1, dtype=np.uint8)
        reference = np.zeros_like(previous)
        previous_reference = np.full_like(previous, 1)
        result = metric.trmae_map(image, previous, reference, previous_reference)
        self.assertEqual(result.dtype, np.float64)
        self.assertAlmostEqual(result[0, 0], .6644518272425249)

    def test_all_functions_reject_empty_malformed_and_nonfinite_images(self):
        valid = np.ones((2, 2, 3))
        invalid = [np.empty((0, 2, 3)), np.empty((2, 0, 3)), np.ones((2, 2)),
                   np.ones((2, 2, 4)), np.ones((2, 2, 1)),
                   valid * np.nan, valid * np.inf, valid * -np.inf]
        functions = [(metric.luminance, (valid,)), (metric.smape_map, (valid, valid)),
                     (metric.smape, (valid, valid)), (metric.signed_relative_map, (valid, valid)),
                     (metric.trmae_map, (valid,) * 4), (metric.trmae, (valid,) * 4)]
        for function, args in functions:
            for index in range(len(args)):
                for value in invalid:
                    with self.subTest(function=function.__name__, argument=index, shape=value.shape):
                        altered = list(args)
                        altered[index] = value
                        with self.assertRaises(ValueError):
                            function(*altered)

    def test_comparison_functions_reject_mismatched_image_shapes(self):
        valid = np.ones((2, 2, 3))
        mismatched = np.ones((1, 2, 3))
        functions = [(metric.smape_map, (valid, valid)), (metric.smape, (valid, valid)),
                     (metric.signed_relative_map, (valid, valid)),
                     (metric.trmae_map, (valid,) * 4), (metric.trmae, (valid,) * 4)]
        for function, args in functions:
            for index in range(len(args)):
                with self.subTest(function=function.__name__, argument=index):
                    altered = list(args)
                    altered[index] = mismatched
                    with self.assertRaises(ValueError):
                        function(*altered)


if __name__ == "__main__":
    unittest.main()
