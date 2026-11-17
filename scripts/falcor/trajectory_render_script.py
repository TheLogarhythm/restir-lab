"""Build trajectory render scripts and verify camera evidence, independent of CLIs."""
import math
from pathlib import Path

from . import spatial_render_script


CAPTURE_FRAMES = tuple(range(41, 341))


def validate_schedule(frames, *, seed_offset=None):
    """Require 40 warmup poses, 300 video poses, and consecutive uint32 seeds.

    Preview callers may choose an offset. Formal replay explicitly requires zero.
    Resolution, route approval, and method budgets belong to their entry points.
    """
    if len(frames) != 340:
        raise ValueError("Trajectory requires the 40+300 frame budget")
    offset = frames[0].get("path_seed") if seed_offset is None else seed_offset
    if (type(offset) is not int or not 0 <= offset <= 2**32 - 340
            or any(type(r.get("frame")) is not int or type(r.get("path_seed")) is not int
                   for r in frames)
            or any(type(r.get("video_frame")) is not int for r in frames[40:])
            or [r.get("frame") for r in frames] != list(range(1, 341))
            or [r.get("video_frame") for r in frames] != [None] * 40 + list(range(300))
            or [r.get("path_seed") for r in frames] != list(range(offset, offset + 340))):
        raise ValueError("Trajectory requires the 40+300 frame budget and consecutive seeds")


def build_script(scene, frames, output, options, *, adapted=False, captures=None):
    """Reuse graph and camera setup, then apply every sampled pose before rendering."""
    validate_schedule(frames)
    captures = list(CAPTURE_FRAMES) if captures is None else captures
    initial = frames[0]["camera"]
    initial = {**initial, "direction": [b - a for a, b in zip(initial["position"], initial["target"])]}
    source = spatial_render_script.build_script(
        scene, initial, output, len(frames), options, adapted=adapted,
        capture_frames=captures, static_clock=True, record_scene_state=True,
        seed_offset=frames[0]["path_seed"])
    loop = "for frame in range(1, 341):"
    prefix = ("trajectory = " + repr(frames) + "\ntrajectory_records = []\n" + loop
              + "\n    pose = trajectory[frame - 1]['camera']"
              + "\n    camera.position = float3(*pose['position'])"
              + "\n    camera.target = float3(*pose['target'])"
              + "\n    camera.up = float3(*pose['up'])")
    if source.count(loop) != 1:
        raise ValueError("Trajectory loop does not match the declared 340-frame budget")
    source = source.replace(loop, prefix)
    source = source.replace("    m.renderFrame()", "    m.renderFrame()\n"
                            "    trajectory_records.append({**trajectory[frame - 1], 'actual_camera': camera_state(), 'actual_fixed_seed': int(tracer.fixedSeed), 'actual_clock_frame': int(m.clock.frame)})")
    source = source.replace("exit()", "Path(" + repr(str(Path(output) / "trajectory-records.json"))
                            + ").write_text(json.dumps(trajectory_records, indent=2), encoding='utf8')\nexit()")
    return source


def build_formal_script(scene, frames, output, options, *, adapted=False, phase="capture"):
    """Keep image capture and profiling separate, sharing every sampled camera pose."""
    if phase not in ("capture", "timing"):
        raise ValueError("Unknown formal trajectory phase")
    validate_schedule(frames, seed_offset=0)
    from . import spatial_measure as measure
    source = build_script(scene, frames, output, options, adapted=adapted, captures=CAPTURE_FRAMES)
    if phase == "capture":
        return source.replace("for frame in range(1, 341):",
                              "m.profiler.enabled = False\nfor frame in range(1, 341):", 1)
    source = measure.instrument(source, CAPTURE_FRAMES, False, drain_last_frame=True)
    # The extra render exists solely to read frame 340's previous-frame timestamps.
    # Hold its final pose; its own sample is neither displayed nor measured.
    source = source.replace("trajectory[frame - 1]", "trajectory[min(frame, 340) - 1]")
    append = "    trajectory_records.append("
    if source.count(append) != 1:
        raise ValueError("Unexpected trajectory evidence boundary")
    return source.replace(append, "    if frame <= 340: trajectory_records.append(", 1)


def verify_camera_records(records, frames):
    if len(records) != len(frames):
        raise ValueError("Incorrect trajectory frame count")
    for actual, expected in zip(records, frames):
        if any(actual.get(key) != value for key, value in expected.items()):
            raise ValueError("Requested trajectory record changed")
        if actual.get("actual_fixed_seed") != expected["path_seed"] or actual.get("actual_clock_frame") != expected["frame"]:
            raise ValueError("Actual camera frame or seed differs")
        camera = actual["actual_camera"]
        for name in ("position", "target", "up"):
            vector = camera.get(name)
            if (not isinstance(vector, list) or len(vector) != 3
                    or any(type(a) not in (int, float) or not math.isfinite(a) or abs(a - b) > 2e-5
                           for a, b in zip(vector, expected["camera"][name]))):
                raise ValueError("Actual camera differs from sampled trajectory")
        focal = 12 / math.tan(math.radians(expected["camera"]["vertical_fov"]) / 2)
        if any(type(camera.get(name)) not in (int, float) or not math.isfinite(camera[name])
               for name in ("frameHeight", "focalLength", "apertureRadius", "nearPlane")):
            raise ValueError("Nonfinite trajectory projection")
        if (abs(camera["frameHeight"] - 24) > 1e-5 or abs(camera["focalLength"] - focal) > 1e-4
                or abs(camera["nearPlane"] - expected["camera"]["near_plane"]) > 1e-6
                or camera["apertureRadius"] != 0 or camera["animated"] is not False):
            raise ValueError("Trajectory projection changed")
