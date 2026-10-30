"""Integer lattice disks shared by image-neighborhood metrics."""

from math import isqrt
from numbers import Integral


def _nonnegative_integer(value, name):
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return int(value)


def disk_row_spans(radius, *, max_vertical=None):
    """Return ``(dy, half_width)`` rows of the closed integer disk.

    ``max_vertical`` optionally clips the row offsets, without changing their
    horizontal widths. This bounds work when the disk exceeds image height.
    """
    radius = _nonnegative_integer(radius, "radius")
    extent = (
        radius
        if max_vertical is None
        else min(radius, _nonnegative_integer(max_vertical, "max_vertical"))
    )
    return tuple(
        (dy, isqrt(radius * radius - dy * dy)) for dy in range(-extent, extent + 1)
    )


def disk_offsets(radius, *, include_center=True):
    """Return closed-disk ``(dy, dx)`` offsets in row-major order.

    Center inclusion defaults to true as an explicit local convention. Callers
    evaluating neighbor-only predicates can request ``include_center=False``.
    """
    if not isinstance(include_center, bool):
        raise ValueError("include_center must be a boolean")
    return tuple(
        (dy, dx)
        for dy, half_width in disk_row_spans(radius)
        for dx in range(-half_width, half_width + 1)
        if include_center or dy != 0 or dx != 0
    )
