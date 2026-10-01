"""Linear RGB PFM I/O and the shared display transform."""
from contextlib import nullcontext
import gzip
from pathlib import Path
import numpy as np


def read_pfm(path):
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        if stream.readline().strip() != b"PF":
            raise ValueError("Expected RGB PFM")
        try:
            width, height = map(int, stream.readline().split())
            scale = float(stream.readline())
        except ValueError as exc:
            raise ValueError("Invalid PFM header") from exc
        if width <= 0 or height <= 0 or not np.isfinite(scale) or scale == 0:
            raise ValueError("Invalid PFM dimensions/scale")
        data = stream.read()
    if len(data) != width * height * 12:
        raise ValueError("Truncated or oversized PFM")
    rgb = np.frombuffer(data, dtype="<f4" if scale < 0 else ">f4").reshape(height, width, 3)[::-1]
    rgb = rgb.astype(np.float64) * abs(scale)
    if not np.isfinite(rgb).all():
        raise ValueError("Non-finite PFM pixels")
    return rgb


def write_pfm(path, rgb):
    rgb = np.asarray(rgb, dtype="<f4")
    if rgb.ndim != 3 or rgb.shape[2] != 3 or not np.isfinite(rgb).all():
        raise ValueError("PFM requires finite H x W x 3 RGB")
    path = Path(path)
    with path.open("wb") as raw, (
            gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0)
            if path.suffix == ".gz" else nullcontext(raw)) as stream:
        stream.write(f"PF\n{rgb.shape[1]} {rgb.shape[0]}\n-1.0\n".encode("ascii"))
        stream.write(rgb[::-1].tobytes())


def preview_rgb(rgb, exposure_ev=0):
    linear = np.maximum(np.asarray(rgb, dtype=np.float64), 0)
    linear *= 2.0 ** exposure_ev
    mapped = linear / (1 + linear)
    srgb = np.where(mapped <= .0031308, 12.92 * mapped,
                    1.055 * mapped ** (1 / 2.4) - .055)
    return np.rint(np.clip(srgb, 0, 1) * 255).astype(np.uint8)
