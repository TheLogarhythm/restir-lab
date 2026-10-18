"""Export accepted-reference PDF comparisons without running the renderer.

CLI: ``python scripts/analysis/pdf_artifacts.py --manifest condition.json --output DIR``.
The input JSON supplies off_dir, on_dir, references (frame -> PFM path), the
explicit references_accepted flag, and optional keyword arguments documented by
export_condition. Relative input paths resolve beside the input JSON. No seed
selection, reference acceptance, pilot scale estimation, or ROI selection occurs
here. Native HDR files remain the quantitative source of record.
"""
import argparse
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

RUN_SCRIPTS = Path(__file__).resolve().parents[1] / "run"
if str(RUN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUN_SCRIPTS))
from experiment.images import preview_rgb, read_pfm
from experiment.reference import metrics as spatial_metrics

METHODS = ("pdf-off", "pdf-on")
KEYFRAMES = (32, 33, 64, 65, 96)
FRAME_PATTERN = re.compile(r"frame-(\d+)\.pfm(?:\.gz)?$")
MAP_LABELS = {"smape": "SMAPE", "signed_relative": "Signed relative residual", "trmae": "TRMAE"}
METRIC_DEFINITIONS = {
    "smape": "100 * mean(abs(Y(I)-Y(R)) / (abs(Y(I))+abs(Y(R))+1e-4)); no factor two",
    "signed_relative": "100 * (Y(I)-Y(R)) / (abs(Y(R))+1e-4); unclipped numeric values",
    "trmae": "mean(RGB_L1((I_t-I_previous)-(R_t-R_previous)) / (RGB_L1(R_t-R_previous)+0.01)) / 3",
    "luminance": "linear RGB weights (0.2126, 0.7152, 0.0722)",
    "rmae": "mean(abs(I-R)) / (mean(abs(R))+1e-12), linear RGB",
    "nrmse": "sqrt(mean((I-R)^2) / (mean(R^2)+1e-12)), linear RGB",
}


def map_scale(metric, temporal_scale=None):
    """Return the shared display interval, palette, and units for a metric."""
    if metric == "smape":
        return (0., 100.), "magma", "%"
    if metric == "signed_relative":
        return (-50., 50.), "bwr", "%"
    if metric == "trmae" and temporal_scale is not None:
        low, high = map(float, temporal_scale)
        if low == 0 and math.isfinite(high) and high > 0:
            return (low, high), "magma", "TRMAE"
    raise ValueError("TRMAE requires a finite positive pilot temporal_scale=(0, maximum)")


def colorize_map(values, metric, temporal_scale=None):
    """Color an unclipped map using fixed limits; return RGB and clip fraction."""
    from matplotlib import colormaps
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 2 or not values.size or not np.isfinite(values).all():
        raise ValueError("Error maps must be finite nonempty two-dimensional arrays")
    (low, high), palette, _ = map_scale(metric, temporal_scale)
    clipped = float(np.mean((values < low) | (values > high)))
    normalized = np.clip((values - low) / (high - low), 0, 1)
    rgb = np.rint(colormaps[palette](normalized)[..., :3] * 255).astype(np.uint8)
    return rgb, clipped


def _captures(directory):
    result = {}
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise ValueError(f"Missing capture directory: {directory}")
    for path in directory.iterdir():
        match = FRAME_PATTERN.fullmatch(path.name)
        if match:
            frame = int(match.group(1))
            if frame < 1 or frame in result:
                raise ValueError(f"Invalid or duplicate capture frame: {path}")
            result[frame] = path
    if not result:
        raise ValueError(f"No PFM captures in {directory}")
    return result


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _config_alignment(off_dir, on_dir, expected_seed=1):
    """Allow only the intended PDF toggle to differ between explicitly paired runs."""
    paths = [Path(directory) / "config.json" for directory in (off_dir, on_dir)]
    if not any(path.exists() for path in paths):
        return {"checked": False, "reason": "Explicit captures supplied without run configs"}
    if not all(path.is_file() for path in paths):
        raise ValueError("Both PDF runs require config.json for alignment")
    configs = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    for config, enabled in zip(configs, (False, True)):
        if config.get("seed") != expected_seed:
            raise ValueError(f"Artifact comparisons require explicitly selected seed {expected_seed}")
        if config.get("definition", {}).get("pdf_similarity", False) is not enabled:
            raise ValueError("Expected PDF off/on configurations in that order")
    comparable = copy.deepcopy(configs)
    for config in comparable:
        config["definition"].pop("pdf_similarity", None)
        arguments = config.get("arguments", {})
        arguments.pop("restirDI.pdfSimilarity.enabled", None)
    if comparable[0] != comparable[1]:
        raise ValueError("PDF off/on config alignment mismatch beyond PDF toggle")
    resolved = [Path(directory) / "resolved.json" for directory in (off_dir, on_dir)]
    if any(path.exists() for path in resolved):
        if not all(path.is_file() for path in resolved):
            raise ValueError("Both runs require resolved.json for resolved-state alignment")
        states = [json.loads(path.read_text()) for path in resolved]
        for state, enabled in zip(states, (False, True)):
            if state.get("pdf_similarity", False) is not enabled:
                raise ValueError("Resolved-state PDF toggle differs from selected method")
            state.pop("pdf_similarity", None)
        if states[0] != states[1]:
            raise ValueError("PDF off/on resolved-state alignment mismatch")
    return {"checked": True, "seed": expected_seed,
            "config_sha256": [_hash(path) for path in paths]}


