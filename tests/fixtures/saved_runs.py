"""Tiny independent saved-run files; mutations and hash refreshes stay explicit."""

import hashlib
import json
from pathlib import Path
import numpy as np
from .provenance import lighting_build


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def write_rtxdi_run(directory, *, seed=1, value=1.0):
    directory = Path(directory)
    directory.mkdir(parents=True)
    controls = [
        dict(
            frame=i,
            sampling_frame=seed * 1048576 + i - 1,
            position=[0, 0, -3],
            direction=[0, 0, 1],
            up=[0, 1, 0],
            reset=i == 1,
            capture=True,
        )
        for i in range(1, 5)
    ]
    config = dict(
        schema_version=3,
        scene_id="fixture",
        mode="combined",
        scenario="static",
        seed=seed,
        width=3,
        height=2,
        frames=controls,
        definition={"renderer_commit": "fixture-renderer", "analytic_sun": True},
        scene={"camera": {"vertical_fov": 60}, "lighting": {"environment": False}},
        arguments={
            "lighting.indirectMode": "NONE",
            "denoiser.mode": "OFF",
            "postProcessing.aaMode": "OFF",
            "rendering.pixelJitter": 0,
            "scene.animation": 0,
            "restirDI.shading.enableFinalVisibility": 1,
        },
    )
    save(directory / "config.json", config)
    captures = []
    # Write PFM bytes directly, independently of the decoder and production writer.
    import gzip

    for row in controls:
        rgb = np.full((2, 3, 3), value + row["frame"], dtype="<f4")
        image = directory / f"frame-{row['frame']:04d}.pfm.gz"
        image.write_bytes(
            gzip.compress(b"PF\n3 2\n-1.0\n" + rgb[::-1].tobytes(), mtime=0)
        )
        captures.append({"frame": row["frame"], "image_sha256": digest(image)})
    manifest = {
        "status": "completed",
        "config_sha256": digest(directory / "config.json"),
        "captures": captures,
        "scene": {"sha256": "a" * 64},
        "build": lighting_build(),
    }
    save(directory / "manifest.json", manifest)
    return directory


def write_falcor_run(directory, *, snapshots=True, value=1.0):
    import OpenEXR
    from PIL import Image

    directory = Path(directory)
    directory.mkdir(parents=True)
    config = dict(
        schema_version=1,
        width=3,
        height=2,
        frames=4,
        captures=[1, 4],
        timeout=600,
        mode="path-tracer",
    )
    save(directory / "config.json", config)
    artifacts = []
    for frame in config["captures"]:
        image = directory / f"capture.PathTracer.color.{frame}.exr"
        OpenEXR.File(
            {}, {"RGB": np.full((2, 3, 3), value + frame, dtype=np.float32)}
        ).write(str(image))
        preview = directory / f"frame-{frame:04d}.png"
        Image.fromarray(np.full((2, 3, 3), 128, dtype=np.uint8)).save(preview)
        artifacts.append(
            {
                "frame": frame,
                "preview": preview.name,
                "preview_sha256": digest(preview),
                "hdr": image.name,
                "hdr_sha256": digest(image),
                "encoding": "scene-linear RGB FLOAT32 EXR",
            }
        )
    manifest = {
        "schema_version": 1,
        "backend": "falcor",
        "status": "completed",
        "config": config,
        "commit": "b" * 40,
        "kind": "bounded_setup_smoke",
        "artifacts": artifacts,
        "rng_policy": "native PathTracer frameCount seed, fresh process, fixedSeed unset",
        "gpu_time_ms": None,
        "source_sha256": {},
        "asset_sha256": {"scene.gltf": "a" * 64},
    }
    save(directory / "resolved-camera.json", {"position": [0, 0, -3]})
    (directory / "resolved.py").write_text(
        "raise AssertionError('never execute saved graphs')\n"
    )
    if snapshots:
        save(directory / "build.json", {"commit": manifest["commit"]})
        manifest.update(
            build_manifest="build.json",
            build_manifest_sha256=digest(directory / "build.json"),
        )
        (directory / "graphs.py").write_text("# snapshotted graph\n")
        manifest["source_sha256"]["scripts/falcor/graphs.py"] = digest(
            directory / "graphs.py"
        )
    else:
        manifest["build_manifest_sha256"] = "c" * 64
    save(directory / "manifest.json", manifest)
    return directory
