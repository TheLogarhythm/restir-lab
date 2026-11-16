"""Small archived PT captures with real FLOAT32 EXRs and frozen collector evidence."""
import hashlib
import json
from pathlib import Path

import numpy as np
import OpenEXR


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def index_archive(root):
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["files"] = [
        {"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size, "sha256": digest(p)}
        for p in sorted(root.rglob("*")) if p.is_file() and p != root / "manifest.json"
    ]
    save(root / "manifest.json", manifest)


def write_archive(root, seeds=(0, 100), *, included=True):
    root = Path(root)
    root.mkdir(parents=True)
    graph = {"samplesPerPixel": 1, "sampleGenerator": 0, "useReSTIRPT": True,
             "maxSurfaceBounces": 10,
             "reSTIRPathTracingOptions": {"useTemporalResampling": True}}
    camera = {"position": [0, 0, 2], "target": [0, 0, 0], "up": [0, 1, 0],
              "animated": False, "apertureRadius": 0, "focalLength": 24, "frameHeight": 24}
    qualities = []
    for seed in seeds:
        directory = root / f"room/temporal-on/quality/seed-{seed}"
        directory.mkdir(parents=True)
        expression = "frame - 1" if seed == 0 else f"{seed} + frame - 1"
        script = f"""from falcor import RenderGraph, createPass
# Only parsed; the offline reader must never import or execute this script.
g = RenderGraph('capture')
g.addPass(createPass('PathTracer', {graph!r}), 'PathTracer')
m.addGraph(g)
m.loadScene('retired-scene.pyscene')
m.scene.animated = False
camera = m.scene.camera
camera.animated = False
m.clock.framerate = 0
m.clock.pause()
m.clock.time = 0
tracer = g['PathTracer']
tracer.useFixedSeed = True
for frame in range(1, 6):
    tracer.fixedSeed = {expression}
    m.clock.frame = frame
    m.renderFrame()
    if frame in [3, 4, 5]: m.frameCapture.capture()
"""
        (directory / "render.py").write_text(script, encoding="utf-8")
        resolved = dict(graph, fixedSeed=seed + 4)
        (directory / "resolved.py").write_text(
            "def render_graph_capture():\n    g.create_pass('PathTracer', 'PathTracer', "
            + repr(resolved) + ")\n", encoding="utf-8")
        save(directory / "resolved-camera.json", {
            "initial": camera, "first_frame": dict(camera, frame=1),
            "last_frame": dict(camera, frame=5)})
        save(directory / "scene-state.json", {
            "lights": [{"name": "sun", "active": True, "intensity": [1, 1, 1]}],
            "environment_present": True, "useAnalyticLights": True,
            "useEnvLight": True, "useEmissiveLights": True})
        artifacts = []
        for frame in (3, 4, 5):
            image = directory / f"capture.PathTracer.color.{frame}.exr"
            OpenEXR.File({}, {"RGB": np.full((2, 3, 3), 1 + seed / 1000,
                                            dtype=np.float32)}).write(str(image))
            artifacts.append({"frame": frame, "seed": seed + frame - 1,
                              "reuse_seed": seed + frame - 2, "hdr": image.name,
                              "sha256": digest(image)})
        policy = ("path fixedSeed=frame-1; ReSTIR reuse seed=max(0,frame-2); first temporal pass skipped"
                  if seed == 0 else
                  f"path fixedSeed={seed}+frame-1; ReSTIR reuse seed=0 on first frame, otherwise {seed}+frame-2; first temporal pass skipped")
        save(directory / "manifest.json", {
            "schema_version": 1, "backend": "falcor", "status": "completed",
            "kind": "cgns_pt_temporal_single_frame", "requested_method": "baseline",
            "scene_id": "classroom", "view_id": "view-a", "resolution": [3, 2],
            "warmup_frames": 2, "capture_frames": [3, 4, 5], "seed_offset": seed,
            "seed_policy": policy, "spp_per_frame": 1, "image_accumulation": False,
            "temporal_reuse": True, "clock_policy": {"paused": True, "framerate": 0, "time": 0},
            "requested_graph_options": graph, "scene_config_sha256": "a" * 64,
            "asset_sha256": {"retired-scene": "b" * 64}, "source_sha256": {},
            "build_commit": "c" * 40, "runtime_verification": {"receipt_sha256": "d" * 64},
            "runtime_spatial_shader_sha256": "e" * 64,
            "render_script_sha256": digest(directory / "render.py"),
            "artifacts": artifacts, "pid": seed + 10, "exit_code": 0,
            "command": ["retired-renderer.exe", "--script", "retired-capture/render.py"]})
        qualities.append({"seed_offset": seed, "directory": directory.relative_to(root).as_posix(),
                          "source_run_id": f"retired-batch/room/quality/seed-{seed}"})
    timing = root / "room/temporal-on/timing"
    save(timing / "manifest.json", {"status": "completed", "seed_offset": 0,
                                     "requested_method": "baseline", "temporal_reuse": True,
                                     "scene_id": "classroom", "view_id": "view-a"})
    save(root / "room/view.json", {"scene_id": "classroom", "view_id": "view-a",
                                    "config_sha256": "a" * 64})
    save(root / "room/reference/reference.json", {"final": {
        "scene_id": "classroom", "view_id": "view-a", "path": "retired-reference.exr"}})
    save(root / "manifest.json", {"schema_version": 1, "kind": "falcor_pt_stage_archive",
        "status": "completed_compacted", "path_base": "archive_root", "resolution": [3, 2],
        "quality_seed_offsets": list(seeds), "quality_frames": [3, 4, 5], "timing_frames": [3, 4, 5],
        "views": {"room": {"view_config": "room/view.json", "reference": "room/reference/reference.json",
            "methods": {"temporal-on": {"quality": qualities, "timing": {
                "directory": "room/temporal-on/timing", "included": included,
                "exclusion_reason": None if included else "Unstable timing attempts",
                "seed_offset": 0, "source_run_id": "retired-timing-recheck"}}}}}, "files": []})
    index_archive(root)
    return root
