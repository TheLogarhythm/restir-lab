"""Signed relative covariance of independent scalar-luminance realizations.

The estimator follows CGNS Appendix A, Eqs. (16)-(17): center each pixel and
frame on its across-run sample mean, normalize by that mean plus epsilon,
and sum residual products with sample divisor N-1. This is neither Pearson
correlation nor an absolute covariance, and uses no reference image. Convert
linear RGB images with ``error_metrics.luminance`` before calling these APIs.
"""
from numbers import Integral, Real

import numpy as np

from .neighborhoods import disk_row_spans


def _samples(samples, dimensions):
    try:
        unconverted = np.asarray(samples)
        if np.iscomplexobj(unconverted):
            raise ValueError("Samples must contain real scalar luminance")
        values = np.asarray(unconverted, dtype=np.float64)
    except (TypeError, OverflowError) as error:
        raise ValueError("Samples must contain finite real scalar luminance") from error
    if values.ndim != dimensions or not values.size or values.shape[0] < 2:
        shape = "N x H x W" if dimensions == 3 else "N x T x H x W"
        raise ValueError(f"Samples must have nonempty {shape} shape with N >= 2")
    if not np.isfinite(values).all():
        raise ValueError("Samples must contain only finite luminance")
    return values


def _epsilon(epsilon):
    if isinstance(epsilon, bool) or not isinstance(epsilon, Real):
        raise ValueError("epsilon must be a finite positive real scalar")
    epsilon = float(epsilon)
    if not np.isfinite(epsilon) or epsilon <= 0:
        raise ValueError("epsilon must be a finite positive real scalar")
    return epsilon


def _relative_residuals(samples, epsilon):
    mean = np.mean(samples, axis=0, dtype=np.float64)
    denominator = mean + epsilon
    if np.any(denominator == 0):
        raise ValueError("Sample mean plus epsilon must be nonzero")
    return (samples - mean) / denominator


def _checked_result(result):
    if not np.isfinite(result).all():
        raise ValueError("Covariance computation produced non-finite values")
    return result


def relative_covariance_map(a, b, *, epsilon=1e-4):
    """Return an H x W signed sample-relative covariance map.

    Inputs are matching N x H x W arrays, with N >= 2 independent runs aligned
    along the first axis. Each input uses its own per-pixel sample mean. Finite
    negative samples are retained; zero denominators and overflow are errors.
    """
    a, b = _samples(a, 3), _samples(b, 3)
    if a.shape != b.shape:
        raise ValueError("Samples must have matching shapes")
    epsilon = _epsilon(epsilon)
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            residual_a = _relative_residuals(a, epsilon)
            residual_b = _relative_residuals(b, epsilon)
            result = np.sum(residual_a * residual_b, axis=0, dtype=np.float64) / (a.shape[0] - 1)
    except FloatingPointError as error:
        raise ValueError("Covariance computation overflowed or became non-finite") from error
    return _checked_result(result)


def _horizontal_sums(residual, half_width):
    """Sum cropped row windows without subtracting large, unrelated prefixes."""
    if half_width == 0:
        return residual
    height, width = residual.shape
    length = 2 * half_width + 1
    padding = half_width + (-(width + 2 * half_width) % length)
    blocks = np.pad(residual, ((0, 0), (half_width, padding))).reshape(height, -1, length)
    prefix = np.cumsum(blocks, axis=2, dtype=np.float64).reshape(height, -1)
    suffix = np.cumsum(blocks[:, :, ::-1], axis=2, dtype=np.float64)[:, :, ::-1].reshape(height, -1)
    # A window is one whole block, or a suffix and prefix of adjacent blocks.
    # Every summed value is inside that window; outside magnitudes cannot
    # destroy small local sums through global-prefix cancellation.
    start = np.arange(width)
    end = start + length - 1
    sums = prefix[:, end].copy()
    split = start % length != 0
    sums[:, split] += suffix[:, start[split]]
    return sums


def radial_relative_covariance_map(samples, *, radius=8, epsilon=1e-4):
    """Average each pixel's relative covariance over a cropped closed disk.

    Input is N x H x W scalar luminance; output is H x W. Offsets satisfy
    dx**2 + dy**2 <= radius**2. The center is included as an explicit local
    convention (the paper does not specify it). Image boundaries are cropped
    and every center divides by its actual valid lattice-neighbor count.

    Linearity lets us average normalized neighbor residuals before forming
    products. Local block prefix/suffix sums require O(radius) image-sized
    operations per run, with no per-offset or N x H x W x neighborhood
    intermediate. Their float64 sums never subtract unrelated row prefixes.
    """
    samples = _samples(samples, 3)
    epsilon = _epsilon(epsilon)
    runs, height, width = samples.shape
    spans = disk_row_spans(radius, max_vertical=height - 1)
    columns = np.arange(width)
    neighborhoods = {}
    counts = np.zeros((height, width), dtype=np.int64)
    for dy, half_width in spans:
        half_width = min(half_width, width - 1)
        left = np.maximum(0, columns - half_width)
        right = np.minimum(width, columns + half_width + 1)
        center_rows = slice(max(0, -dy), min(height, height - dy))
        neighbor_rows = slice(max(0, dy), min(height, height + dy))
        neighborhoods.setdefault(half_width, []).append((center_rows, neighbor_rows))
        counts[center_rows] += right - left
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            residuals = _relative_residuals(samples, epsilon)
            result = np.zeros((height, width), dtype=np.float64)
            for residual in residuals:
                neighbors = np.zeros((height, width), dtype=np.float64)
                for half_width, row_pairs in neighborhoods.items():
                    horizontal = _horizontal_sums(residual, half_width)
                    for center_rows, neighbor_rows in row_pairs:
                        neighbors[center_rows] += horizontal[neighbor_rows]
                result += residual * (neighbors / counts)
            result /= runs - 1
    except FloatingPointError as error:
        raise ValueError("Covariance computation overflowed or became non-finite") from error
    return _checked_result(result)


def temporal_relative_covariance_maps(samples, *, lag=3, epsilon=1e-4):
    """Return signed maps for aligned times t and t+lag, shaped (T-lag,H,W).

    Input is N x T x H x W scalar luminance from independent runs. This pure
    array helper assumes contiguous times within one history segment. Sequence
    callers must check frame IDs, run identity and reset metadata before use.
    Every frame has its own across-run mean; no spatial averaging, reference
    image, motion warping or absolute value is applied.
    """
    samples = _samples(samples, 4)
    epsilon = _epsilon(epsilon)
    if isinstance(lag, bool) or not isinstance(lag, Integral) or lag <= 0 or lag >= samples.shape[1]:
        raise ValueError("lag must be a positive integer smaller than the time dimension")
    lag = int(lag)
    return np.stack([relative_covariance_map(samples[:, time], samples[:, time + lag], epsilon=epsilon)
                     for time in range(samples.shape[1] - lag)], axis=0)