def _validate_rois(rois, width, height):
    result, names = [], set()
    for roi in rois:
        if set(roi) != {"name", "x", "y", "width", "height"}:
            raise ValueError("Each preselected ROI needs name,x,y,width,height")
        name = roi["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name) or name in names:
            raise ValueError("ROI names must be unique safe path components")
        x, y, w, h = (roi[key] for key in ("x", "y", "width", "height"))
        if any(type(value) is not int for value in (x, y, w, h)) or (
                x < 0 or y < 0 or w < 1 or h < 1 or x + w > width or y + h > height):
            raise ValueError("Preselected ROI lies outside the native image")
        names.add(name)
        result.append(dict(roi))
    return result


def _panel(images, labels, *, footer="", metric=None, temporal_scale=None):
    """Use identical native tile dimensions and one shared colorbar."""
    width, height = images[0].size
    if any(image.size != (width, height) for image in images):
        raise ValueError("Panel tiles must have identical dimensions")
    font_size = max(10, min(36, width // 60))
    font = ImageFont.load_default(size=font_size)
    title_height = max(28, font_size + 18)
    footer_height = max(58, 3 * font_size + 30) if metric else max(30, font_size + 18)
    canvas = Image.new("RGB", (width * len(images), height + title_height + footer_height), "#17191e")
    draw = ImageDraw.Draw(canvas)
    for index, (image, label) in enumerate(zip(images, labels)):
        x = index * width
        draw.text((x + 4, 7), label, fill="white", font=font)
        canvas.paste(image, (x, title_height))
    y = title_height + height
    if metric:
        (low, high), _, unit = map_scale(metric, temporal_scale)
        # Even tiny synthetic panels have a valid common bar, without stretching images.
        bar_width = max(1, canvas.width - 8)
        gradient = np.linspace(low, high, bar_width)[None, :]
        bar, _ = colorize_map(gradient, metric, temporal_scale)
        canvas.paste(Image.fromarray(bar).resize((bar_width, font_size)), (4, y + 4))
        draw.text((4, y + font_size + 10), f"{MAP_LABELS[metric]}: {low:g} to {high:g} {unit}; display clipping only", fill="white", font=font)
        y += 2 * font_size + 17
    draw.text((4, y + 5), footer, fill="white", font=font)
    return canvas


def _save_rgb(path, image):
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _presentation(images, labels, frame, footer, *, metric=None, temporal_scale=None):
    """1920x1080 video canvas; native exports never pass through this resize."""
    canvas = Image.new("RGB", (1920, 1080), "#17191e")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=22)
    if metric:
        cells = ((0, 220, 960, 570), (960, 220, 960, 570))
    else:
        cells = ((0, 0, 960, 540), (960, 0, 960, 540), (0, 540, 960, 540))
    for image, label, (x, y, width, height) in zip(images, labels, cells):
        scale = min(width / image.width, (height - 36) / image.height)
        resized = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                               Image.Resampling.LANCZOS)
        canvas.paste(resized, (x + (width - resized.width) // 2, y + 36))
        draw.text((x + 12, y + 9), f"{label} | frame {frame} | presentation scale {scale:g}x", fill="white", font=font)
    if metric:
        (low, high), _, unit = map_scale(metric, temporal_scale)
        bar, _ = colorize_map(np.linspace(low, high, 1800)[None, :], metric, temporal_scale)
        canvas.paste(Image.fromarray(bar).resize((1800, 24)), (60, 870))
        draw.text((60, 908), f"{metric.upper()} fixed {low:g} to {high:g} {unit}; display clipping only", fill="white", font=font)
        draw.text((60, 950), footer, fill="white", font=font)
    else:
        draw.text((980, 570), f"Frame {frame} | logical playback 30 FPS", fill="white", font=font)
        draw.text((980, 610), footer, fill="white", font=font)
        draw.text((980, 650), "Native HDR and PNG frames retained at original resolution", fill="white", font=font)
    return canvas


class _VideoWriter:
    """A bounded-memory FFmpeg pipe with checked completion and child cleanup."""
    def __init__(self, path, size, fps, executable):
        self.path = Path(path)
        self.log = tempfile.TemporaryFile()
        width, height = size
        self.size = size
        self.command = [executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f"{width}x{height}",
            "-framerate", str(fps), "-i", "pipe:0", "-an", "-c:v", "libx264",
            "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)]
        self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.log)

    def append(self, image):
        if image.size != self.size:
            raise ValueError("Video frame dimensions changed")
        try:
            self.process.stdin.write(np.asarray(image.convert("RGB"), dtype=np.uint8).tobytes())
        except (BrokenPipeError, OSError) as exc:
            self.close(abort=True)
            raise RuntimeError(f"FFmpeg pipe failed for {self.path.name}") from exc

    def close(self, abort=False):
        if self.process.stdin and not self.process.stdin.closed:
            try:
                self.process.stdin.close()
            except (BrokenPipeError, OSError):
                abort = True
        if abort and self.process.poll() is None:
            self.process.terminate()
        try:
            status = self.process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
            status = -1
        self.log.seek(0)
        detail = self.log.read().decode("utf-8", errors="replace")[-4000:]
        self.log.close()
        if status and not abort:
            raise RuntimeError(f"FFmpeg failed ({status}): {detail}")


def _phase(frame):
    return "startup" if frame <= 32 else "motion-change" if frame <= 64 else "recovery"


def export_condition(output, off_dir, on_dir, references_mapping, *, references_accepted,
                     fps=30, rois=(), temporal_scale=None, exposure_ev=0., write_videos=True,
                     expected_resolution=(1920, 1080), expected_frames=None):
    """Export an explicitly selected seed-one pair after reference acceptance.

    Input frame sets must match exactly. Consecutive captures receive adjacent
    TRMAE maps; gaps never create temporal pairs. temporal_scale=(0, pilot_max)
    must already be frozen whenever an adjacent pair exists. All PFM inputs are
    validated before any output is created. A fresh output directory is required.
    PNGs/maps retain native pixels; comparison videos alone resize for presentation.
    """
    if references_accepted is not True:
        raise ValueError("References must be explicitly accepted before artifact export")
    if fps != 30 or isinstance(fps, bool):
        raise ValueError("Controlled comparison videos require logical 30 FPS")
    if not math.isfinite(exposure_ev):
        raise ValueError("Exposure must be finite and shared")
    output = Path(output).resolve()
    if output.exists():
        raise ValueError(f"Refusing to overwrite existing artifact output: {output}")
    sources = {"pdf-off": _captures(off_dir), "pdf-on": _captures(on_dir)}
    frames = sorted(sources["pdf-off"])
    if set(frames) != set(sources["pdf-on"]):
        raise ValueError("PDF off/on capture frame alignment mismatch")
    if expected_frames is not None and (len(set(expected_frames)) != len(expected_frames)
            or sorted(expected_frames) != frames):
        raise ValueError("Capture frames do not match expected_frames")
    if any(type(frame) is not int or frame < 1 for frame in references_mapping):
        raise ValueError("Reference mapping keys must be positive integer frames")
    if set(references_mapping) != set(frames):
        raise ValueError("Reference frame alignment mismatch: provide exactly one reference per captured frame")
    sources["reference"] = {frame: Path(path).resolve() for frame, path in references_mapping.items()}
    temporal_pairs = [[previous, current] for previous, current in zip(frames, frames[1:]) if current == previous + 1]
    if temporal_pairs:
        map_scale("trmae", temporal_scale)
    if write_videos and len(temporal_pairs) != len(frames) - 1:
        raise ValueError("Continuous videos require consecutive captures; use write_videos=False for static captures")
    alignment = _config_alignment(off_dir, on_dir)
    width, height = expected_resolution
    if any(type(value) is not int or value < 1 for value in (width, height)):
        raise ValueError("Expected resolution must contain positive integer width,height")
    rois = _validate_rois(rois, width, height)
    provenance, checked = {}, set()
    for method, paths in sources.items():
        provenance[method] = {}
        for frame, path in sorted(paths.items()):
            if not path.is_file():
                raise ValueError(f"Missing reference/capture image: {path}")
            if path not in checked:
                image = read_pfm(path)
                if image.shape != (height, width, 3):
                    raise ValueError(f"Image resolution/alignment mismatch for {path}: {image.shape}")
                checked.add(path)
            provenance[method][str(frame)] = {"path": str(path), "sha256": _hash(path)}
    executable = shutil.which("ffmpeg") if write_videos else None
    if write_videos and not executable:
        raise ValueError("FFmpeg is required for video export; install ffmpeg or set write_videos=False")
    from experiment.error_metrics import smape_map, signed_relative_map, trmae_map
    # Create only after the fail-closed preflight; rename an isolated staging directory on success.
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    writers, rows, temporal_keyframes = {}, [], {}
    settings = {metric: {"range": list(map_scale(metric, temporal_scale)[0]),
        "palette": map_scale(metric, temporal_scale)[1], "units": map_scale(metric, temporal_scale)[2]}
        for metric in (("smape", "signed_relative", "trmae") if temporal_pairs else ("smape", "signed_relative"))}
    try:
        if write_videos:
            (stage / "videos").mkdir()
            for name in ("comparison", "smape", "reference"):
                writers[name] = _VideoWriter(stage / f"videos/{name}.mp4", (1920, 1080), fps, executable)
        previous, previous_frame = {}, None
        selected = {128} if 128 in frames else {frames[-1]}
        selected.update(frame for frame in KEYFRAMES if frame in frames and temporal_pairs)
        for frame in frames:
            images = {method: read_pfm(paths[frame]) for method, paths in sources.items()}
            display = {method: Image.fromarray(preview_rgb(image, exposure_ev)) for method, image in images.items()}
            maps, colored = {}, {}
            for method in METHODS:
                values = {"smape": smape_map(images[method], images["reference"]),
                          "signed_relative": signed_relative_map(images[method], images["reference"])}
                if previous_frame is not None and frame == previous_frame + 1:
                    values["trmae"] = trmae_map(images[method], previous[method], images["reference"], previous["reference"])
                maps[method], colored[method] = values, {}
                standard = spatial_metrics(images[method], images["reference"])
                row = {"frame": frame, "previous_frame": previous_frame if "trmae" in values else None,
                    "phase": _phase(frame), "method": method, "smape": float(np.mean(values["smape"])),
                    "rmae": standard["rmae"], "nrmse": standard["nrmse"],
                    "trmae": float(np.mean(values["trmae"])) if "trmae" in values else None}
                for metric, value in values.items():
                    rgb, fraction = colorize_map(value, metric, temporal_scale)
                    colored[method][metric] = Image.fromarray(rgb)
                    row[f"{'signed' if metric == 'signed_relative' else metric}_clipped_fraction"] = fraction
                rows.append(row)
                directory = stage / f"maps/{method}"
                directory.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(directory / f"frame-{frame:04d}.npz", **values)
            for method, image in display.items():
                _save_rgb(stage / f"frames/{method}/frame-{frame:04d}.png", image)
            if frame in selected:
                footer = f"Frame {frame}; fixed exposure {exposure_ev:g} EV; native {width}x{height}"
                _save_rgb(stage / f"panels/frame-{frame:04d}-rendered.png", _panel(
                    [display[key] for key in ("reference", *METHODS)], ["Reference", "PDF off", "PDF on"], footer=footer))
                for metric in ("smape", "signed_relative", "trmae"):
                    if metric not in maps["pdf-off"]:
                        continue
                    pair_label = f"{previous_frame} -> {frame}" if metric == "trmae" else f"frame {frame}"
                    _save_rgb(stage / f"panels/frame-{frame:04d}-{metric}.png", _panel(
                        [colored[method][metric] for method in METHODS], [f"PDF off | {pair_label}", f"PDF on | {pair_label}"],
                        footer=footer, metric=metric, temporal_scale=temporal_scale))
                    if metric == "trmae" and frame in KEYFRAMES:
                        temporal_keyframes[str(frame)] = {"pair": [previous_frame, frame], "label": pair_label,
                            "panel": f"panels/frame-{frame:04d}-trmae.png"}
                for roi in rois:
                    box = (roi["x"], roi["y"], roi["x"] + roi["width"], roi["y"] + roi["height"])
                    for method, image in display.items():
                        _save_rgb(stage / f"rois/{roi['name']}/{method}/frame-{frame:04d}.png", image.crop(box))
                    for metric in ("smape", "signed_relative", "trmae"):
                        if metric not in maps["pdf-off"]:
                            continue
                        _save_rgb(stage / f"rois/{roi['name']}/frame-{frame:04d}-{metric}.png", _panel(
                            [colored[method][metric].crop(box) for method in METHODS], ["PDF off", "PDF on"],
                            footer=f"Preselected ROI: {roi['name']} | {footer}", metric=metric, temporal_scale=temporal_scale))
            if writers:
                footer = f"Fixed exposure {exposure_ev:g} EV; frame {frame}; {_phase(frame)}"
                writers["comparison"].append(_presentation([display[key] for key in ("reference", *METHODS)],
                    ["Reference", "PDF off", "PDF on"], frame, footer))
                writers["smape"].append(_presentation([colored[method]["smape"] for method in METHODS],
                    ["PDF off", "PDF on"], frame, footer, metric="smape"))
                reference_video = Image.new("RGB", (1920, 1080), "black")
                if display["reference"].size != (1920, 1080):
                    reference_video.paste(display["reference"].resize((1920, 1080), Image.Resampling.LANCZOS))
                else:
                    reference_video.paste(display["reference"])
                reference_draw = ImageDraw.Draw(reference_video)
                reference_draw.rectangle((0, 0, 1100, 42), fill="#17191e")
                reference_draw.text((12, 9), f"Accepted reference | frame {frame} | {fps} FPS | {exposure_ev:g} EV", fill="white", font=ImageFont.load_default(size=24))
                writers["reference"].append(reference_video)
            previous, previous_frame = images, frame
        for writer in writers.values():
            writer.close()
        writers.clear()
        fieldnames = ["frame", "previous_frame", "phase", "method", "smape", "rmae", "nrmse", "trmae",
                      "smape_clipped_fraction", "signed_clipped_fraction", "trmae_clipped_fraction"]
        with (stage / "frame-metrics.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        manifest = {"schema_version": 1, "references_accepted": True, "seed": 1,
            "frames": frames, "temporal_pairs": temporal_pairs, "temporal_keyframes": temporal_keyframes,
            "source_resolution": [width, height], "fps": fps, "logical_fps_not_performance": True,
            "display_transform": "Reinhard + sRGB", "exposure_ev": exposure_ev, "rois": rois,
            "scales": settings, "metric_definitions": METRIC_DEFINITIONS,
            "temporal_scale_source": "Caller-supplied frozen pilot interval" if temporal_pairs else None,
            "numeric_maps": "Unclipped float64 NPZ; map values precede display clipping",
            "video_resolution": [1920, 1080] if write_videos else None,
            "video_layout": "comparison: 2x2, three synchronized images; SMAPE: shared scale, two methods",
            "video_resize": "Presentation only; native HDR source and native PNG exports retained",
            "config_alignment": alignment, "inputs": provenance, "frame_metrics": rows,
            "videos": [f"videos/{name}.mp4" for name in ("comparison", "smape", "reference")] if write_videos else []}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        stage.rename(output)
        return manifest
    finally:
        for writer in writers.values():
            if not writer.log.closed:
                writer.close(abort=True)
        if stage.exists():
            shutil.rmtree(stage)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path, help="Explicit condition inputs/settings JSON")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    config = json.loads(args.manifest.read_text(encoding="utf-8"))
    base = args.manifest.resolve().parent
    def source_path(value):
        path = Path(value)
        return path if path.is_absolute() else base / path
    off_dir, on_dir = (source_path(config.pop(key)) for key in ("off_dir", "on_dir"))
    refs = {int(frame): source_path(path) for frame, path in config.pop("references").items()}
    export_condition(args.output, off_dir, on_dir, refs, **config)
    print(f"Exported accepted-reference artifacts to {args.output.resolve()}")


if __name__ == "__main__":
    main()
