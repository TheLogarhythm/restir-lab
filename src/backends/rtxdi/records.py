"""Offline adapter for schema-3 RTXDI direct-lighting experiment captures."""

import copy
import hashlib
import json
import math

from records.models import CapturedFrame, RunRecord
from records.validation import (
    artifact_path,
    capture_rows,
    checked_image,
    dimensions,
    integer,
    read_json,
    require_digest,
)

_SURFACE = (
    "rendering.rayQuery",
    "rendering.pixelJitter",
    "postProcessing.textures",
    "gbuffer.alphaTested",
    "gbuffer.transparent",
    "gbuffer.rasterizeGBuffer",
)
_LIGHTING_SOURCES = (
    "scripts/run/build_rtxdi_experiments.py",
    "scripts/run/rtxdi_experiments.patch",
    "scripts/run/rtxdi_experiments/LabExperiment.h",
    "scripts/run/rtxdi_emission.py",
)


def _validate_estimator_build(build):
    """Require recorded estimator identity before declaring runs comparable."""
    if not isinstance(build, dict):
        raise ValueError("Missing or invalid RTXDI build record")
    try:
        require_digest(build.get("executable_sha256"))
    except ValueError as exc:
        raise ValueError("Missing or invalid RTXDI executable fingerprint") from exc
    shaders = build.get("shader_sha256")
    if not isinstance(shaders, dict) or not shaders:
        raise ValueError("Missing or empty RTXDI shader fingerprint inventory")
    for name, digest in shaders.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Invalid RTXDI shader name")
        try:
            require_digest(digest)
        except ValueError as exc:
            raise ValueError("Invalid RTXDI shader fingerprint: " + name) from exc


def lighting_signature(build):
    """Match the historical importer/lighting contract, not estimator binaries."""
    values = (
        build["renderer_commit"],
        build["donut"]["commit"],
        build["donut"]["source_sha256"]["src/engine/GltfImporter.cpp"],
        *(build["integration_sha256"][name] for name in _LIGHTING_SOURCES),
    )
    if not all(isinstance(value, str) and value for value in values):
        raise ValueError("Missing lighting provenance")
    return values


def _target(config, frame, asset_hash):
    value = {
        "scene_id": config["scene_id"],
        "asset_sha256": asset_hash,
        "renderer_commit": config["definition"]["renderer_commit"],
        "resolution": [config["width"], config["height"]],
        "camera": {key: frame[key] for key in ("position", "direction", "up")},
        "vertical_fov": config["scene"]["camera"]["vertical_fov"],
        "lighting": config["scene"]["lighting"],
        "analytic_sun": config["definition"].get("analytic_sun", True),
        "surface_settings": {key: config["arguments"].get(key) for key in _SURFACE},
        "output": "scene-linear direct illumination + upstream emission/background/glass",
    }
    if (
        "lighting" in frame
        and frame["lighting"].get("emissive_intensity_multiplier") != 1.0
    ):
        value["lighting_state"] = copy.deepcopy(frame["lighting"])
    return value


def _controls(config):
    frames = config["frames"]
    if not isinstance(frames, list) or not frames:
        raise ValueError("Missing frame controls")
    previous = None
    seed_base = config["seed"] * 1048576
    sampling_offset = None
    for frame in frames:
        index = integer(frame["frame"], "control frame", 1)
        sampling = integer(frame["sampling_frame"], "sampling_frame")
        offset = sampling - seed_base - index + 1
        if (
            offset < 0
            or sampling >= seed_base + 1048576
            or sampling_offset is not None
            and offset != sampling_offset
        ):
            raise ValueError(
                "RNG sampling must advance once per frame within its seed block"
            )
        sampling_offset = offset
        if type(frame["reset"]) is not bool or type(frame["capture"]) is not bool:
            raise ValueError("Invalid capture/reset flag")
        if previous is not None and index != previous + 1:
            raise ValueError("Control frames must be contiguous and unique")
        for key in ("position", "direction", "up"):
            vector = frame[key]
            if (
                not isinstance(vector, list)
                or len(vector) != 3
                or any(
                    type(v) not in (int, float) or not math.isfinite(v) for v in vector
                )
            ):
                raise ValueError("Invalid camera vector")
        previous = index
    if frames[0]["reset"] is not True:
        raise ValueError("Control sequence must begin with a history reset")
    return frames, sampling_offset


def normalize(directory, manifest, manifest_digest):
    config_path = artifact_path(directory, "config.json")
    config, config_digest = read_json(
        config_path, require_digest(manifest.get("config_sha256"))
    )
    if config.get("schema_version") != 3 or config.get("reference"):
        raise ValueError(
            "Expected schema-3 baseline run; reference checkpoints use a separate format"
        )
    width, height = dimensions(config)
    seed = integer(config.get("seed"), "independent seed", 0, 4095)
    arguments = config["arguments"]
    required = {
        "lighting.indirectMode": "NONE",
        "denoiser.mode": "OFF",
        "postProcessing.aaMode": "OFF",
        "rendering.pixelJitter": 0,
        "scene.animation": 0,
        "restirDI.shading.enableFinalVisibility": 1,
    }
    if any(arguments.get(key) != value for key, value in required.items()):
        raise ValueError(
            "Reader supports frozen unprocessed direct-lighting baselines only"
        )
    controls, sampling_offset = _controls(config)
    expected = [frame["frame"] for frame in controls if frame["capture"]]
    rows = capture_rows(manifest.get("captures"), expected)
    asset_hash = require_digest(manifest["scene"]["sha256"])
    _validate_estimator_build(manifest["build"])
    lighting = lighting_signature(manifest["build"])
    if lighting[0] != config["definition"]["renderer_commit"]:
        raise ValueError("Config and build renderer revisions differ")
    frames = []
    keys = {}
    for frame in controls:
        index = frame["frame"]
        if index not in rows:
            continue
        image = artifact_path(directory, f"frame-{index:04d}.pfm.gz")
        digest = require_digest(rows[index].get("image_sha256"))
        checked_image(image, digest, width, height)
        target = _target(config, frame, asset_hash)
        keys[str(index)] = hashlib.sha256(
            json.dumps(target, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:24]
        frames.append(
            CapturedFrame(
                index, image, digest, frame["reset"], frame["sampling_frame"], target
            )
        )
    return RunRecord(
        "rtxdi",
        directory,
        manifest_digest,
        width,
        height,
        tuple(frames),
        seed,
        tuple(controls),
        config,
        {
            "manifest": manifest,
            "config_sha256": config_digest,
            "lighting_signature": lighting,
            "rng_schedule": {
                "policy": "seed * 1048576 + frame - 1 + constant offset",
                "sampling_offset": sampling_offset,
            },
            "record_files": {
                "manifest.json": manifest_digest,
                "config.json": config_digest,
            },
            "legacy_target_keys": keys,
            "transport": "direct illumination plus native emission/background/glass",
        },
        (),
        frozenset({"linear_rgb", "independent_trials", "native_target"}),
    )
