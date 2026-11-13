"""Read a reference-set manifest independently of historical render runs."""

import hashlib
import json
import re
from pathlib import Path

from .scene_inputs import relative_name


def load_catalog(manifest, workspace, *, require_images=False):
    root = Path(workspace).resolve(strict=True)
    data = json.loads(Path(manifest).read_text(encoding="utf-8-sig"))
    if (
        data.get("schema_version") not in (1, 2)
        or data.get("path_base") != "repository_root"
    ):
        raise ValueError("Unsupported reference catalog")
    if (
        not isinstance(data.get("name"), str)
        or not data["name"]
        or data.get("resolution") != [1920, 1080]
        or data.get("samples_per_pixel") != 16384
        or not isinstance(data.get("views"), list)
    ):
        raise ValueError("Invalid reference catalog settings")
    result = {}
    for item in data["views"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid reference view")
        scene, view, name, digest = (
            item.get(k) for k in ("scene_id", "view_id", "path", "sha256")
        )
        if (
            not isinstance(scene, str)
            or not scene
            or not isinstance(view, str)
            or not view
            or not isinstance(name, str)
            or not name
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ValueError("Invalid reference view fields")
        relative_name(name, description="Reference")
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Reference path escapes workspace")
        key = (scene, view)
        if key in result:
            raise ValueError("Duplicate reference view")
        if require_images:
            h = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(block)
            if h.hexdigest() != digest:
                raise ValueError("Reference image hash mismatch")
        if data["schema_version"] == 2:
            binding = item.get("binding")
            if (
                not isinstance(binding, dict)
                or binding.get("schema_version") != 1
                or set(binding)
                != {
                    "schema_version",
                    "camera_sha256",
                    "scene_sha256",
                    "transport_sha256",
                }
                or any(
                    not isinstance(binding.get(k), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", binding[k])
                    for k in ("camera_sha256", "scene_sha256", "transport_sha256")
                )
            ):
                raise ValueError("Invalid reference integrand binding")
        result[key] = dict(item)
    if not result:
        raise ValueError("Reference catalog is empty")
    return result


TRANSPORT_FIELDS = (
    "maxSurfaceBounces",
    "maxDiffuseBounces",
    "maxSpecularBounces",
    "maxTransmissionBounces",
    "useRussianRoulette",
    "useRTXDI",
)


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf8")
    ).hexdigest()


def binding_for_view(config, entry, experiment):
    """Bind a fixed image to rendered camera, scene/material/runtime inputs and transport.

    Sampling/reuse parameters do not change the transport target and are omitted.
    Reference generation uses a different sampler from the compared methods.
    """
    from .reference_runner import camera_target

    camera = config["camera"]
    camera_target(camera)
    normalized = {
        key: [float(x) for x in camera[key]] for key in ("position", "direction", "up")
    }
    normalized["vertical_fov"] = float(camera["vertical_fov"])
    if "near_plane" in camera:
        import math

        near = float(camera["near_plane"])
        if not math.isfinite(near) or near <= 0:
            raise ValueError("Invalid camera near plane")
        normalized["near_plane"] = near
    scene = {
        "scene_source": config["scene_source"],
        "adapted": entry["adapted"],
        "asset_sha256": entry["asset_sha256"],
        "source_sha256": entry["source_sha256"],
        "runtime_receipt_sha256": entry["runtime_receipt_sha256"],
    }
    # Expectations and load policy are scene semantics even when asset bytes match.
    for key in (
        "expected_light_count",
        "expected_environment_present",
        "expected_material_counts",
        "expected_texture_slots",
        "asset_roots",
        "reference_runtime",
    ):
        if key in config:
            scene[key] = config[key]
    graph = experiment["graph"]
    transport = {
        "resolution": [experiment["render"]["width"], experiment["render"]["height"]],
        **{key: graph[key] for key in TRANSPORT_FIELDS},
    }
    return {
        "schema_version": 1,
        "camera_sha256": _digest(normalized),
        "scene_sha256": _digest(scene),
        "transport_sha256": _digest(transport),
    }


def validate_binding(record, config, entry, experiment):
    """Fail closed: a matching scene/view label alone never certifies a reference."""
    if record.get("binding") != binding_for_view(config, entry, experiment):
        raise ValueError(
            "Reference camera, scene inputs or transport binding differs; a new reference is required"
        )
    return record
