"""Independent numerical contracts for signed CGNS relative covariance."""
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment import covariance_metrics as metric
from experiment.neighborhoods import disk_offsets, disk_row_spans


def direct_radial(samples, radius, epsilon):
    """Slow literal pairwise definition; independent of the row-span kernel."""
    runs, height, width = samples.shape
    means = np.mean(samples, axis=0)
    result = np.zeros((height, width))
    for y in range(height):
        for x in range(width):
            count = 0
            for other_y in range(height):
                for other_x in range(width):
                    if (other_y - y) ** 2 + (other_x - x) ** 2 > radius ** 2:
                        continue
                    count += 1
                    covariance = 0.
                    for run in range(runs):
                        covariance += ((samples[run, y, x] - means[y, x]) /
                                       (means[y, x] + epsilon) *
                                       (samples[run, other_y, other_x] - means[other_y, other_x]) /
                                       (means[other_y, other_x] + epsilon))
                    result[y, x] += covariance / (runs - 1)
            result[y, x] /= count
    return result


class RelativeCovarianceTests(unittest.TestCase):
    def test_three_runs_use_sample_means_signed_products_and_n_minus_one(self):
        a = np.array([0., 2., 4.]).reshape(3, 1, 1)
        positive = np.array([1., 3., 5.]).reshape(3, 1, 1)
        negative = np.array([3., 2., 1.]).reshape(3, 1, 1)
        np.testing.assert_allclose(metric.relative_covariance_map(a, positive, epsilon=.5), [[16 / 35]])
        np.testing.assert_allclose(metric.relative_covariance_map(a, negative, epsilon=.5), [[-.32]])

    def test_default_epsilon_and_independent_mean_at_each_pixel(self):
        a = np.array([[[0., 0.]], [[1., 10.]], [[2., 20.]]])
        expected = [[1 / 1.0001 ** 2, 100 / 10.0001 ** 2]]
        result = metric.relative_covariance_map(a, a)
        np.testing.assert_allclose(result, expected, rtol=1e-14)
        self.assertEqual(result.dtype, np.float64)

    def test_finite_negative_luminance_uses_signed_mean_denominator(self):
        a = np.array([-3., -2., -1.]).reshape(3, 1, 1)
        b = np.array([1., 2., 3.]).reshape(3, 1, 1)
        np.testing.assert_allclose(metric.relative_covariance_map(a, b, epsilon=.5), [[-4 / 15]])

    def test_identical_runs_and_black_have_zero_covariance(self):
        for samples in (np.zeros((3, 2, 4)), np.full((3, 2, 4), 100.)):
            np.testing.assert_array_equal(metric.relative_covariance_map(samples, samples), np.zeros((2, 4)))
            np.testing.assert_array_equal(metric.radial_relative_covariance_map(samples), np.zeros((2, 4)))

    def test_integer_input_is_converted_before_subtraction(self):
        samples = np.array([0, 1, 2], dtype=np.uint8).reshape(3, 1, 1)
        np.testing.assert_allclose(metric.relative_covariance_map(samples, samples, epsilon=1), [[.25]])

    def test_malformed_nonfinite_complex_and_insufficient_samples_are_rejected(self):
        valid = np.ones((3, 2, 4))
        invalid = [np.ones((2, 4)), np.ones((3, 2, 4, 1)), np.ones((1, 2, 4)),
                   np.empty((0, 2, 4)), np.empty((3, 0, 4)), np.empty((3, 2, 0)),
                   valid * np.nan, valid * np.inf, valid * -np.inf, valid.astype(complex)]
        for samples in invalid:
            with self.subTest(shape=samples.shape, dtype=samples.dtype):
                with self.assertRaises(ValueError):
                    metric.relative_covariance_map(samples, valid)
                with self.assertRaises(ValueError):
                    metric.relative_covariance_map(valid, samples)
                with self.assertRaises(ValueError):
                    metric.radial_relative_covariance_map(samples)
        with self.assertRaises(ValueError):
            metric.relative_covariance_map(valid, np.ones((3, 2, 3)))

    def test_epsilon_must_be_a_finite_positive_real_scalar(self):
        samples = np.ones((3, 1, 1))
        for epsilon in (0, -1, float("nan"), float("inf"), True, 1j, [1.]):
            with self.subTest(epsilon=epsilon):
                for function, args in ((metric.relative_covariance_map, (samples, samples)),
                                       (metric.radial_relative_covariance_map, (samples,)),
                                       (metric.temporal_relative_covariance_maps, (samples[:, None].repeat(4, axis=1),))):
                    with self.assertRaises(ValueError):
                        function(*args, epsilon=epsilon)

    def test_zero_denominator_and_floating_point_overflow_are_rejected(self):
        invalid = [np.full((3, 1, 1), -1e-4),
                   np.full((3, 1, 1), np.finfo(np.float64).max),
                   np.array([-1e200, 0., 1e200]).reshape(3, 1, 1)]
        for samples in invalid:
            with self.subTest(samples=samples.ravel()):
                with self.assertRaises(ValueError):
                    metric.relative_covariance_map(samples, samples)
                with self.assertRaises(ValueError):
                    metric.radial_relative_covariance_map(samples)
                with self.assertRaises(ValueError):
                    metric.temporal_relative_covariance_maps(samples[:, None].repeat(4, axis=1))


