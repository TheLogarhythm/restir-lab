"""Shared unclipped linear RGB error metrics; historical definitions are stable."""

import numpy as np

_LUMINANCE = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)


def _images(*images):
    images = tuple(np.asarray(image, dtype=np.float64) for image in images)
    if any(
        image.ndim != 3 or image.shape[-1] != 3 or not image.size for image in images
    ):
        raise ValueError("Images must have nonempty H x W x 3 shapes")
    if any(image.shape != images[0].shape for image in images[1:]):
        raise ValueError("Images must have matching shapes")
    if any(not np.isfinite(image).all() for image in images):
        raise ValueError("Non-finite image values")
    return images


def luminance(image):
    """Return linear luminance using Rec. 709 RGB weights, without clipping."""
    return _images(image)[0] @ _LUMINANCE


def smape_map(image, reference):
    """Return per-pixel luminance SMAPE in percent, without a factor of two."""
    image, reference = _images(image, reference)
    image_y, reference_y = image @ _LUMINANCE, reference @ _LUMINANCE
    return (
        100.0
        * np.abs(image_y - reference_y)
        / (np.abs(image_y) + np.abs(reference_y) + 1e-4)
    )


def smape(image, reference):
    """Return the spatial mean of the per-pixel SMAPE percentages."""
    return float(np.mean(smape_map(image, reference)))


def signed_relative_map(image, reference):
    """Return signed luminance residual percentages; retain all values."""
    image, reference = _images(image, reference)
    image_y, reference_y = image @ _LUMINANCE, reference @ _LUMINANCE
    return 100.0 * (image_y - reference_y) / (np.abs(reference_y) + 1e-4)


def trmae_map(image, previous, reference, previous_reference):
    """Return per-pixel TRMAE (Isik et al. 2021, Eq. 16) for one frame pair.

    Use RGB L1 norms of adjacent-frame radiance differences and divide by
    three after normalization. No warping or division by frame duration.
    """
    image, previous, reference, previous_reference = _images(
        image, previous, reference, previous_reference
    )
    delta_image = image - previous
    delta_reference = reference - previous_reference
    numerator = np.sum(np.abs(delta_image - delta_reference), axis=-1)
    denominator = np.sum(np.abs(delta_reference), axis=-1) + 0.01
    return numerator / denominator / 3.0


def trmae(image, previous, reference, previous_reference):
    """Return the spatial mean TRMAE for one adjacent-frame pair."""
    return float(np.mean(trmae_map(image, previous, reference, previous_reference)))
