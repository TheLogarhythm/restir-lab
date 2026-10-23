"""Export reference-free method images and optional comparison videos."""
import math
from pathlib import Path
import shutil
import tempfile
from rtxdi_common import sha
from experiment.artifacts import save_json
from experiment.images import preview_rgb, read_pfm
from . import pdf_artifacts


def export_raw_condition(output, off_dir, on_dir, *, exposure_ev=0., write_videos=True,
                         expected_resolution=(1920, 1080), expected_frames=None, fps=30,
                         check_budget=lambda: None):
    """Export seed-one visual comparisons without claiming reference accuracy."""
    check_budget()
    if type(fps) is not int or fps != 30 or not math.isfinite(exposure_ev):
        raise ValueError("Visual comparisons require 30 FPS and finite shared exposure")
    output = Path(output).resolve()
    if output.exists():
        raise ValueError(f"Refusing to overwrite existing visual comparison: {output}")
    sources = {"pdf-off": pdf_artifacts._captures(off_dir), "pdf-on": pdf_artifacts._captures(on_dir)}
    frames = sorted(sources["pdf-off"])
    if set(frames) != set(sources["pdf-on"]):
        raise ValueError("PDF off/on capture frame alignment mismatch")
    if expected_frames is not None and (len(set(expected_frames)) != len(expected_frames)
            or sorted(expected_frames) != frames):
        raise ValueError("Capture frames do not match expected_frames")
    if write_videos and any(b != a + 1 for a, b in zip(frames, frames[1:])):
        raise ValueError("Continuous visual comparison videos require consecutive captures")
    alignment = pdf_artifacts._config_alignment(off_dir, on_dir)
    if not alignment["checked"]:
        raise ValueError("Method visual comparisons require aligned seed-one run configs")
    width, height = expected_resolution
    if any(type(value) is not int or value < 1 for value in (width, height)):
        raise ValueError("Expected resolution must contain positive integer width,height")
    provenance = {}
    for method, paths in sources.items():
        provenance[method] = {}
        for frame, path in sorted(paths.items()):
            check_budget()
            if read_pfm(path).shape != (height, width, 3):
                raise ValueError(f"Image resolution mismatch for {path}")
            provenance[method][str(frame)] = {"path": str(path.resolve()), "sha256": sha(path)}
    executable = shutil.which("ffmpeg") if write_videos else None
    if write_videos and not executable:
        raise ValueError("FFmpeg is required for visual comparison videos")
    from PIL import Image
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    writer = None
    try:
        if write_videos:
            (stage / "videos").mkdir()
            writer = pdf_artifacts._VideoWriter(stage / "videos/comparison.mp4", (1920, 1080), fps, executable)
        selected = {frames[-1], *(frame for frame in pdf_artifacts.KEYFRAMES if frame in frames)}
        for frame in frames:
            check_budget()
            display = [Image.fromarray(preview_rgb(read_pfm(sources[method][frame]), exposure_ev))
                       for method in ("pdf-off", "pdf-on")]
            footer = f"Reference pending; visual comparison only | {exposure_ev:g} EV | frame {frame}"
            for method, image in zip(("pdf-off", "pdf-on"), display):
                pdf_artifacts._save_rgb(stage / f"frames/{method}/frame-{frame:04d}.png", image)
            if frame in selected:
                pdf_artifacts._save_rgb(stage / f"panels/frame-{frame:04d}.png",
                    pdf_artifacts._panel(display, ["PDF off", "PDF on"], footer=footer))
            if writer is not None:
                writer.append(pdf_artifacts._presentation(display, ["PDF off", "PDF on"], frame, footer))
        if writer is not None:
            writer.close()
            writer = None
        receipt = {"schema_version": 1, "kind": "method_visual_comparison", "references_accepted": False,
            "seed": 1, "frames": frames, "source_resolution": [width, height], "fps": fps,
            "logical_fps_not_performance": True, "display_transform": "Reinhard + sRGB",
            "exposure_ev": exposure_ev, "config_alignment": alignment, "inputs": provenance,
            "videos": ["videos/comparison.mp4"] if write_videos else []}
        save_json(stage / "manifest.json", receipt)
        check_budget()
        stage.rename(output)
        return receipt
    finally:
        if writer is not None and not writer.log.closed:
            writer.close(abort=True)
        if stage.exists():
            shutil.rmtree(stage)
