"""Bounded-memory quality/covariance analysis of aligned independent runs."""

from dataclasses import dataclass
from collections.abc import Mapping
from numbers import Real
import numpy as np

from .error_metrics import luminance, smape_map
from image_io.images import read_pfm
from .covariance_metrics import relative_covariance_map, radial_relative_covariance_map
from .neighborhoods import disk_row_spans


@dataclass(frozen=True)
class Frame:
    """One measured frame. An image is any token accepted by image_loader."""

    index: int
    image: object
    reset: bool = False
    segment: str = "measurement"


@dataclass(frozen=True)
class SequenceRun:
    """An independent trial; frame order and reset/segment metadata are required."""

    id: str
    frames: list[Frame]


def validate_alignment(runs, lag=3):
    """Reject gaps within segments and return valid (start, end) list positions."""
    if len(runs) < 2:
        raise ValueError("Covariance requires at least two independent runs")
    identifiers = [run.id for run in runs]
    if any(not isinstance(value, str) or not value for value in identifiers) or len(
        set(identifiers)
    ) != len(runs):
        raise ValueError("Run IDs must be nonempty and unique")
    frames = runs[0].frames
    if type(lag) is not int or not 1 <= lag < len(frames):
        raise ValueError("lag must be an integer in 1..number of frames - 1")
    schedules = []
    for run in runs:
        schedule = []
        for frame in run.frames:
            if (
                type(frame.index) is not int
                or frame.index < 0
                or type(frame.reset) is not bool
                or not isinstance(frame.segment, str)
                or not frame.segment
            ):
                raise ValueError("Invalid frame index, reset flag or segment")
            schedule.append((frame.index, frame.reset, frame.segment))
        for a, b in zip(run.frames, run.frames[1:]):
            if b.index <= a.index:
                raise ValueError(
                    "Frame IDs must be strictly increasing; duplicate or reordered frame"
                )
            if a.segment == b.segment and b.index != a.index + 1:
                raise ValueError(
                    "Missing frame in a continuous segment; declare separate segments for gaps"
                )
        schedules.append(schedule)
    if any(schedule != schedules[0] for schedule in schedules[1:]):
        raise ValueError("Runs must have matching frames, reset flags and segments")
    pairs = {}
    for start in range(len(frames) - lag):
        window = frames[start : start + lag + 1]
        if all(
            b.index == a.index + 1 and b.segment == a.segment and not b.reset
            for a, b in zip(window, window[1:])
        ):
            pairs[start] = start + lag
    if not pairs:
        raise ValueError("No valid temporal pairs within continuous history segments")
    return pairs


def _reference(references, frame):
    if isinstance(references, Mapping):
        if frame not in references:
            raise ValueError(f"Missing reference for frame {frame}")
        return references[frame]
    return references


def _masks(masks, frame, shape, regions):
    value = masks(frame) if callable(masks) else masks
    if (
        value is not None
        and isinstance(value, Mapping)
        and any(type(k) is int for k in value)
    ):
        if frame not in value:
            raise ValueError(f"Missing masks for frame {frame}")
        value = value[frame]
    if value is not None and not isinstance(value, Mapping):
        raise ValueError("Masks must map region names to boolean arrays")
    result = {}
    for name in regions:
        if name == "all":
            mask = np.ones(shape, dtype=bool)
        else:
            if value is None or name not in value:
                raise ValueError(f"Missing region {name} at frame {frame}")
            mask = np.asarray(value[name])
        if mask.dtype != np.bool_ or mask.shape != shape:
            raise ValueError(f"Region {name} must be a matching boolean image")
        if not mask.any():
            raise ValueError(f"Empty requested region {name} at frame {frame}")
        result[name] = mask
    return result


def _read_rgb(loader, image):
    rgb = np.asarray(loader(image))
    if rgb.dtype.kind not in "iuf":
        raise ValueError("Sequence images must contain real numeric RGB")
    return rgb


def _load_frame(runs, position, loader, expected_shape, reference=None):
    """Materialize only one frame across runs, retaining scalar luminance."""
    stack = None
    error = None
    for n, run in enumerate(runs):
        rgb = _read_rgb(loader, run.frames[position].image)
        y = luminance(rgb)  # Existing float64 linear Rec.709 validation/conversion.
        if expected_shape is not None and y.shape != expected_shape:
            raise ValueError("Image dimensions differ across frames/runs")
        if stack is None:
            expected_shape = y.shape
            stack = np.empty((len(runs), *y.shape), dtype=np.float64)
            if reference is not None:
                error = np.zeros(y.shape, dtype=np.float64)
        stack[n] = y
        if reference is not None:
            # Reuse the historical SMAPE formula/epsilon exactly, before averaging runs.
            error += smape_map(rgb, reference) / len(runs)
    return stack, error


