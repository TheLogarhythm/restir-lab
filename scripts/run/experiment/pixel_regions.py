"""Method-independent easy/hard regions from primary-surface geometry.

The traditional predicate follows ReSTIR-CGNS f28d553f3b2552b1be829feffea6d1abb1945e1d,
Source/RenderPasses/CGNS/SpatialResampling.rt.slang lines 123-136:
normal dot >= 0.5 and |d_center - d_neighbor| < 0.1*d_center. Distances
are radial camera-to-surface distances, not view-space Z; normals are shading
normals (GenerateCGNSGBuffer.cs.slang lines 34-39). No material test is used.

Analysis conventions: enumerate the full clipped integer disk, exclude self,
count in-bounds background neighbors as failures, and rank valid centers only.
These conventions are deterministic analysis choices, not the author's random
candidate sampling or CGNS neighbor selections. Radius 30 is the classification
radius and is independent of a renderer's spatial reuse radius.
"""
from numbers import Integral, Real
import numpy as np
from .neighborhoods import disk_offsets


def _real_array(value, name):
    value = np.asarray(value)
    if value.dtype.kind not in "iuf":
        raise ValueError(f"{name} must contain real numeric values")
    return np.asarray(value, dtype=np.float64)


def _mask(value, shape):
    value = np.asarray(value)
    if value.dtype != np.bool_ or value.shape != shape:
        raise ValueError("valid must be a boolean mask matching the image")
    return value


def traditional_acceptance(camera_distance, shading_normals, *, valid=None,
                           classification_radius=30, block_rows=32):
    """Return acceptance rates, counts and valid centers for one geometry frame.

    All arithmetic uses float64. Input values must be real and finite; background
    may have distance/normal zero. Valid surface distances must be positive and
    normal lengths within .001 of one. Normals are used as supplied, without
    changing their direction or normalization. Candidate and accepted counts are int64. Background
    centers and centers with no candidates have zero counts/rates. Processing
    row blocks bounds temporary storage independently of neighborhood area.
    """
    distance = _real_array(camera_distance, "camera_distance")
    normals = _real_array(shading_normals, "shading_normals")
    if distance.ndim != 2 or not distance.size:
        raise ValueError("camera_distance must have a nonempty H x W shape")
    if normals.shape != (*distance.shape, 3):
        raise ValueError("shading_normals must have a matching H x W x 3 shape")
    if not np.isfinite(distance).all() or not np.isfinite(normals).all() or np.any(distance < 0):
        raise ValueError("Geometry must be finite with nonnegative camera distances")
    valid = distance > 0 if valid is None else _mask(valid, distance.shape)
    surface_normals = normals[valid]
    # Bound components before squaring: corrupted but finite huge inputs must
    # fail without overflowing. The tolerance allows float/half rounding.
    if (np.any(distance[valid] <= 0) or np.any(np.abs(surface_normals) > 1.001)
            or np.any(np.abs(np.linalg.norm(surface_normals, axis=-1) - 1.) > .001)):
        raise ValueError("Valid surfaces need positive distances and approximately unit normals")
    # Background normal values have no geometric meaning and never enter dots.
    normals = np.where(valid[..., None], normals, 0.)
    if isinstance(block_rows, (bool, np.bool_)) or not isinstance(block_rows, Integral) or block_rows < 1:
        raise ValueError("block_rows must be a positive integer")
    offsets = disk_offsets(classification_radius, include_center=False)
    height, width = distance.shape
    accepted = np.zeros(distance.shape, dtype=np.int64)
    candidates = np.zeros(distance.shape, dtype=np.int64)
    for dy, dx in offsets:
        y0, y1 = max(0, -dy), min(height, height - dy)
        x0, x1 = max(0, -dx), min(width, width - dx)
        if y0 >= y1 or x0 >= x1:
            continue
        for first in range(y0, y1, int(block_rows)):
            last = min(y1, first + int(block_rows))
            center = (slice(first, last), slice(x0, x1))
            neighbor = (slice(first + dy, last + dy), slice(x0 + dx, x1 + dx))
            center_valid = valid[center]
            candidates[center] += center_valid
            compatible = center_valid & valid[neighbor]
            compatible &= np.abs(distance[center] - distance[neighbor]) < .1 * distance[center]
            # Component sums avoid a neighborhood-sized H x W x K x 3 tensor.
            normal_dot = np.einsum("...i,...i->...", normals[center], normals[neighbor])
            compatible &= normal_dot >= .5
            accepted[center] += compatible
    acceptance = np.zeros(distance.shape, dtype=np.float64)
    np.divide(accepted, candidates, out=acceptance, where=candidates > 0)
    return {"acceptance": acceptance, "accepted": accepted,
            "candidates": candidates, "valid": valid.copy()}


def rank_regions(acceptance, valid, *, hard_percent=10):
    """Rank valid centers; hard is the lowest floor(N_valid*p/100) rates.

    Equal rates resolve by increasing row-major pixel index. Background is in
    neither easy nor hard; those masks partition valid. Empty regions remain
    explicit all-false masks, including p=0, too few valid pixels, or no valid
    surfaces. Callers must handle empty masks explicitly before computing means;
    the sequence evaluator rejects a requested empty region.
    """
    acceptance = _real_array(acceptance, "acceptance")
    if acceptance.ndim != 2 or not acceptance.size:
        raise ValueError("acceptance must have a nonempty H x W shape")
    valid = _mask(valid, acceptance.shape)
    if not np.isfinite(acceptance).all() or np.any((acceptance < 0) | (acceptance > 1)):
        raise ValueError("acceptance rates must be finite and in [0, 1]")
    if (isinstance(hard_percent, (bool, np.bool_)) or not isinstance(hard_percent, Real)
            or not np.isfinite(hard_percent) or not 0 <= hard_percent <= 100):
        raise ValueError("hard_percent must be a finite number in [0, 100]")
    indices = np.flatnonzero(valid)
    count = int(np.floor(len(indices) * float(hard_percent) / 100.))
    ordered = np.argsort(acceptance.ravel()[indices], kind="stable")
    hard = np.zeros(valid.shape, dtype=bool)
    hard.ravel()[indices[ordered[:count]]] = True
    return {"hard": hard, "easy": valid & ~hard, "valid": valid.copy()}
