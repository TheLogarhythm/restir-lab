"""Capture approved 1080p PT walks, replay native GPU timings, then encode media.

The timing replay renders 340 trajectory frames plus one timestamp-drain frame.
Only the capture phase writes HDR; encoding never launches a renderer.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess

from . import camera_trajectory, trajectory_render_script as trajectory_script
from . import spatial_capture as capture, spatial_measure as measure
from . import spatial_experiment_config as settings, run, capture_lifecycle
from . import reference_extension_batch, reference_extension_gallery as gallery
from .adapted_reference_runner import isolated_python_environment
from .process_utils import check_renderer_idle, exclusive_operation

ROOT = Path(__file__).resolve().parents[2]
ROUTES = ROOT / "scenes/trajectories/pt-walkthroughs"
APPROVED = frozenset(("classroom", "bistro-interior", "bistro-exterior", "zero-day"))
METHODS = {"baseline": "Baseline", "pdf-similarity": "PDF similarity", "cgns": "CGNS"}
SCHEDULE = list(trajectory_script.CAPTURE_FRAMES)
GPU_TOTAL_EVENT = "/onFrameRender/gpu_time"
RESOLUTION = [1920, 1080]
# The tracked receipt binds existing user approval; the local preflight is provenance only.
APPROVAL_RECEIPT = ROUTES / "approved-routes.json"
PREFLIGHT = ROOT / "build/pt-trajectory-production/preflight.json"


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def _new_output(output):
    output = Path(output).resolve()
    if output.exists() or not output.is_relative_to((ROOT / "runs").resolve()):
        raise ValueError("Formal video requires a new output directory under runs")
    return output


def _approved_trajectory(path):
    path = Path(path).resolve()
    if path.parent != ROUTES.resolve() or path.stem not in APPROVED or path.suffix != ".json":
        raise ValueError("Formal video requires an approved trajectory")
    if not APPROVAL_RECEIPT.is_file():
        raise ValueError("Formal video requires the tracked trajectory approval receipt")
    receipt = _json(APPROVAL_RECEIPT)
    if receipt.get("schema_version") != 1:
        raise ValueError("Unsupported trajectory approval receipt schema")
    approved_hashes = receipt.get("trajectory_sha256", {})
    if approved_hashes.get(path.relative_to(ROOT).as_posix()) != run.sha(path):
        raise ValueError("Formal video differs from the approved trajectory hash")
    config = camera_trajectory.load(path)
    frames = camera_trajectory.sample_frames(config)
    trajectory_script.validate_schedule(frames, seed_offset=0)
    return path, config, frames


def render_script(scene, frames, output, options, *, adapted=False, phase="capture"):
    """Generate the separately budgeted formal capture or timing phase."""
    return trajectory_script.build_formal_script(scene, frames, output, options,
        adapted=adapted, phase=phase)


def timing_rows(records):
    """Extract exact parent GPU timestamps; never sum nested passes or use CPU time.

    The first 14 display windows use the available captured frames; subsequent
    windows contain exactly 15 frames. Raw timings and every GPU stage survive.
    """
    if not isinstance(records, list) or len(records) != 341:
        raise ValueError("Timing replay requires 340 frames and one timestamp drain")
    rows = []
    for frame, record in enumerate(records, 1):
        if (type(record.get("rendered_frame")) is not int or record["rendered_frame"] != frame
                or type(record.get("gpu_measured_frame")) is not int
                or record["gpu_measured_frame"] != frame - 1):
            raise ValueError("Incorrect previous-frame GPU timing alignment")
        measured = frame - 1
        if measured not in SCHEDULE:
            continue
        events = record.get("events_previous_frame")
        if not isinstance(events, dict) or not any(key.endswith("/tracePass/gpu_time") for key in events):
            raise ValueError("Missing native GPU path trace stage")
        gpu_events = {}
        for name, lane in events.items():
            if not name.endswith("/gpu_time"):
                continue
            value = lane.get("value") if isinstance(lane, dict) else None
            if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value < 1e8:
                raise ValueError("Invalid native GPU timestamp")
            gpu_events[name] = value
        value = gpu_events.get(GPU_TOTAL_EVENT)
        if value is None or value <= 0:
            raise ValueError("Missing positive onFrameRender GPU total; CPU fallback is prohibited")
        window = [row["gpu_ms_raw"] for row in rows[-14:]] + [value]
        average = math.fsum(window) / len(window)
        rows.append({"frame": measured, "video_frame": measured - 41,
                     "video_time_seconds": (measured - 41) / 30,
                     "gpu_ms_raw": value, "gpu_ms_mean15": average,
                     "gpu_fps_mean15": 1000 / average,
                     "smoothing_frames": len(window), "gpu_events_ms": gpu_events})
    if [row["frame"] for row in rows] != SCHEDULE:
        raise ValueError("Missing captured-frame GPU timings")
    return rows


def watermark(method, row):
    return (f"{METHODS[method]} | GPU {row['gpu_ms_mean15']:.2f} ms | "
            f"{row['gpu_fps_mean15']:.2f} GPU FPS | Playback 30 FPS")


def _artifact(path, directory, **metadata):
    return {**metadata, "path": Path(path).relative_to(directory).as_posix(), "sha256": run.sha(path)}


def _verify_render_evidence(directory, base, options, frames, adapted, phase):
    records = _json(directory / "trajectory-records.json")
    trajectory_script.verify_camera_records(records, frames)
    resolved = (directory / "resolved.py").read_text(encoding="utf8")
    capture.cgns_pt_smoke.validate_resolved_graph(resolved, options)
    capture.cgns_pt_smoke.validate_resolved_graph(resolved, capture.spatial_render_script.VBUFFER_OPTIONS, "VBufferRT")
    cameras = _json(directory / "resolved-camera.json")
    expected_poses = {"initial": records[0]["actual_camera"], "first_frame": records[0]["actual_camera"],
                      "last_frame": records[-1]["actual_camera"]}
    for name, expected in expected_poses.items():
        actual = dict(cameras.get(name, {}))
        if name != "initial" and actual.pop("frame", None) != (1 if name == "first_frame" else 340 + (phase == "timing")):
            raise ValueError("Resolved trajectory endpoint frame changed")
        if actual != expected:
            raise ValueError("Resolved trajectory endpoint camera changed")
    state = _json(directory / "scene-state.json")
    audit = _json(directory / "scene-audit.json") if adapted else None
    capture.views.validate_current_scene_state(base, state, audit)
    names = ["trajectory.json", "requested-frames.json", "trajectory-records.json", "resolved.py",
             "resolved-camera.json", "scene-state.json", "render.py"]
    if adapted:
        names.append("scene-audit.json")
    return [_artifact(directory / name, directory, kind="evidence") for name in names]


def _source_hashes(method, trajectory_path, scene_config_path):
    paths = {*capture.dependency_files(method), Path(capture.__file__), Path(__file__),
             Path(camera_trajectory.__file__), Path(trajectory_script.__file__), Path(measure.__file__),
             APPROVAL_RECEIPT,
             trajectory_path, scene_config_path, settings.DEFAULT_CONFIG,
             capture.views.scene_manifest_path()}
    if PREFLIGHT.exists():
        paths.add(PREFLIGHT)
    return {Path(path).resolve().relative_to(ROOT).as_posix(): run.sha(path) for path in paths}


def _verified_source(directory, phase, trajectory_path, method):
    directory = Path(directory).resolve(strict=True)
    if not directory.is_relative_to((ROOT / "runs").resolve()):
        raise ValueError("Video sources must be retained under runs")
    manifest = _json(directory / "manifest.json")
    if (manifest.get("status") != "completed" or manifest.get("kind") != "falcor_formal_trajectory_" + phase
            or manifest.get("requested_method") != method or manifest.get("resolution") != RESOLUTION
            or manifest.get("temporal_reuse") is not True or manifest.get("warmup_frames") != 40
            or manifest.get("capture_frames") != SCHEDULE
            or manifest.get("trajectory_sha256") != run.sha(trajectory_path)):
        raise ValueError("Video source does not match the approved trajectory and method")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("Video source lacks verified artifact evidence")
    seen = set()
    for artifact in artifacts:
        relative = artifact.get("path")
        if not isinstance(relative, str):
            raise ValueError("Invalid source artifact path")
        path = (directory / relative).resolve(strict=True)
        if not path.is_relative_to(directory) or relative in seen or run.sha(path) != artifact.get("sha256"):
            raise ValueError("Video source artifact changed or escaped its directory")
        seen.add(relative)
    required = {"trajectory.json", "requested-frames.json", "trajectory-records.json", "resolved.py",
                "resolved-camera.json", "scene-state.json", "render.py", "validation.json"}
    if phase == "timing":
        required.update(("timings.json", "gpu-frame-timings.json", "timing-validation.json"))
        if list(directory.glob("*.exr")):
            raise ValueError("Timing replay unexpectedly contains images")
    else:
        captures = [a for a in artifacts if a.get("kind") == "linear_hdr"]
        if [a.get("frame") for a in captures] != SCHEDULE:
            raise ValueError("Capture source lacks exactly 300 ordered linear HDR frames")
        actual = sorted(directory.glob("*.exr"))
        run.capture_frames(actual, SCHEDULE)
        if {path.name for path in actual} != {a["path"] for a in captures}:
            raise ValueError("Capture image inventory differs from its manifest")
    if not required.issubset(seen):
        raise ValueError("Video source evidence inventory is incomplete")
    return directory, manifest


def _encode(trajectory_path, output, method, capture_output, timing_output, timeout):
    if capture_output is None or timing_output is None:
        raise ValueError("Encoding requires retained capture_output and timing_output")
    capture_dir, captured = _verified_source(capture_output, "capture", trajectory_path, method)
    timing_dir, timed = _verified_source(timing_output, "timing", trajectory_path, method)
    for key in ("trajectory_sha256", "requested_graph_options", "runtime_verification", "source_sha256",
                "asset_sha256", "scene_config_sha256", "experiment_config_sha256", "display_transform"):
        if captured.get(key) != timed.get(key):
            raise ValueError("Capture and timing replay inputs differ: " + key)
    frames = camera_trajectory.sample_frames(camera_trajectory.load(trajectory_path))
    for directory in (capture_dir, timing_dir):
        if _json(directory / "requested-frames.json") != frames:
            raise ValueError("Retained requested trajectory changed")
        trajectory_script.verify_camera_records(_json(directory / "trajectory-records.json"), frames)
    measure.validate_timings(timing_dir / "timings.json", SCHEDULE, drain_last_frame=True)
    rows = timing_rows(_json(timing_dir / "timings.json"))
    if _json(timing_dir / "gpu-frame-timings.json") != rows:
        raise ValueError("Derived GPU timings differ from raw profiler records")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        raise RuntimeError("ffmpeg and ffprobe are required for verified H.264 encoding")
    source_manifests = {str(directory.relative_to(ROOT)): run.sha(directory / "manifest.json")
                        for directory in (capture_dir, timing_dir)}
    inputs = [a for a in captured["artifacts"] if a.get("kind") == "linear_hdr"]
    command = [ffmpeg, "-nostdin", "-v", "error", "-n", "-framerate", "30", "-start_number", "0",
               "-i", str(output / "display/frame-%03d.png"), "-frames:v", "300", "-c:v", "libx264",
               "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output / "video.mp4")]
    display = captured["display_transform"]
    def prepare(directory):
        from PIL import Image, ImageDraw, ImageFont
        destination = directory / "display"
        destination.mkdir(exist_ok=False)
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf"
        font = ImageFont.truetype(str(font_path), 30) if font_path.exists() else ImageFont.load_default(size=30)
        for artifact, row in zip(inputs, rows):
            rgb = run.inspect_hdr(capture_dir / artifact["path"], *RESOLUTION)
            picture = Image.fromarray(gallery.display(rgb, display["method"], display["ev"]))
            draw = ImageDraw.Draw(picture)
            label = watermark(method, row)
            draw.rectangle((0, 0, picture.width, 52), fill="black")
            draw.text((16, 9), label, font=font, fill="white")
            picture.save(destination / f"frame-{row['video_frame']:03d}.png")
        run.save(directory / "gpu-frame-timings.json", rows)
        run.save(directory / "watermarks.json", [{"video_frame": row["video_frame"], "label": watermark(method, row)} for row in rows])
    def verify(directory):
        from PIL import Image
        paths = sorted((directory / "display").glob("*.png"))
        if [path.name for path in paths] != [f"frame-{frame:03d}.png" for frame in range(300)]:
            raise ValueError("Encoded video lacks exactly 300 display frames")
        for path in paths:
            with Image.open(path) as image:
                if image.size != tuple(RESOLUTION) or image.mode != "RGB":
                    raise ValueError("Malformed 1080p RGB display frame")
        probe = json.loads(subprocess.check_output([ffprobe, "-v", "error", "-select_streams", "v:0", "-count_frames",
            "-show_entries", "stream=codec_name,width,height,pix_fmt,r_frame_rate,nb_read_frames,duration", "-of", "json", str(directory / "video.mp4")],
            text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
        streams = probe.get("streams", [])
        if len(streams) != 1:
            raise ValueError("Video does not contain exactly one inspected video stream")
        stream = streams[0]
        if (stream.get("codec_name") != "h264" or [stream.get("width"), stream.get("height")] != RESOLUTION
                or stream.get("pix_fmt") != "yuv420p" or stream.get("r_frame_rate") != "30/1"
                or stream.get("nb_read_frames") != "300" or abs(float(stream.get("duration", 0)) - 10) > 0.001):
            raise ValueError("Encoded H.264 video differs from the 1080p/300-frame/30FPS/10s budget")
        for path, digest in source_manifests.items():
            if run.sha(ROOT / path / "manifest.json") != digest:
                raise ValueError("Source manifest changed while encoding")
        # Recheck all input hashes after display conversion and encoding.
        _verified_source(capture_dir, "capture", trajectory_path, method)
        _verified_source(timing_dir, "timing", trajectory_path, method)
        run.save(directory / "video-probe.json", probe)
        return [_artifact(path, directory, kind="display_png", video_frame=index) for index, path in enumerate(paths)] + [
            _artifact(directory / name, directory, kind="media" if name == "video.mp4" else "evidence")
            for name in ("video.mp4", "gpu-frame-timings.json", "watermarks.json", "video-probe.json")]
    return run.execute(command, output, timeout, prepare=prepare, verify=verify, metadata={
        "kind": "falcor_formal_trajectory_encode", "phase": "encode", "requested_method": method,
        "trajectory_id": captured["trajectory_id"], "trajectory_sha256": captured["trajectory_sha256"],
        "resolution": RESOLUTION, "frame_count": 300, "fps_playback": 30, "duration_seconds": 10,
        "source_manifests_sha256": source_manifests, "display_transform": display,
        "gpu_total_event": GPU_TOTAL_EVENT, "gpu_smoothing": "trailing 15 captured frames; partial initial windows",
        "gpu_timing_source": "Separate image-free deterministic replay; raw previous-frame GPU timestamps",
        "watermark_example": watermark(method, rows[0]), "driver_sha256": run.sha(__file__)})


def launch(trajectory_path, output, runtime, method, *, phase="capture", capture_output=None,
           timing_output=None, timeout=7200):
    """Run one fixed-budget phase and return its unique manifest path."""
    if method not in METHODS:
        raise ValueError("Unknown comparison method")
    if phase not in ("capture", "timing", "encode"):
        raise ValueError("Unknown formal video phase")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 7200:
        raise ValueError("Formal video timeout must be at most two hours")
    output = _new_output(output)
    trajectory_path, config, frames = _approved_trajectory(trajectory_path)
    if phase == "encode":
        return _encode(trajectory_path, output, method, capture_output, timing_output, timeout)
    capture_lifecycle.check_shader_environment()
    if capture_output is not None or timing_output is not None:
        raise ValueError("Source directories are only accepted by the encode phase")
    if phase == "capture" and shutil.disk_usage(ROOT).free < 20 * 1024**3:
        raise ValueError("Formal capture requires at least 20 GiB free disk space")
    runtime = Path(runtime).resolve(strict=True)
    scene_config_path = (ROOT / config["scene_config"]).resolve(strict=True)
    if not scene_config_path.is_relative_to(ROOT):
        raise ValueError("Scene configuration escapes workspace")
    base = capture.views.load_config(scene_config_path)
    entry = capture.views.frozen_views()[(base["scene_id"], base["view_id"])]
    experiment, digest = settings.load_config_snapshot(settings.DEFAULT_CONFIG)
    options = capture.graph_options(method, experiment, temporal_reuse=True)
    parameters = experiment["methods"][method]["shader"] if method in ("cgns", "pdf-similarity") else None
    scene = (ROOT / base["scene_source"]).resolve(strict=True)
    if not scene.is_relative_to(ROOT):
        raise ValueError("Scene source escapes workspace")
    source = render_script(scene, frames, output, options, adapted=entry["adapted"], phase=phase).encode("utf8")
    command = [str(runtime / "Mogwai.exe"), "--device-type", "d3d12", "--width", "1920", "--height", "1080",
               "--script", str(output / "render.py"), "--headless"]
    with exclusive_operation(ROOT / "build/falcor/.operation.lock"):
        check_renderer_idle()
        built, reference, receipt = capture.verify_launch_inputs(base, entry, runtime, method, experiment, parameters)
        hashes = _source_hashes(method, trajectory_path, scene_config_path)
        gpu = subprocess.check_output(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"], text=True).strip()
        git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        git_dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).splitlines()
        transform, exposure = gallery.RECIPES[(base["scene_id"], base["view_id"])]
        metadata = {**capture.portable_paths(settings.DEFAULT_CONFIG, runtime, command, ROOT),
            "kind": "falcor_formal_trajectory_" + phase, "phase": phase,
            "trajectory_id": config["id"], "trajectory_path": trajectory_path.relative_to(ROOT).as_posix(),
            "trajectory_sha256": run.sha(trajectory_path), "requested_method": method,
            "scene_id": base["scene_id"], "view_id": base["view_id"],
            "scene_config_path": config["scene_config"], "scene_config_sha256": run.sha(scene_config_path),
            "asset_sha256": entry["asset_sha256"], "scene_source_sha256": entry["source_sha256"],
            "source_sha256": hashes, "experiment_config_sha256": digest, "experiment_config": experiment,
            "resolution": RESOLUTION, "warmup_frames": 40, "capture_frames": SCHEDULE,
            "rendered_frames": 340 + (phase == "timing"), "captured_frames": 300 if phase == "capture" else 0,
            "profiler_drain_frames": int(phase == "timing"), "temporal_reuse": True,
            "spp_per_frame": 1, "image_accumulation": False, "denoising": False, "upscaling": False,
            "history_policy": "Fresh process; 40 warmup frames; continuous temporal history with no resets",
            "seed_policy": capture.seed_policy(True), "clock_policy": {"paused": True, "framerate": 0, "time": 0},
            "requested_graph_options": options, "runtime_verification": receipt, "reference": reference,
            "render_script_sha256": hashlib.sha256(source).hexdigest(), "build_commit": built["commit"],
            "git_commit": git_commit, "git_dirty": git_dirty, "gpu_driver_vram": gpu, "os": platform.platform(),
            "display_transform": {"method": transform, "ev": exposure, "encoding": "sRGB"},
            "fps_playback": 30, "duration_seconds": 10, "motion_seconds": [1, 8, 1],
            "timing_boundary": "Exact /onFrameRender/gpu_time; previous frame read after current render; no image I/O in timing replay",
            "gpu_total_event": GPU_TOTAL_EVENT, "independent_repeats": 1,
            "interpretation": "Single-seed descriptive sequence; correlated frames are not independent repeats"}
        metadata["trajectory_approval_receipt"] = _json(APPROVAL_RECEIPT)
        if PREFLIGHT.exists():
            metadata["production_preflight"] = _json(PREFLIGHT)
        def prepare(directory):
            (directory / "render.py").write_bytes(source)
            run.save(directory / "trajectory.json", config)
            run.save(directory / "requested-frames.json", frames)
        def verify(directory):
            if (_json(directory / "requested-frames.json") != frames or _json(directory / "trajectory.json") != config
                    or (directory / "render.py").read_bytes() != source):
                raise ValueError("Requested formal trajectory or generated render script changed")
            artifacts = _verify_render_evidence(directory, base, options, frames, entry["adapted"], phase)
            if phase == "capture":
                paths = sorted(directory.glob("*.exr"))
                numbers = run.capture_frames(paths, SCHEDULE)
                for frame, path in sorted(zip(numbers, paths)):
                    run.inspect_hdr(path, *RESOLUTION)
                    artifacts.append(_artifact(path, directory, kind="linear_hdr", frame=frame, video_frame=frame - 41,
                                               encoding="scene-linear RGB FLOAT32 EXR"))
            else:
                if list(directory.glob("*.exr")):
                    raise ValueError("Timing replay unexpectedly exported an image")
                timing = measure.validate_timings(directory / "timings.json", SCHEDULE, drain_last_frame=True)
                rows = timing_rows(_json(directory / "timings.json"))
                run.save(directory / "gpu-frame-timings.json", rows)
                run.save(directory / "timing-validation.json", timing)
                artifacts.extend(_artifact(directory / name, directory, kind="timing")
                                 for name in ("timings.json", "gpu-frame-timings.json", "timing-validation.json"))
            if any(run.sha(ROOT / name) != expected for name, expected in hashes.items()):
                raise ValueError("Formal trajectory implementation or input changed during rendering")
            if capture.validate_runtime(runtime, method, entry["adapted"], parameters) != receipt:
                raise ValueError("Formal trajectory runtime changed during rendering")
            reference_extension_batch.recheck_view(entry, base)
            run.save(directory / "validation.json", {"status": "passed", "phase": phase,
                "trajectory_frames": 340, "captured_frames": 300 if phase == "capture" else 0,
                "rendered_frames": 340 + (phase == "timing"), "temporal_reuse": True,
                "camera_records_sha256": run.sha(directory / "trajectory-records.json"),
                "scene_state_sha256": run.sha(directory / "scene-state.json"),
                "resolved_graph_sha256": run.sha(directory / "resolved.py")})
            artifacts.append(_artifact(directory / "validation.json", directory, kind="evidence"))
            return artifacts
        with isolated_python_environment():
            return run.execute(command, output, timeout, prepare=prepare, verify=verify, metadata=metadata)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("trajectory", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--method", choices=tuple(METHODS), required=True)
    parser.add_argument("--phase", choices=("capture", "timing", "encode"), default="capture")
    parser.add_argument("--capture-output", type=Path)
    parser.add_argument("--timing-output", type=Path)
    parser.add_argument("--timeout", type=int, default=7200)
    args = vars(parser.parse_args())
    if args["phase"] != "encode" and args["runtime"] is None:
        parser.error("--runtime is required for rendering phases")
    print(launch(args.pop("trajectory"), args.pop("output"), args.pop("runtime"), args.pop("method"), **args))


if __name__ == "__main__":
    main()
