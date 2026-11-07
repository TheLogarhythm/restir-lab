"""Comparison quality maps: average per-seed errors, never averaged RGB."""

import numpy as np
from .error_metrics import smape_map, luminance


def validate_masks(masks, shape):
    if not isinstance(masks, dict) or "all" not in masks:
        raise ValueError("Masks must include all")
    result = {}
    for name, value in masks.items():
        mask = np.asarray(value)
        if mask.dtype != bool or mask.shape != tuple(shape) or not mask.any():
            raise ValueError(f"Invalid or empty mask: {name}")
        result[name] = mask
    if not result["all"].all():
        raise ValueError("all must include every pixel, including background")
    return result


def aggregate_smape(images, reference, masks, *, load_image=np.asarray):
    """Accept seed->image/path mappings; load one image at a time, accumulate float64."""
    shape = luminance(reference).shape
    masks = validate_masks(masks, shape)
    if not images or any(
        type(seed) is not int or not 0 <= seed <= 4095 for seed in images
    ):
        raise ValueError("Require one or more independent integer seeds in 0..4095")
    total = np.zeros(shape, dtype=np.float64)
    per_seed = {}
    for seed, source in images.items():
        error = smape_map(load_image(source), reference)
        total += error
        per_seed[seed] = {
            name: float(error[mask].mean()) for name, mask in masks.items()
        }
    total /= len(per_seed)
    return {
        "error": total,
        "per_seed": per_seed,
        "summary": {name: float(total[mask].mean()) for name, mask in masks.items()},
    }


def compare_errors(baseline, comparison, masks):
    """Signed improvement in SMAPE percentage points; positive means improvement."""
    a, b = np.asarray(baseline, dtype=np.float64), np.asarray(
        comparison, dtype=np.float64
    )
    if (
        a.ndim != 2
        or a.shape != b.shape
        or not np.isfinite(a).all()
        or not np.isfinite(b).all()
    ):
        raise ValueError("Error maps must be matching finite H x W arrays")
    masks = validate_masks(masks, a.shape)
    delta = a - b
    return {
        "delta": delta,
        "summary": {name: float(delta[mask].mean()) for name, mask in masks.items()},
    }