def analyze_sequence(
    runs,
    *,
    references=None,
    masks=None,
    regions=None,
    lag=3,
    radius=8,
    epsilon=1e-4,
    block_rows=64,
    image_loader=read_pfm,
):
    """Return per-frame and overall metrics; never load an entire video.

    Input RGB must be scene-linear Rec.709, without display transforms. References
    affect only historical SMAPE (percent, epsilon=1e-4). Covariance is dimensionless
    and uses per-frame means across runs with its independently configurable epsilon.

    masks is a static region mapping, frame->region mapping, or callable(frame).
    It is shared by all runs. Only final aggregation is masked: the spatial disk
    remains complete and temporal pairs use the start mask at fixed screen pixels.
    Empty requested regions raise. Overall values are equal-weight means of eligible
    frame-region means; counts also expose pixel-frames for changing mask sizes.
    """
    runs = list(runs)
    pairs = validate_alignment(runs, lag)
    disk_row_spans(radius, max_vertical=0)  # Validate without allocating the disk.
    radius = int(radius)
    if (
        isinstance(epsilon, (bool, np.bool_))
        or not isinstance(epsilon, Real)
        or not np.isfinite(epsilon)
        or epsilon <= 0
    ):
        raise ValueError("epsilon must be positive and finite")
    if type(block_rows) is not int or block_rows < 1:
        raise ValueError("block_rows must be a positive integer")
    regions = tuple(
        regions
        if regions is not None
        else (("all", "hard") if masks is not None else ("all",))
    )
    if (
        not regions
        or any(not isinstance(name, str) or not name for name in regions)
        or "all" not in regions
        or len(set(regions)) != len(regions)
    ):
        raise ValueError("Regions must be unique names and include all")
    shape, rows = None, []
    for t, frame in enumerate(runs[0].frames):
        reference = (
            None
            if references is None
            else _read_rgb(image_loader, _reference(references, frame.index))
        )
        current, error = _load_frame(runs, t, image_loader, shape, reference)
        shape = current.shape[1:]
        selected = _masks(masks, frame.index, shape, regions)
        endpoint = (
            _load_frame(runs, pairs[t], image_loader, shape)[0] if t in pairs else None
        )
        sums = {
            name: {"pixels": int(mask.sum()), "spatial": 0.0, "temporal": 0.0}
            for name, mask in selected.items()
        }
        for first in range(0, shape[0], block_rows):
            last = min(shape[0], first + block_rows)
            lo, hi = max(0, first - radius), min(shape[0], last + radius)
            spatial = radial_relative_covariance_map(
                current[:, lo:hi], radius=radius, epsilon=epsilon
            )
            spatial = spatial[first - lo : last - lo]
            temporal = (
                relative_covariance_map(
                    current[:, first:last], endpoint[:, first:last], epsilon=epsilon
                )
                if endpoint is not None
                else None
            )
            for name, mask in selected.items():
                part = mask[first:last]
                sums[name]["spatial"] += float(
                    np.sum(spatial[part] / sums[name]["pixels"], dtype=np.float64)
                )
                if temporal is not None:
                    sums[name]["temporal"] += float(
                        np.sum(temporal[part] / sums[name]["pixels"], dtype=np.float64)
                    )
        record = {
            "frame": frame.index,
            "segment": frame.segment,
            "history_reset": frame.reset,
            "temporal_end_frame": (
                runs[0].frames[pairs[t]].index if t in pairs else None
            ),
            "regions": {},
        }
        for name, total in sums.items():
            count = total["pixels"]
            values = {
                "pixels": count,
                "smape_percent": (
                    float(np.mean(error[selected[name]], dtype=np.float64))
                    if error is not None
                    else None
                ),
                "spatial_relative_covariance": total["spatial"],
                "temporal_relative_autocovariance": (
                    total["temporal"] if t in pairs else None
                ),
                "temporal_pixel_pairs": count if t in pairs else 0,
            }
            if any(v is not None and not np.isfinite(v) for v in values.values()):
                raise ValueError(
                    "Non-finite sequence metric; input range exceeds float64 arithmetic"
                )
            record["regions"][name] = values
        rows.append(record)
        # Explicit lifetime bound: no frame stacks survive to the next iteration.
        del current, endpoint, reference, error
    summary = {}
    for name in regions:
        records = [row["regions"][name] for row in rows]
        summary[name] = {
            "frames": len(rows),
            "pixel_frames": sum(r["pixels"] for r in records),
            "valid_temporal_frame_pairs": len(pairs),
            "temporal_pixel_pairs": sum(r["temporal_pixel_pairs"] for r in records),
            "run_temporal_pixel_pairs": len(runs)
            * sum(r["temporal_pixel_pairs"] for r in records),
        }
        for metric in (
            "smape_percent",
            "spatial_relative_covariance",
            "temporal_relative_autocovariance",
        ):
            values = [r[metric] for r in records if r[metric] is not None]
            summary[name][metric] = (
                float(np.sum(np.asarray(values) / len(values), dtype=np.float64))
                if values
                else None
            )
            if values and not np.isfinite(summary[name][metric]):
                raise ValueError("Non-finite overall sequence metric")
    return {
        "schema_version": 1,
        "run_ids": [run.id for run in runs],
        "runs": len(runs),
        "measured_frames": len(rows),
        "valid_temporal_frame_pairs": len(pairs),
        "lag": lag,
        "radius": radius,
        "epsilon": float(epsilon),
        "smape_epsilon": 1e-4,
        "input_color_space": "scene-linear Rec.709 RGB",
        "luminance_weights": [0.2126, 0.7152, 0.0722],
        "spatial_disk": "closed integer disk including center; clipped at image edges",
        "aggregation": "runs first; disk per center; selected pixels per frame; equal eligible frame means",
        "covariance_units": "dimensionless signed relative covariance",
        "temporal_pairing": "same screen pixel; start-frame mask; no reset/segment crossing",
        "frames": rows,
        "summary": summary,
    }
