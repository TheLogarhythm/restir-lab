"""Small shared helpers for the official and external-scene launchers."""
import hashlib
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[2]
RENDERER = ROOT / "renderers/rtxdi"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def di_settings(width, height):
    # Presets must precede overrides: the upstream parser applies them in argument order.
    return {"restirDI.preset": "UNBIASED", "device.vk": 0,
            "device.backBufferWidth": width, "device.backBufferHeight": height,
            "rendering.width": width, "rendering.height": height,
            "rendering.rayQuery": 1, "rendering.pixelJitter": 0,
            "lighting.directMode": "RESTIR", "lighting.indirectMode": "NONE",
            "denoiser.mode": "OFF", "postProcessing.aaMode": "OFF", "postProcessing.toneMapping": 1,
            "restirDI.diMode": "TEMPORAL_SPATIAL", "restirDI.checkerboard": 0, "debug.verbose": 1}


def validate_bmp(path, expected_size):
    with path.open("rb") as stream:
        header = stream.read(26)
    if len(header) < 26 or header[:2] != b"BM":
        raise RuntimeError("Missing or truncated BMP capture")
    width, height = struct.unpack_from("<ii", header, 18)
    if (width, abs(height)) != tuple(expected_size):
        raise RuntimeError("Unexpected capture dimensions")
    if path.stat().st_size != struct.unpack_from("<I", header, 2)[0]:
        raise RuntimeError("Incomplete BMP capture")
    return {"width": width, "height": abs(height), "sha256": sha(path)}
