"""Read historical Falcor smoke captures without inventing missing experiment evidence."""

import re

from records.models import CapturedFrame, RunRecord
from records.provenance import sha256
from records.validation import (
    artifact_path,
    capture_rows,
    checked_image,
    dimensions,
    integer,
    read_json,
    require_digest,
)


def normalize(directory, manifest, manifest_digest):
    if (
        type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != 1
    ):
        raise ValueError("Unsupported Falcor record schema")
    config, config_digest = read_json(artifact_path(directory, "config.json"))
    if config != manifest["config"]:
        raise ValueError("Config differs from the embedded saved config")
    width, height = dimensions(config)
    count = integer(config["frames"], "frame budget", 1, 16384)
    if config.get("mode") not in ("path-tracer", "restir-pt"):
        raise ValueError("Unsupported Falcor mode")
    expected = config["captures"]
    if not isinstance(expected, list) or not expected:
        raise ValueError("Missing capture schedule")
    for frame in expected:
        integer(frame, "capture frame", 1, count)
    if expected != sorted(set(expected)):
        raise ValueError("Capture schedule must be sorted and unique")
    rows = capture_rows(manifest.get("artifacts"), expected)
    limitations = [
        "independent_rng_not_recorded",
        "history_controls_not_recorded",
        "target_equivalence_not_certified",
        "resolved_configuration_hashes_not_recorded",
    ]
    provenance = {
        "manifest": manifest,
        "config_sha256_observed": config_digest,
        "record_files": {
            "manifest.json": manifest_digest,
            "config.json": config_digest,
        },
        "gpu_time_ms": manifest.get("gpu_time_ms"),
        "transport": "native path tracing",
        "frame_interpretation": "unaccumulated output; frame number is not accumulated spp",
    }
    if "build_manifest" in manifest:
        path = artifact_path(directory, manifest["build_manifest"])
        build, digest = read_json(
            path, require_digest(manifest.get("build_manifest_sha256"))
        )
        if build.get("commit") != manifest.get("commit"):
            raise ValueError("Snapshot build and run commits differ")
        provenance["build_manifest_sha256"] = digest
        provenance["record_files"][manifest["build_manifest"]] = digest
    else:
        limitations.append("build_snapshot_missing")
    if (directory / "graphs.py").exists():
        graph = artifact_path(directory, "graphs.py")
        digest = require_digest(
            manifest["source_sha256"].get("scripts/falcor/graphs.py")
        )
        if sha256(graph) != digest:
            raise ValueError("Saved graph snapshot hash mismatch")
        provenance["graph_snapshot_sha256"] = digest
        provenance["record_files"]["graphs.py"] = digest
    else:
        limitations.append("graph_snapshot_missing")
    frames = []
    for index in expected:
        row = rows[index]
        if row.get("encoding") != "scene-linear RGB FLOAT32 EXR":
            raise ValueError("Unsupported capture encoding")
        image = artifact_path(directory, row["hdr"])
        match = re.fullmatch(
            r"capture\.PathTracer\.color\.(\d+)(?:\.RGBA)?\.exr", image.name
        )
        if not match or int(match[1]) != index:
            raise ValueError("Capture filename/frame mismatch")
        digest = require_digest(row.get("hdr_sha256"))
        checked_image(image, digest, width, height, float32_exr=True)
        if "preview" in row or "preview_sha256" in row:
            preview = artifact_path(directory, row.get("preview"))
            preview_digest = require_digest(row.get("preview_sha256"))
            if sha256(preview) != preview_digest:
                raise ValueError("Saved preview hash mismatch")
            provenance["record_files"][row["preview"]] = preview_digest
        frames.append(CapturedFrame(index, image, digest, None, None))
    return RunRecord(
        "falcor",
        directory,
        manifest_digest,
        width,
        height,
        tuple(frames),
        None,
        (),
        config,
        provenance,
        tuple(limitations),
        frozenset({"linear_rgb"}),
    )
