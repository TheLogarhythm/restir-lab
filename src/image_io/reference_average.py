"""Average independent linear FLOAT32 EXR seed results without overwriting inputs."""

import os
from pathlib import Path
import tempfile

import numpy as np
import OpenEXR

from .exr import read_exr


def average_seed_exrs(inputs, output):
    """Write the equal-weight mean of exactly eight seed images."""
    return _average_seed_exrs(inputs, output, seed_count=8)


def _average_seed_exrs(inputs, output, *, seed_count):
    """Write the equal-weight RGB mean; reject invalid, aliased, or existing files."""
    if type(seed_count) is not int or seed_count not in (8, 16):
        raise ValueError('Seed count must be eight or sixteen')
    paths = [Path(path).resolve(strict=True) for path in inputs]
    if len(paths) != seed_count:
        raise ValueError(f"Exactly {seed_count} seed images are required")
    for index, path in enumerate(paths):
        if any(os.path.samefile(path, prior) for prior in paths[:index]):
            raise ValueError("Seed image paths must identify distinct files")
    output = Path(output).absolute()
    if output.exists():
        raise FileExistsError(output)

    total = None
    for path in paths:
        image = read_exr(path, require_float32=True)
        if total is None:
            total = np.zeros(image.shape, dtype=np.float64)
        if image.shape != total.shape:
            raise ValueError("Seed image shapes differ")
        total += image.astype(np.float64) / seed_count
    mean = total.astype(np.float32)
    if not np.isfinite(mean).all():
        raise ValueError("Mean cannot be represented as finite FLOAT32")

    # A sibling temporary file permits atomic no-overwrite publication via hardlink.
    descriptor, name = tempfile.mkstemp(prefix='.reference-average-', suffix='.exr', dir=output.parent)
    os.close(descriptor)
    try:
        OpenEXR.File({}, {"RGB": mean}).write(name)
        os.link(name, output)
    finally:
        os.unlink(name)
    return output