class RadialCovarianceTests(unittest.TestCase):
    def test_closed_disk_includes_center_and_crops_boundary_with_valid_count(self):
        slopes = np.array([[1., -1., 0.], [2., 0., 1.]])
        samples = 2 + np.array([-1., 0., 1.])[:, None, None] * slopes
        result = metric.radial_relative_covariance_map(samples, radius=1, epsilon=.5)
        np.testing.assert_allclose(result, [[8 / 75, 0., 0.], [.32, 0., 4 / 75]], atol=1e-15)

    def test_radius_zero_is_relative_variance(self):
        samples = np.array([[[0., 1.]], [[1., 3.]], [[2., 5.]]])
        result = metric.radial_relative_covariance_map(samples, radius=0, epsilon=1)
        np.testing.assert_allclose(result, [[.25, .25]])

    def test_radial_average_retains_negative_covariance(self):
        samples = 2 + np.array([-1., 0., 1.])[:, None, None] * np.array([[1., -2.]])
        np.testing.assert_allclose(metric.radial_relative_covariance_map(samples, radius=1, epsilon=.5), [[-.08, .16]])

    def test_row_span_kernel_matches_literal_pairwise_definition(self):
        generator = np.random.default_rng(412)
        for shape in ((3, 1, 1), (4, 2, 7), (5, 7, 2), (3, 5, 6)):
            samples = generator.uniform(-.25, 5., shape)
            for radius in (0, 1, 2, 8):
                with self.subTest(shape=shape, radius=radius):
                    expected = direct_radial(samples, radius, .03)
                    result = metric.radial_relative_covariance_map(samples, radius=radius, epsilon=.03)
                    np.testing.assert_allclose(result, expected, rtol=3e-13, atol=1e-14)

    def test_wide_image_prefix_sums_preserve_small_covariance(self):
        generator = np.random.default_rng(29)
        samples = generator.uniform(1., 2., (3, 1, 1001))
        means = samples.mean(axis=0)
        residuals = (samples - means) / (means + 1e-4)
        expected = np.empty((1, 1001))
        for x in range(1001):
            neighbors = residuals[:, 0, max(0, x - 8):min(1001, x + 9)]
            expected[0, x] = sum(np.dot(residuals[:, 0, x], neighbors[:, j]) / 2
                                 for j in range(neighbors.shape[1])) / neighbors.shape[1]
        np.testing.assert_allclose(metric.radial_relative_covariance_map(samples), expected,
                                   rtol=2e-11, atol=2e-15)

    def test_large_earlier_residual_does_not_erase_later_local_covariance(self):
        # The first pixel has a zero mean and huge fluctuations; its prefix sum
        # must not erase small local sums in later, disjoint neighborhoods.
        amplitudes = np.array([[1e16, 1., 1., 1., 1., 1., 1.]])
        samples = np.array([-1., 0., 1.])[:, None, None] * amplitudes
        for radius in (0, 1, 2):
            with self.subTest(radius=radius):
                expected = direct_radial(samples, radius, 1.)
                actual = metric.radial_relative_covariance_map(samples, radius=radius, epsilon=1.)
                np.testing.assert_allclose(actual, expected, rtol=2e-15, atol=1e-15)

    def test_large_outside_values_do_not_round_nonzero_local_covariance(self):
        # Unlike total cancellation to zero, the old prefix fallback missed
        # nonzero but inaccurate differences (relative error around 1e-5).
        for small in (1.1, 10000.1, 1e8 + .1):
            amplitudes = np.array([[1e16, *([small] * 9)]])
            samples = np.array([-1., 0., 1.])[:, None, None] * amplitudes
            for radius in (0, 1, 2, 8):
                with self.subTest(small=small, radius=radius):
                    actual = metric.radial_relative_covariance_map(samples, radius=radius, epsilon=1.)
                    expected = direct_radial(samples, radius, 1.)
                    np.testing.assert_allclose(actual, expected, rtol=3e-15, atol=1e-15)

    def test_radius_rejects_boolean_noninteger_and_negative_values(self):
        for radius in (-1, True, 1.5, "1", None):
            with self.subTest(radius=radius):
                with self.assertRaises(ValueError):
                    metric.radial_relative_covariance_map(np.ones((3, 1, 1)), radius=radius)


