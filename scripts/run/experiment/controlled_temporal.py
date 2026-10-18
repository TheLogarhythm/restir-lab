"""Sequence reference precision in fixed-radiance-unit TRMAE.

Each pair belongs to its later frame. Pixels and pairs are averaged within
each seed before the independent seeds are averaged for each PDF method.
Only adjacent decoded frames are retained outside the bounded image cache.
"""
from collections import defaultdict
from pathlib import Path

import numpy as np

from .error_metrics import smape, trmae_map
from .reference import ImageCache, metrics, rmae


PHASES = (("1-32", 2, 32), ("33-64", 33, 64), ("65-96", 65, 96))
VARIANTS = ("current", "half_a", "half_b", "previous")


def _groups(captures, references, frames=range(1, 97), required_seeds=None):
    """Validate metadata before decoding any sequence images."""
    groups = defaultdict(dict)
    expected = set(frames)
    for capture in captures:
        try:
            seed = capture["config"]["seed"]
            method = capture["config"]["definition"]["pdf_similarity"]
            frame = capture["frame"]["frame"]
            key = capture["key"]
            image = capture["image"]
        except (KeyError, TypeError) as exc:
            raise ValueError("Missing temporal capture metadata") from exc
        if (type(seed) is not int or type(method) is not bool or type(frame) is not int
                or frame not in expected or not isinstance(key, str) or not key):
            raise ValueError("Invalid temporal seed, method, frame or reference key")
        group = groups[seed, method]
        if frame in group:
            raise ValueError(f"Duplicate temporal frame {frame} for seed {seed}, PDF {method}")
        if image is None:
            raise ValueError("Missing temporal capture image")
        group[frame] = capture
        try:
            reference = references[key]
            streams = reference["streams"]
            paths = (reference["image"], reference["previous_image"], *streams)
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Missing temporal reference or checkpoint for {key}") from exc
        if (not isinstance(streams, (list, tuple)) or len(streams) != 2
                or any(not isinstance(path, (str, Path)) or not str(path) for path in paths)):
            raise ValueError(f"Temporal reference {key} requires a current/previous mean and two streams")
    if not groups:
        raise ValueError("No temporal captures")
    seeds = {seed for seed, _ in groups}
    if required_seeds is not None and seeds != set(required_seeds):
        raise ValueError("Static comparison requires exactly seeds 1, 2 and 3")
    if set(groups) != {(seed, method) for seed in seeds for method in (False, True)}:
        raise ValueError("Temporal comparison requires matched PDF off/on seeds")
    aligned = None
    for group in groups.values():
        if set(group) != expected:
            raise ValueError(f"Every seed/method must contain frames {sorted(expected)} exactly")
        keys = tuple(group[frame]["key"] for frame in sorted(expected))
        if aligned is not None and keys != aligned:
            raise ValueError("Temporal reference keys do not align across seeds/methods")
        aligned = keys
    return groups


def _paired_difference(methods):
    """Separate method precision from resolution of the smaller paired delta."""
    current = methods["True"]["current"] - methods["False"]["current"]
    variants = {variant: methods["True"][variant] - methods["False"][variant]
                for variant in VARIANTS[1:]}
    change = max(abs(value - current) for value in variants.values())
    resolved = abs(current) > change
    equal = current == 0. and all(value == 0. for value in variants.values())
    return {"current": current, "variants": variants, "max_reference_change": change,
            "direction_resolved": resolved,
            "state": "equal" if equal else "resolved" if resolved else "inconclusive"}


def _spatial_means(images, masks):
    image = images[0]
    values = {name: {metric: {} for metric in ("smape", "rmae", "nrmse")} for name in masks}
    for name, mask in masks.items():
        for variant, reference in zip(VARIANTS, images[1:]):
            measured = metrics(image[mask], reference[mask])
            values[name]["smape"][variant] = smape(image[mask], reference[mask])
            values[name]["rmae"][variant] = rmae(image[mask], reference[mask])
            values[name]["nrmse"][variant] = measured["nrmse"]
    return values


