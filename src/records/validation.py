"""Strict saved-file validation shared by the format adapters."""

import hashlib
import json
from pathlib import Path, PureWindowsPath
import re

from image_io.images import read_image
from image_io.exr import read_exr
from .provenance import sha256


def artifact_path(directory, name):
    if not isinstance(name, str) or not name or "\0" in name:
        raise ValueError("Invalid artifact path")
    portable = PureWindowsPath(name)
    if (
        Path(name).is_absolute()
        or portable.drive
        or portable.root
        or ".." in portable.parts
    ):
        raise ValueError("Artifact path must stay inside the run directory")
    root = Path(directory).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Artifact path escapes the run directory")
    if not path.is_file():
        raise ValueError("Missing saved artifact: " + name)
    return path


def require_digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Missing or invalid SHA256 digest")
    return value


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def _constant(value):
    raise ValueError("Nonfinite JSON value: " + value)


def read_json(path, expected=None):
    data = Path(path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if expected is not None and digest != require_digest(expected):
        raise ValueError("Saved JSON hash mismatch: " + str(path))
    value = json.loads(
        data.decode("utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_constant
    )
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object: " + str(path))
    return value, digest


def integer(value, name, minimum=0, maximum=2**32 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Invalid " + name)
    return value


def dimensions(config):
    return (
        integer(config["width"], "width", 1, 16384),
        integer(config["height"], "height", 1, 16384),
    )


def capture_rows(rows, expected):
    if not isinstance(rows, list) or not rows:
        raise ValueError("Missing captures")
    found = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid capture record")
        index = integer(row.get("frame"), "capture frame")
        if index in found:
            raise ValueError("Duplicate capture frame")
        found[index] = row
    if set(found) != set(expected):
        raise ValueError("Capture coverage differs from the saved schedule")
    return found


def checked_image(path, expected, width, height, *, float32_exr=False):
    expected = require_digest(expected)
    if sha256(path) != expected:
        raise ValueError("Saved image hash mismatch: " + str(path))
    rgb = read_exr(path, require_float32=True) if float32_exr else read_image(path)
    if rgb.shape != (height, width, 3):
        raise ValueError("Image dimensions differ from the run config")
    return rgb