class TemporalCovarianceTests(unittest.TestCase):
    def test_lag_three_uses_separate_mean_for_each_time(self):
        # Means change with time, while per-run fluctuations reverse at t=3.
        means = np.array([2., 4., 6., 8., 10.])
        slopes = np.array([1., 2., 3., -4., 5.])
        samples = (means + np.array([-1., 0., 1.])[:, None] * slopes)[:, :, None, None]
        result = metric.temporal_relative_covariance_maps(samples, epsilon=.5)
        self.assertEqual(result.shape, (2, 1, 1))
        np.testing.assert_allclose(result[:, 0, 0], [-4 / (2.5 * 8.5), 10 / (4.5 * 10.5)])

    def test_temporal_maps_match_direct_pairwise_covariance_for_every_pair(self):
        samples = np.random.default_rng(7).uniform(0., 4., (4, 7, 2, 3))
        for lag in (1, 3, 6):
            result = metric.temporal_relative_covariance_maps(samples, lag=lag)
            for time in range(7 - lag):
                a, b = samples[:, time], samples[:, time + lag]
                expected = ((a - a.mean(axis=0)) * (b - b.mean(axis=0)) /
                            ((a.mean(axis=0) + 1e-4) * (b.mean(axis=0) + 1e-4))).sum(axis=0) / 3
                np.testing.assert_allclose(result[time], expected, rtol=1e-13, atol=1e-15)

    def test_temporal_requires_four_dimensions_and_enough_contiguous_times(self):
        invalid = [np.ones((3, 2, 3)), np.ones((3, 4, 2, 3, 1)), np.ones((1, 4, 2, 3)),
                   np.empty((3, 0, 2, 3)), np.empty((3, 4, 0, 3)), np.empty((3, 4, 2, 0)),
                   np.ones((3, 3, 2, 3)), np.full((3, 4, 2, 3), np.inf)]
        for samples in invalid:
            with self.subTest(shape=samples.shape):
                with self.assertRaises(ValueError):
                    metric.temporal_relative_covariance_maps(samples)
        for lag in (0, -1, True, 1.5, "1", None, 4):
            with self.subTest(lag=lag):
                with self.assertRaises(ValueError):
                    metric.temporal_relative_covariance_maps(np.ones((3, 4, 2, 3)), lag=lag)


class DiskNeighborhoodTests(unittest.TestCase):
    def test_disk_is_closed_includes_center_and_has_deterministic_row_order(self):
        self.assertEqual(disk_offsets(0), ((0, 0),))
        self.assertEqual(disk_offsets(1), ((-1, 0), (0, -1), (0, 0), (0, 1), (1, 0)))
        self.assertEqual(disk_offsets(0, include_center=False), ())
        self.assertEqual(len(disk_offsets(8)), 197)
        self.assertEqual(len(disk_offsets(8, include_center=False)), 196)
        self.assertEqual(disk_offsets(np.int64(1)), disk_offsets(1))

    def test_row_spans_represent_same_disk_and_clip_vertical_extent(self):
        self.assertEqual(disk_row_spans(2), ((-2, 0), (-1, 1), (0, 2), (1, 1), (2, 0)))
        self.assertEqual(disk_row_spans(2, max_vertical=1), ((-1, 1), (0, 2), (1, 1)))
        for radius in (0, 1, 2, 8):
            reconstructed = tuple((dy, dx) for dy, half_width in disk_row_spans(radius)
                                  for dx in range(-half_width, half_width + 1))
            self.assertEqual(reconstructed, disk_offsets(radius))

    def test_invalid_disk_arguments_are_rejected(self):
        for radius in (-1, True, 1.5, "1", None):
            for function in (disk_offsets, disk_row_spans):
                with self.subTest(radius=radius, function=function.__name__):
                    with self.assertRaises(ValueError):
                        function(radius)
        for include_center in (0, 1, None, "false"):
            with self.assertRaises(ValueError):
                disk_offsets(1, include_center=include_center)
        for max_vertical in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                disk_row_spans(2, max_vertical=max_vertical)


if __name__ == "__main__":
    unittest.main()