def assess_static_reference_differences(captures, references, rois=()):
    """Assess paired static frame-128 differences with three matched seeds.

    ``passed`` confirms a complete assessment, not reference precision; the
    reference manager handles static quality. Interpret each metric's paired
    difference using its reference-stream/checkpoint sensitivity receipt.
    Earlier static captures are deliberately excluded from this assessment.
    """
    selected = []
    for capture in captures:
        try:
            frame = capture["frame"]["frame"]
        except (KeyError, TypeError) as exc:
            raise ValueError("Missing static capture frame") from exc
        if frame == 128:
            selected.append(capture)
    groups = _groups(selected, references, frames=(128,), required_seeds=(1, 2, 3))
    cache = ImageCache(max_bytes=64 * 1024**2)
    masks, shape = None, None
    seed_rows = defaultdict(lambda: defaultdict(dict))
    for (seed, method), group in sorted(groups.items()):
        images = _load_frame(group[128], references, cache, shape)
        if masks is None:
            shape = images[0].shape
            masks = _masks(shape, rois)
        for name, values in _spatial_means(images, masks).items():
            for metric, row in values.items():
                seed_rows[name, metric][str(method)][str(seed)] = row
        del images
    regions = {}
    for name in masks:
        evaluated = {}
        for metric in ("smape", "rmae", "nrmse"):
            methods = {}
            for method, per_seed in seed_rows[name, metric].items():
                methods[method] = {variant: float(np.mean([row[variant] for row in per_seed.values()]))
                                   for variant in VARIANTS}
                methods[method]["per_seed"] = dict(per_seed)
            evaluated[metric] = {"methods": methods, "paired_difference": _paired_difference(methods)}
        regions[name] = {"static": {"metrics": evaluated}}
    return {"passed": True, "regions": regions}


def _masks(shape, rois):
    masks = {"full": (slice(None), slice(None))}
    for roi in rois:
        try:
            name = roi["name"]
            x, y, width, height = (roi[field] for field in ("x", "y", "width", "height"))
        except (KeyError, TypeError) as exc:
            raise ValueError("Invalid temporal diagnostic region") from exc
        if (not isinstance(name, str) or not name or name in masks
                or any(type(value) is not int for value in (x, y, width, height))
                or min(x, y) < 0 or min(width, height) <= 0
                or x + width > shape[1] or y + height > shape[0]):
            raise ValueError("Invalid temporal diagnostic region")
        masks[name] = (slice(y, y + height), slice(x, x + width))
    return masks


def _load_frame(capture, references, cache, shape):
    reference = references[capture["key"]]
    paths = (capture["image"], reference["image"], *reference["streams"], reference["previous_image"])
    try:
        images = tuple(cache(path) for path in paths)
    except (OSError, TypeError) as exc:
        raise ValueError(f"Cannot load temporal frame/reference for {capture['key']}") from exc
    for image in images:
        if (image.ndim != 3 or image.shape[-1] != 3 or not image.size
                or (shape is not None and image.shape != shape)):
            raise ValueError("Temporal images must have matching nonempty H x W x 3 shapes")
        if not np.isfinite(image).all():
            raise ValueError("Non-finite temporal image values")
        shape = image.shape
    return images


def _pair_means(current, previous, masks):
    """Evaluate each alternate reference with its own TRMAE normalization."""
    image, reference, a, b, checkpoint = current
    old_image, old_reference, old_a, old_b, old_checkpoint = previous
    values = {name: {} for name in masks}
    for variant, present, old in zip(VARIANTS, current[1:], previous[1:]):
        terms = trmae_map(image, old_image, present, old)
        for name, mask in masks.items():
            values[name][variant] = float(np.mean(terms[mask]))
    delta_reference = reference - old_reference
    denominator = np.sum(np.abs(delta_reference), axis=-1) + .01
    noise = .5 * np.sum(np.abs((a - old_a) - (b - old_b)), axis=-1) / denominator / 3.
    change = np.sum(np.abs(delta_reference - (checkpoint - old_checkpoint)), axis=-1) / denominator / 3.
    for name, mask in masks.items():
        values[name]["reference_gradient_noise"] = float(np.mean(noise[mask]))
        values[name]["checkpoint_gradient_change"] = float(np.mean(change[mask]))
        if not all(np.isfinite(value) for value in values[name].values()):
            raise ValueError("Non-finite temporal reference metric")
    return values


