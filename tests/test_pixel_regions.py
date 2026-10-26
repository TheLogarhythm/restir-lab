"""Hand-derived checks for shared geometry-only pixel regions."""
from pathlib import Path
import importlib
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))


class PixelRegionTests(unittest.TestCase):
    def module(self):
        return importlib.import_module("experiment.pixel_regions")

    @staticmethod
    def normals(shape):
        result = np.zeros((*shape, 3))
        result[..., 2] = 1.
        return result

    def test_disk_excludes_center_clips_edges_and_keeps_invalid_denominator(self):
        distances = np.ones((3, 3))
        distances[1, 1] = 0.
        result = self.module().traditional_acceptance(
            distances, self.normals((3, 3)), classification_radius=1, block_rows=1)
        np.testing.assert_array_equal(result["candidates"], [[2, 3, 2], [3, 0, 3], [2, 3, 2]])
        np.testing.assert_array_equal(result["accepted"], [[2, 2, 2], [2, 0, 2], [2, 2, 2]])
        np.testing.assert_allclose(result["acceptance"], [[1, 2/3, 1], [2/3, 0, 2/3], [1, 2/3, 1]])
        self.assertEqual(result["acceptance"].dtype, np.float64)

    def test_author_depth_test_is_strict_and_relative_to_center(self):
        # |10-11| == 10% of center 10 fails; |11-10| < 10% of 11 passes.
        result = self.module().traditional_acceptance(
            [[10., 11.]], self.normals((1, 2)), classification_radius=1)
        np.testing.assert_array_equal(result["accepted"], [[0, 1]])
        np.testing.assert_array_equal(result["acceptance"], [[0, 1]])

    def test_author_normal_threshold_includes_equality_and_rejects_below(self):
        normals = np.array([[[0., 0., 1.], [np.sqrt(.75), 0., .5], [0., 0., -1.]]])
        result = self.module().traditional_acceptance([[10., 10., 10.]], normals, classification_radius=1)
        np.testing.assert_array_equal(result["accepted"], [[1, 1, 0]])
        np.testing.assert_allclose(result["acceptance"], [[1, .5, 0]])

    def test_radius_two_is_disk_not_square_and_blocks_are_equivalent(self):
        distance = np.ones((5, 5), dtype=np.float32)
        result = self.module().traditional_acceptance(distance, self.normals((5, 5)), classification_radius=2, block_rows=1)
        # Center: 4 axial radius-one + 4 diagonals + 4 axial radius-two = 12.
        self.assertEqual(result["candidates"][2, 2], 12)
        self.assertEqual(result["candidates"][0, 0], 5)
        large = self.module().traditional_acceptance(distance, self.normals((5, 5)), classification_radius=2, block_rows=99)
        for key in result:
            np.testing.assert_array_equal(result[key], large[key])

    def test_zero_radius_and_single_pixel_have_zero_finite_acceptance(self):
        for radius, shape in ((0, (2, 3)), (30, (1, 1))):
            result = self.module().traditional_acceptance(np.ones(shape), self.normals(shape), classification_radius=radius)
            np.testing.assert_array_equal(result["accepted"], np.zeros(shape))
            np.testing.assert_array_equal(result["candidates"], np.zeros(shape))
            np.testing.assert_array_equal(result["acceptance"], np.zeros(shape))

    def test_rank_excludes_background_uses_floor_and_row_major_ties(self):
        rate = np.array([[0., .4, .1, .1, .8], [.1, .1, .2, .3, .9]])
        valid = np.ones((2, 5), dtype=bool)
        valid[0, 0] = False
        regions = self.module().rank_regions(rate, valid, hard_percent=30)
        expected = np.zeros_like(valid)
        expected[0, 2:4] = True  # floor(9 * .3)=2; earliest two of four .1 ties.
        np.testing.assert_array_equal(regions["hard"], expected)
        np.testing.assert_array_equal(regions["easy"], valid & ~expected)
        np.testing.assert_array_equal(regions["valid"], valid)

    def test_empty_regions_and_percentage_endpoints_remain_explicit_masks(self):
        for valid in (np.zeros((1, 3), dtype=bool), np.ones((1, 3), dtype=bool)):
            for percent in (0, 10, 100):
                result = self.module().rank_regions(np.zeros((1, 3)), valid, hard_percent=percent)
                self.assertEqual(int(result["hard"].sum()), int(valid.sum()) * percent // 100)
                np.testing.assert_array_equal(result["hard"] | result["easy"], valid)
                self.assertFalse(np.any(result["hard"] & result["easy"]))

    def test_geometry_rejects_bad_shapes_nonfinite_and_invalid_parameters(self):
        function = self.module().traditional_acceptance
        distance = np.ones((2, 3))
        normals = self.normals((2, 3))
        for value in (np.ones(3), np.empty((0, 3)), distance * np.nan, distance * np.inf, -distance):
            with self.subTest(distance_shape=value.shape):
                with self.assertRaises(ValueError): function(value, normals)
        for value in (np.ones((2, 3, 2)), np.ones((1, 3, 3)), np.full_like(normals, np.nan), np.full_like(normals, np.inf), np.zeros_like(normals)):
            with self.subTest(normal_shape=value.shape):
                with self.assertRaises(ValueError): function(distance, value)
        for key, values in {"classification_radius": [-1, True, 1.5], "block_rows": [0, -1, True, 1.5], "valid": [np.ones((2, 3)), np.ones((1, 3), dtype=bool)]}.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ValueError): function(distance, normals, **{key: value})
        with self.assertRaises(ValueError): function(np.zeros((2, 3)), normals, valid=np.ones((2, 3), dtype=bool))

    def test_complex_geometry_and_acceptance_are_rejected_before_float_conversion(self):
        distance = np.ones((1, 2))
        normals = self.normals((1, 2))
        for imaginary in (0., 1.):
            for bad_distance, bad_normals in ((distance.astype(complex) + imaginary * 1j, normals),
                                              (distance, normals.astype(complex) + imaginary * 1j)):
                with self.subTest(imaginary=imaginary), self.assertRaises(ValueError):
                    self.module().traditional_acceptance(bad_distance, bad_normals)
            with self.assertRaises(ValueError):
                self.module().rank_regions(distance.astype(complex) + imaginary * 1j,
                                           np.ones((1, 2), dtype=bool))

    def test_valid_normals_require_unit_length_and_huge_inputs_never_overflow(self):
        for scale in (.5, 2., 1e308):
            with self.subTest(scale=scale), np.errstate(over="raise", invalid="raise"):
                with self.assertRaises(ValueError):
                    self.module().traditional_acceptance([[1., 1.]], self.normals((1, 2)) * scale)

    def test_normal_rounding_tolerance_keeps_values_without_renormalizing(self):
        normals = np.array([[[0., 0., .9999], [np.sqrt(.75), 0., .5]]])
        result = self.module().traditional_acceptance([[1., 1.]], normals, classification_radius=1)
        # Both lengths are within .001 of one; raw dot=.49995 still fails.
        np.testing.assert_array_equal(result["accepted"], [[0, 0]])

    def test_invalid_surface_normal_values_cannot_overflow_pairwise_arithmetic(self):
        normals = self.normals((1, 3))
        normals[0, 1:] = 1e308
        with np.errstate(over="raise", invalid="raise"):
            result = self.module().traditional_acceptance([[1., 0., 0.]], normals, classification_radius=1)
        np.testing.assert_array_equal(result["accepted"], [[0, 0, 0]])
        np.testing.assert_array_equal(result["candidates"], [[1, 0, 0]])

    def test_rank_rejects_bad_shape_dtype_nonfinite_and_range(self):
        function = self.module().rank_regions
        valid = np.ones((2, 3), dtype=bool)
        for rate in (np.zeros((1, 3)), np.zeros(3), np.empty((0, 3)), np.full((2, 3), np.nan), np.full((2, 3), np.inf), np.full((2, 3), -.1), np.full((2, 3), 1.1)):
            with self.subTest(shape=rate.shape):
                with self.assertRaises(ValueError): function(rate, valid)
        with self.assertRaises(ValueError): function(np.zeros((2, 3)), valid.astype(int))
        for value in (-1, 101, np.nan, np.inf, True, "10"):
            with self.subTest(percent=value):
                with self.assertRaises(ValueError): function(np.zeros((2, 3)), valid, hard_percent=value)


if __name__ == "__main__":
    unittest.main()
