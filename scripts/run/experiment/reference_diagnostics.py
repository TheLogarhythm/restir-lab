"""Diagnostic-only light-class probes; never reference accumulation inputs."""
import math

import numpy as np

from .reference import EPSILON, pair, reference_config


_COUNTS = {"zero": (0, 0, 0), "local": (64, 0, 0),
           "local_environment": (64, 64, 0), "allocation": (64, 8, 4)}


def make_probe_config(base, pose, samples, seed, component):
    """Freeze the target while selecting conventional light-class sample counts.

    The zero-light probe captures two nominal batches to check deterministic
    emission/background/glass. The allocation trial retains all light classes.
    All probes use fresh streams without resume; samples specifies nominal
    local-class count, not a sum over classes.
    """
    if component not in _COUNTS:
        raise ValueError("Unknown diagnostic light-class component")
    if type(samples) is not int or samples < 128 or samples % 64:
        raise ValueError("Probe samples must be multiples of 64 and at least 128")
    checkpoints = [64, 128] if component == "zero" else [samples]
    config = reference_config(base, pose, checkpoints, 64, seed, "POWER_RIS")
    counts = dict(zip(("local", "environment", "infinite"), _COUNTS[component]))
    for name, value in counts.items():
        config["definition"][f"initial_{name}_candidates"] = value
    for name, value in zip(("LocalLight", "Environment", "InfiniteLight"), _COUNTS[component]):
        config["arguments"][f"restirDI.initialSampling.num{name}Samples"] = value
    config["arguments"]["restirDI.neeLocalLightSampling.numLocalLightPowerRISSamples"] = counts["local"]
    config["reference"].update(diagnostic_only=True, component=component, class_counts=counts)
    return config


def _diagnostic(a, b, energy):
    error = np.abs(a - b) * .5
    pixels = np.mean(error, axis=-1)
    total = float(pixels.sum())
    count = max(1, math.ceil(pixels.size * .01))
    top = np.partition(pixels.ravel(), pixels.size - count)[-count:]
    y, x = np.unravel_index(np.argmax(pixels), pixels.shape)
    return {"half_stream_rgb_mae": float(error.mean()),
            "half_stream_rmae": float(error.mean() / (energy + EPSILON)),
            "mean_absolute_rgb": float(np.mean(np.abs((a + b) * .5))),
            "top_one_percent_error_fraction": float(top.sum() / total) if total else 0.,
            "largest_error_pixel_xy": [int(x), int(y)],
            "largest_pixel_rgb_mae": float(pixels[y, x])}


def analyze_prefixes(zero1, zero2, local_byseed, local_environment_byseed, full_byseed, roi=None):
    """Measure prefix and residual disagreement against one full-reference energy.

    Each mapping must contain the same two independent seeds. Residuals subtract
    prefixes within each seed; their errors can cancel, so reported RMAEs are
    diagnostics rather than variance fractions. Pixel coordinates are ROI-local.
    """
    mappings = (local_byseed, local_environment_byseed, full_byseed)
    if any(not isinstance(value, dict) or len(value) != 2 for value in mappings):
        raise ValueError("Each prefix requires two independent seed images")
    seeds = tuple(local_byseed)
    if any(set(value) != set(seeds) for value in mappings):
        raise ValueError("Prefix seed sets must match")
    zero1, zero2 = pair(zero1, zero2)
    arrays = [zero1, zero2]
    for mapping in mappings:
        arrays.extend(pair(zero1, mapping[seed])[1] for seed in seeds)
    for array in arrays:
        if np.any(np.all(array == np.array([0., 0., 1.]), axis=-1)):
            raise ValueError("Diagnostic image contains a blue invalid-radiance sentinel")
    tolerance = 8 * np.finfo(np.float32).eps * np.maximum(np.abs(zero1), np.abs(zero2))
    if np.any(np.abs(zero1 - zero2) > tolerance):
        raise ValueError("Zero-light probe is stochastic; prefix decomposition is invalid")
    if roi is not None:
        if (not isinstance(roi, tuple) or len(roi) != 2
                or any(not isinstance(value, slice) for value in roi)):
            raise ValueError("ROI must contain row and column slices")
        arrays = [array[roi] for array in arrays]
        if not arrays[0].size:
            raise ValueError("ROI must be nonempty")
    zero1, zero2, local_a, local_b, le_a, le_b, full_a, full_b = arrays
    constant = (zero1 + zero2) * .5
    energy = float(np.mean(np.abs((full_a + full_b) * .5)))
    prefixes = {"local": (local_a, local_b), "local_environment": (le_a, le_b),
                "full": (full_a, full_b)}
    components = {"local": _diagnostic(local_a - constant, local_b - constant, energy),
                  "environment": _diagnostic(le_a - local_a, le_b - local_b, energy),
                  "infinite": _diagnostic(full_a - le_a, full_b - le_b, energy)}
    return {"diagnostic_only": True, "pixels": int(zero1.shape[0] * zero1.shape[1]),
            "full_reference_mean_absolute_rgb": energy,
            "constant": {"max_absolute_batch_difference": float(np.max(np.abs(zero1 - zero2))),
                         "mean_absolute_rgb": float(np.mean(np.abs(constant)))},
            "prefixes": {name: _diagnostic(*images, energy) for name, images in prefixes.items()},
            "components": components}