def check_temporal_references(captures, references, rois=(), ratio=.1):
    """Return a JSON-safe precision receipt; reject incomplete/misaligned input.

    ``references[key]`` supplies ``image`` (accepted current mean),
    ``previous_image`` (previous checkpoint mean), and two independent
    half-stream ``streams``. No exposure adjustment, clipping or rescaling is
    applied. Failure requests only keys in changing adjacent reference states
    which contribute nonzero uncertainty to a failing region/phase.
    """
    if type(ratio) not in (int, float) or not np.isfinite(ratio) or not 0 < ratio < 1:
        raise ValueError("Temporal reference ratio must be finite and between zero and one")
    groups = _groups(captures, references)
    cache = ImageCache(max_bytes=64 * 1024**2)
    rois = tuple(rois)
    masks, shape = None, None
    seed_rows = defaultdict(lambda: defaultdict(dict))
    spatial_seed_rows = defaultdict(lambda: defaultdict(dict))
    contributors = defaultdict(set)
    for (seed, method), group in sorted(groups.items()):
        previous = None
        previous_key = None
        # These accumulators contain scalar sums only, never sequence images.
        totals = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
        spatial_totals = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(float))))
        counts = defaultdict(int)
        frame_counts = defaultdict(int)
        for frame in range(1, 97):
            capture = group[frame]
            current = _load_frame(capture, references, cache, shape)
            if masks is None:
                shape = current[0].shape
                masks = _masks(shape, rois)
            phase = PHASES[(frame - 1) // 32][0]
            frame_counts[phase] += 1
            for name, metrics_by_name in _spatial_means(current, masks).items():
                for metric, variants in metrics_by_name.items():
                    for variant, value in variants.items():
                        spatial_totals[name][phase][metric][variant] += value
            if previous is not None:
                values = _pair_means(current, previous, masks)
                counts[phase] += 1
                for name, row in values.items():
                    for metric, value in row.items():
                        totals[name][phase][metric] += value
                    uncertain = (row["reference_gradient_noise"] > 0
                        or row["checkpoint_gradient_change"] > 0
                        or any(row[variant] != row["current"] for variant in VARIANTS[1:]))
                    if previous_key != capture["key"] and uncertain:
                        contributors[name, phase].update((previous_key, capture["key"]))
            previous, previous_key = current, capture["key"]
        for name in masks:
            for phase, first, last in PHASES:
                if counts[phase] != last - first + 1:
                    raise ValueError("Incomplete temporal phase")
                if frame_counts[phase] != 32:
                    raise ValueError("Incomplete spatial phase")
                seed_rows[name, phase][str(method)][str(seed)] = {
                    metric: value / counts[phase] for metric, value in totals[name][phase].items()}
                for metric, variants in spatial_totals[name][phase].items():
                    spatial_seed_rows[name, phase, metric][str(method)][str(seed)] = {
                        variant: value / frame_counts[phase] for variant, value in variants.items()}
        # Release the last adjacent frame before opening another group.
        del current, previous

    regions, refine_keys = {}, set()
    for name in masks:
        regions[name] = {}
        for phase, first, last in PHASES:
            methods = {}
            for method, per_seed in seed_rows[name, phase].items():
                means = {metric: float(np.mean([row[metric] for row in per_seed.values()]))
                         for metric in (*VARIANTS, "reference_gradient_noise", "checkpoint_gradient_change")}
                methods[method] = {**means, "per_seed": dict(per_seed)}
            noise = max(row["reference_gradient_noise"] for row in methods.values())
            change = max(row["checkpoint_gradient_change"] for row in methods.values())
            metric_change = max(abs(row["current"] - row[variant])
                                for row in methods.values() for variant in VARIANTS[1:])
            threshold = ratio * min(row["current"] for row in methods.values())
            passed = max(noise, change, metric_change) <= threshold
            spatial_metrics = {}
            for metric in ("smape", "rmae", "nrmse"):
                spatial_methods = {}
                for method, per_seed in spatial_seed_rows[name, phase, metric].items():
                    means = {variant: float(np.mean([row[variant] for row in per_seed.values()]))
                             for variant in VARIANTS}
                    spatial_methods[method] = {**means, "per_seed": dict(per_seed)}
                spatial_metrics[metric] = {"methods": spatial_methods,
                    "paired_difference": _paired_difference(spatial_methods)}
            regions[name][phase] = {"pair_count": last - first + 1,
                "frame_count": 32, "metrics": spatial_metrics,
                "seed_count": len(next(iter(methods.values()))["per_seed"]), "methods": methods,
                "paired_difference": _paired_difference(methods),
                "reference_gradient_noise": noise, "checkpoint_gradient_change": change,
                "method_metric_change": metric_change, "threshold": threshold, "passed": passed}
            if not passed:
                refine_keys.update(contributors[name, phase])
    return {"passed": all(row["passed"] for phases in regions.values() for row in phases.values()),
            "regions": regions, "refine_keys": sorted(refine_keys)}
