"""Lossless primary G-buffer capture and deterministic CPU geometry decoding.

RTXDI Depth is R32_FLOAT view-space Z; GBufferNormals is R32_UINT using
Donut's octToNdirUnorm32 encoding (65534 divisor, clamped to one). Both are
captured after rendering, outside GPU timers. Archived raw values allow exact
re-decoding; derived float64 arrays support the independent analysis masks.
"""
from numbers import Integral, Real
from pathlib import Path
import numpy as np
from rtxdi_common import sha

GEOMETRY_FORMAT = "view_depth_r32_float+shading_normal_oct_unorm32_v1"
BACKGROUND_DEPTH = 65504.
_SCHEMA = 1
_KEYS = {"schema_version", "vertical_fov_degrees", "view_depth", "packed_normals"}


def _dimensions(width, height, vertical_fov_degrees):
    for value in (width, height):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < 1:
            raise ValueError("Geometry dimensions must be positive integers")
    if (isinstance(vertical_fov_degrees, (bool, np.bool_))
            or not isinstance(vertical_fov_degrees, Real)
            or not np.isfinite(vertical_fov_degrees) or not 0 < vertical_fov_degrees < 180):
        raise ValueError("Geometry vertical FOV must be finite and in (0, 180)")


def decode_normals(packed_normals):
    """Decode Donut uint32 octahedral shading normals to normalized float64."""
    words = np.asarray(packed_normals)
    if words.ndim != 2 or not words.size or words.dtype.kind != "u" or words.dtype.itemsize != 4:
        raise ValueError("Packed normals must be nonempty H x W uint32")
    x = np.minimum((words & 0xffff).astype(np.float64) / 65534., 1.) * 2. - 1.
    y = np.minimum((words >> 16).astype(np.float64) / 65534., 1.) * 2. - 1.
    z = 1. - np.abs(x) - np.abs(y)
    fold = np.maximum(0., -z)
    x += np.where(x >= 0., -fold, fold)
    y += np.where(y >= 0., -fold, fold)
    normals = np.stack((x, y, z), axis=-1)
    normals /= np.linalg.norm(normals, axis=-1, keepdims=True)
    return normals


def _decode(view_depth, packed_normals, vertical_fov_degrees):
    if (view_depth.ndim != 2 or not view_depth.size or view_depth.dtype != np.dtype("<f4")
            or packed_normals.shape != view_depth.shape or packed_normals.dtype != np.dtype("<u4")):
        raise RuntimeError("Invalid geometry raw array shapes or types")
    height, width = view_depth.shape
    _dimensions(width, height, vertical_fov_degrees)
    if not np.isfinite(view_depth).all() or np.any(view_depth <= 0):
        raise RuntimeError("Geometry depth must be finite and positive (background uses 65504)")
    valid = view_depth != BACKGROUND_DEPTH
    # Matches GBufferHelpers.hlsli ViewDepthToWorldPos for this harness's
    # perspective camera, square pixels and disabled projection jitter.
    tangent = np.tan(np.deg2rad(float(vertical_fov_degrees)) / 2.)
    x = ((np.arange(width, dtype=np.float64) + .5) * 2. / width - 1.) * (width / height) * tangent
    y = (1. - (np.arange(height, dtype=np.float64) + .5) * 2. / height) * tangent
    distance = view_depth.astype(np.float64) * np.sqrt(1. + y[:, None] ** 2 + x[None, :] ** 2)
    distance[~valid] = 0.
    normals = decode_normals(packed_normals)
    normals[~valid] = 0.
    if not np.isfinite(distance).all():
        raise RuntimeError("Non-finite decoded geometry")
    return {"camera_distance": distance, "shading_normals": normals, "valid": valid}


def load_raw_geometry(stem, width, height, vertical_fov_degrees):
    """Validate exact byte lengths and decode captured row-major raw textures."""
    _dimensions(width, height, vertical_fov_degrees)
    stem = Path(stem)
    arrays = []
    for suffix, dtype in ((".depth32f", "<f4"), (".normals32u", "<u4")):
        path = stem.with_suffix(suffix)
        if not path.is_file() or path.stat().st_size != width * height * 4:
            raise RuntimeError(f"Missing or incorrectly sized geometry capture: {path.name}")
        arrays.append(np.fromfile(path, dtype=dtype).reshape(height, width))
    return {**_decode(*arrays, vertical_fov_degrees), "view_depth": arrays[0], "packed_normals": arrays[1]}


def save_geometry(stem, width, height, vertical_fov_degrees):
    """Archive raw geometry losslessly; raw deletion belongs to finalization."""
    stem = Path(stem)
    arrays = load_raw_geometry(stem, width, height, vertical_fov_degrees)
    path = stem.with_suffix(".geometry.npz")
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, schema_version=np.array(_SCHEMA, dtype=np.int64),
                            vertical_fov_degrees=np.array(vertical_fov_degrees, dtype=np.float64),
                            view_depth=arrays["view_depth"], packed_normals=arrays["packed_normals"])
    temporary.replace(path)
    read_geometry(path)  # Check the saved lossless archive before its raw inputs may be deleted.
    return {"geometry": path.name, "geometry_sha256": sha(path),
            "geometry_valid_fraction": float(arrays["valid"].mean())}


def read_geometry(path):
    """Read validated geometry suitable for traditional_acceptance(**result).

    Reject unsupported schema/types/shapes and non-finite raw values. Derived
    arrays are recomputed from raw values; no redundant float64 arrays are
    stored. The run's captures.json records this NPZ's SHA-256.
    """
    try:
        with np.load(path, allow_pickle=False) as archive:
            if set(archive.files) != _KEYS:
                raise RuntimeError("Invalid geometry archive fields")
            arrays = dict(archive)
        schema = arrays.pop("schema_version")
        fov = arrays.pop("vertical_fov_degrees")
        if schema.shape != () or schema.dtype.kind not in "iu" or int(schema) != _SCHEMA:
            raise RuntimeError("Unsupported geometry archive schema")
        if fov.shape != () or fov.dtype != np.float64:
            raise RuntimeError("Invalid geometry archive FOV")
        return _decode(arrays["view_depth"], arrays["packed_normals"], float(fov))
    except (ValueError, KeyError, OSError, EOFError) as exc:
        raise RuntimeError(f"Cannot read geometry archive: {path}") from exc


def validate_geometry_outputs(output, config, resolved):
    """Require runtime acknowledgement and every requested raw geometry frame."""
    requested = config.get("geometry_export", config["definition"].get("geometry_export", False))
    actual = resolved.get("geometry_export", False)
    if type(requested) is not bool or type(actual) is not bool or actual != requested:
        raise RuntimeError("Resolved geometry export differs from requested mode")
    if not requested:
        return
    if resolved.get("geometry_format") != GEOMETRY_FORMAT:
        raise RuntimeError("Missing or incompatible geometry export format")
    for frame in config["frames"]:
        if frame["capture"]:
            load_raw_geometry(Path(output) / f"frame-{frame['frame']:04d}", config["width"], config["height"],
                              config["scene"]["camera"]["vertical_fov"])
