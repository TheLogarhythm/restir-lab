"""Render bounded ordinary-PT trajectory previews; never a method-comparison entry point."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

from . import camera_trajectory, trajectory_render_script as trajectory_script, spatial_capture as capture
from . import spatial_experiment_config as settings, cgns_pt_six_view_smoke as views
from . import reference_extension_batch, run
from .process_utils import check_renderer_idle, exclusive_operation
from .adapted_reference_runner import isolated_python_environment
from . import reference_extension_gallery as gallery

ROOT = Path(__file__).resolve().parents[2]
CONTACT_FRAMES = [41, 71, 131, 191, 251, 311, 340]


def render_script(scene, frames, output, options, *, adapted=False, captures=None):
    """Generate a bounded preview using the shared trajectory schedule."""
    return trajectory_script.build_script(scene, frames, output, options,
        adapted=adapted, captures=captures)


# Preserve callers that imported camera-evidence verification from the preview.
verify_camera_records = trajectory_script.verify_camera_records


def make_media(output, config, files, *, exposure_ev, full):
    """Postprocess only: clean linear EXRs are retained beside display artifacts."""
    from PIL import Image, ImageDraw, ImageFont
    output = Path(output)
    display = output / "display"
    display.mkdir(exist_ok=False)
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf"
    font = ImageFont.truetype(str(font_path), 16) if font_path.exists() else ImageFont.load_default()
    images = {}
    for frame, path in sorted(files.items()):
        rgb = run.inspect_hdr(path, config["width"], config["height"])
        picture = Image.fromarray(gallery.display(rgb, config.get("display_method", "reinhard"), exposure_ev))
        draw = ImageDraw.Draw(picture)
        label = f"{config['id']} | PT preview | 30 FPS playback | {(frame - 41) / 30:.2f} s"
        draw.rectangle((0, 0, picture.width, 25), fill=(0, 0, 0))
        draw.text((8, 4), label, font=font, fill="white")
        picture.save(display / f"frame-{frame - 41:03d}.png")
        if frame in CONTACT_FRAMES:
            images[frame] = picture
    contact = Image.new("RGB", (config["width"] * 3, (config["height"] + 28) * 2), (20, 20, 20))
    draw = ImageDraw.Draw(contact)
    for index, frame in enumerate(CONTACT_FRAMES[1:]):
        x, y = (index % 3) * config["width"], (index // 3) * (config["height"] + 28)
        contact.paste(images[frame], (x, y + 28))
        draw.text((x + 8, y + 5), f"{(frame - 41) / 30:.2f} s", font=font, fill="white")
    contact.save(output / "contact-sheet.jpg", quality=94)
    artifacts = ["contact-sheet.jpg"]
    if full:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise RuntimeError("ffmpeg required to encode the preview")
        command = [ffmpeg, "-nostdin", "-v", "error", "-n", "-framerate", "30",
                   "-i", str(display / "frame-%03d.png"), "-frames:v", "300",
                   "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                   "-movflags", "+faststart", str(output / "preview.mp4")]
        subprocess.run(command, check=True, timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        artifacts.append("preview.mp4")
    return {"display_transform": config.get("display_method", "reinhard") + " then sRGB", "exposure_ev": exposure_ev,
            "watermark": "Postprocessed label only; no measured rendering FPS in previews.",
            "paths": artifacts}


def launch(trajectory_path, output, runtime, *, width=640, height=360,
           contact_only=False, exposure_ev=None, seed_offset=0, timeout=1800):
    if (type(width) is not int or type(height) is not int or width % 2 or height % 2
            or not 64 <= width <= 640 or not 32 <= height <= 360):
        raise ValueError("Preview resolution must be even and at most 640x360")
    if exposure_ev is not None and (not math.isfinite(exposure_ev) or not -10 <= exposure_ev <= 10):
        raise ValueError("Invalid preview exposure")
    if not 0 < timeout <= 3600:
        raise ValueError("Preview timeout exceeds one hour")
    trajectory_path = Path(trajectory_path).resolve(strict=True)
    config = camera_trajectory.load(trajectory_path)
    frames = camera_trajectory.sample_frames(config, seed_offset=seed_offset)
    output, runtime = Path(output).resolve(), Path(runtime).resolve(strict=True)
    if output.exists() or not output.is_relative_to((ROOT / "runs").resolve()):
        raise ValueError("Preview requires a new output directory under runs")
    if os.environ.get("FALCOR_DEVMODE") == "1":
        raise ValueError("FALCOR_DEVMODE would override isolated shaders")
    scene_config_path = (ROOT / config["scene_config"]).resolve(strict=True)
    if not scene_config_path.is_relative_to(ROOT):
        raise ValueError("Scene configuration escapes workspace")
    base = views.load_config(scene_config_path)
    display_method, scene_exposure = gallery.RECIPES[(base["scene_id"], base["view_id"])]
    exposure_ev = scene_exposure if exposure_ev is None else exposure_ev
    entry = views.frozen_views()[(base["scene_id"], base["view_id"])]
    experiment = settings.load_config()
    options = capture.graph_options("baseline", experiment, temporal_reuse=True)
    captures = CONTACT_FRAMES if contact_only else list(trajectory_script.CAPTURE_FRAMES)
    source = render_script(ROOT / base["scene_source"], frames, output, options,
                           adapted=entry["adapted"], captures=captures).encode("utf8")
    command = [str(runtime / "Mogwai.exe"), "--device-type", "d3d12", "--width", str(width),
               "--height", str(height), "--script", str(output / "render.py"), "--headless"]
    with exclusive_operation(ROOT / "build/falcor/.operation.lock"):
        check_renderer_idle()
        reference_extension_batch.recheck_view(entry, base)
        receipt = capture.validate_runtime(runtime, "baseline", entry["adapted"])
        paths = {*capture.dependency_files("baseline"), Path(__file__), Path(camera_trajectory.__file__),
                 Path(trajectory_script.__file__),
                 trajectory_path, scene_config_path, settings.DEFAULT_CONFIG}
        hashes = {Path(path).resolve().relative_to(ROOT).as_posix(): run.sha(path) for path in paths}
        def prepare(directory):
            (directory / "render.py").write_bytes(source)
            run.save(directory / "trajectory.json", config)
            run.save(directory / "requested-frames.json", frames)
        def verify(directory):
            records = json.loads((directory / "trajectory-records.json").read_text(encoding="utf8"))
            verify_camera_records(records, frames)
            paths = sorted(directory.glob("capture.PathTracer.color.*.exr"))
            numbers = run.capture_frames(paths, captures)
            files = dict(zip(numbers, paths))
            artifacts = [{"frame": f, "path": p.name, "sha256": run.sha(p)} for f, p in sorted(files.items())]
            for path in files.values():
                run.inspect_hdr(path, width, height)
            if any(run.sha(ROOT / name) != digest for name, digest in hashes.items()):
                raise ValueError("Preview input files changed during rendering")
            if (directory / "render.py").read_bytes() != source:
                raise ValueError("Preview script changed during rendering")
            if capture.validate_runtime(runtime, "baseline", entry["adapted"]) != receipt:
                raise ValueError("Preview runtime changed")
            reference_extension_batch.recheck_view(entry, base)
            media = make_media(directory, {"id": config["id"], "width": width, "height": height,
                                           "display_method": display_method}, files,
                               exposure_ev=exposure_ev, full=not contact_only)
            run.save(directory / "preview-summary.json", {
                "status": "passed", "purpose": "Route approval only; no formal comparison.",
                "trajectory_id": config["id"], "resolution": [width, height],
                "rendered_frames": 340, "captured_frames": len(captures), "warmup_frames": 40,
                "method": "ordinary spatial reuse", "temporal": True,
                "fps_playback": 30, "duration_seconds": 10, "seed_offset": seed_offset,
                "path_length_scene_units": frames[-1]["distance_scene_units"],
                "units": config["unit_basis"], "media": media,
                "artifacts": artifacts})
            return artifacts
        with isolated_python_environment():
            return run.execute(command, output, timeout, prepare=prepare, verify=verify, metadata={
                "kind": "camera_trajectory_approval_preview", "trajectory_id": config["id"],
                "resolution": [width, height], "method": "baseline", "temporal_reuse": True,
                "scene_id": base["scene_id"], "scene_config": config["scene_config"],
                "asset_sha256": entry["asset_sha256"], "requested_graph_options": options,
                "warmup_frames": 40, "captured_frames": captures, "runtime_verification": receipt,
                "source_sha256": hashes, "render_script_sha256": hashlib.sha256(source).hexdigest(),
                "formal_comparison": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("trajectory", "output", "runtime"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument("--contact-only", action="store_true")
    parser.add_argument("--exposure-ev", type=float)
    parser.add_argument("--seed-offset", type=int, default=0)
    args = vars(parser.parse_args())
    trajectory = args.pop("trajectory")
    print(launch(trajectory, **args))


if __name__ == "__main__":
    main()
