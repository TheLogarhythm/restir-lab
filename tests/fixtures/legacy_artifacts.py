"""Small RTXDI captures shared by existing saved-analysis fixtures."""

from pathlib import Path

import numpy as np

from experiment.geometry_io import save_geometry
from experiment.images import write_pfm
from rtxdi_common import sha


def write_capture(directory, frame, rgb):
    """Write one compressed PFM and return its capture provenance record."""
    image = Path(directory) / f"frame-{frame:04d}.pfm.gz"
    write_pfm(image, rgb)
    return {"frame": frame, "image_sha256": sha(image)}


def write_plane_geometry(stem, width, height, fov):
    """Write unit-depth, forward-facing geometry and return its saved record."""
    stem = Path(stem)
    np.ones((height, width), dtype="<f4").tofile(stem.with_suffix(".depth32f"))
    np.full((height, width), 0x7FFF7FFF, dtype="<u4").tofile(
        stem.with_suffix(".normals32u")
    )
    return save_geometry(stem, width, height, fov)
