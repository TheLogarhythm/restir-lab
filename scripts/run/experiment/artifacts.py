"""Raw image conversion, captured-reservoir statistics and run-output validation."""
import csv
from rtxdi_common import sha
from pathlib import Path
import json
import math
import numpy as np
from PIL import Image, PngImagePlugin
from .config import LOCAL_SAMPLING_MODES, MODE_VALUES
from .images import write_pfm, preview_rgb

def save_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)

def reservoir_stats(path, width, height):
    # Pinned RTXDI v3.1 packed layout; 16x16 tiled storage, one shading array.
    data = np.fromfile(path, dtype="<u4").reshape(-1, 6)
    y, x = np.indices((height, width))
    row_pitch = ((width + 15) // 16) * 256
    address = (y // 16) * row_pitch + (x // 16) * 256 + (y % 16) * 16 + x % 16
    pixels = data[address]
    valid = pixels[..., 0] != 0
    counts = (pixels[..., 2] >> 18) & 16383
    values = counts[valid]
    return {"valid_reservoir_fraction": float(valid.mean()),
            "M_mean_valid": float(values.mean()) if values.size else 0,
            "M_max_valid": int(values.max()) if values.size else 0,
            "M_p50_valid": float(np.median(values)) if values.size else 0,
            "M_p95_valid": float(np.percentile(values, 95)) if values.size else 0}


def finalize_outputs(output, config):
    validate_run_outputs(output, config)
    records = []
    temporary_files = []
    for frame in config["frames"]:
        if not frame["capture"]:
            continue
        stem = output / f"frame-{frame['frame']:04d}"
        reference = bool(config.get("reference"))
        raw = stem.with_suffix(".rgba32f" if reference else ".rgba16f")
        rgb = np.fromfile(raw, dtype="<f4" if reference else "<f2").reshape(config["height"], config["width"], 4)[..., :3].astype("<f4")
        if not np.isfinite(rgb).all():
            raise RuntimeError(f"Invalid or empty HDR capture: {raw.name}")
        write_pfm(stem.with_suffix(".pfm.gz"), rgb)
        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add(b"sRGB", b"\x00")
        pnginfo.add_text("Display transform", json.dumps(config["preview"], sort_keys=True))
        Image.fromarray(preview_rgb(rgb, config["preview"]["exposure_ev"])).save(stem.with_suffix(".png"), pnginfo=pnginfo)
        record = {"frame": frame["frame"], "mean_rgb": float(rgb.mean()),
                  "max_rgb": float(rgb.max()), "negative_fraction": float((rgb < 0).mean()),
                  "all_black": bool(np.all(rgb == 0)),
                  "image_sha256": sha(stem.with_suffix(".pfm.gz"))}
        reservoir = stem.with_suffix(".reservoir")
        if config["diagnostics"]:
            record.update(reservoir_stats(reservoir, config["width"], config["height"]))
            temporary_files.append(reservoir)
        records.append(record)
        temporary_files.append(raw)
    save_json(output / "captures.json", records)
    for path in temporary_files:
        path.unlink()
    return records


def validate_run_outputs(output, config):
    """Check runtime settings and frame timings before converting or deleting captures."""
    with (output / "timings.csv").open(newline="") as stream:
        timings = list(csv.DictReader(stream))
    if len(timings) != len(config["frames"]) or [int(r["frame"]) for r in timings] != [f["frame"] for f in config["frames"]]:
        raise RuntimeError("Missing or mislabelled GPU timings")
    for row, frame in zip(timings, config["frames"]):
        if any(int(row[column]) != int(frame[key]) for column, key in (
                ("sampling_frame", "sampling_frame"), ("capture", "capture"), ("history_reset", "reset"))):
            raise RuntimeError("Recorded frame sequence differs from requested sequence")
    if any(not math.isfinite(float(value)) or float(value) < 0
           for row in timings for key, value in row.items() if key.endswith("_ms")) or any(
           float(row["gpu_ms"]) <= 0 for row in timings):
        raise RuntimeError("Invalid GPU frame timing")
    resolved = json.loads((output / "resolved.json").read_text())
    if bool(resolved.get("pdf_similarity", False)) != config["definition"].get("pdf_similarity", False):
        raise RuntimeError("Resolved PDF similarity differs from requested mode")
    if config.get("reference"):
        if resolved.get("estimator") != "conventional_light_sampling" or resolved.get("source_format") != "RGBA32_FLOAT accumulated reference":
            raise RuntimeError("Reference estimator/precision differs from requested mode")
        if any(float(row[key + "_ms"]) != 0 for row in timings for key in ("initial", "temporal", "spatial", "presample_lights", "presample_environment")):
            raise RuntimeError("Reference unexpectedly executed resampling/presampling")
    if resolved["mode"] != MODE_VALUES[config["mode"]]:
        raise RuntimeError("Resolved reuse mode differs from requested mode")
    if any(resolved[key] for key in ("denoiser", "aa", "checkerboard", "pixel_jitter")):
        raise RuntimeError("A disabled reconstruction feature was enabled")
    active = {"temporal": config["mode"] in ("temporal", "combined"),
              "spatial": config["mode"] in ("spatial", "combined")}
    for name, enabled in active.items():
        if any((float(row[name + "_ms"]) > 0) != enabled for row in timings):
            raise RuntimeError(f"Unexpected {name} pass execution")
    if resolved["width"] != config["width"] or resolved["height"] != config["height"]:
        raise RuntimeError("Actual rendering resolution differs from requested resolution")
    expected_scene = config["scene"]
    source = expected_scene["source"]
    mount = "Assets/Media/" if source["kind"] == "builtin" else "Assets/Experiment/"
    if resolved["scene_id"] != config["scene_id"] or resolved["loaded_scene"] != mount + source["entry"]:
        raise RuntimeError("Renderer loaded a different scene")
    if resolved["headless"] != bool(config["arguments"]["device.headless"]):
        raise RuntimeError("Renderer window mode differs from requested mode")
    if not math.isclose(resolved["vertical_fov_degrees"], expected_scene["camera"]["vertical_fov"], rel_tol=1e-6):
        raise RuntimeError("Renderer camera FOV differs from requested FOV")
    definition = config["definition"]
    budgets = {
        "numLocalLightSamples": "initial_local_candidates",
        "numBrdfSamples": "initial_brdf_candidates",
        "numInfiniteLightSamples": "initial_infinite_candidates",
        "numEnvironmentSamples": "initial_environment_candidates",
    }
    if any(resolved["initialSamplingParams"][key] != definition[value] for key, value in budgets.items()):
        raise RuntimeError("Actual initial sample budgets differ from requested budgets")
    local_mode = definition.get("initial_local_sampling_mode", "UNIFORM")
    if resolved["initialSamplingParams"]["localLightSamplingMode"] != LOCAL_SAMPLING_MODES[local_mode]:
        raise RuntimeError("Actual local-light sampling mode differs from requested mode")
    if definition["initial_environment_candidates"] and (
            not resolved["environment_present"] or
            not resolved["initialSamplingParams"]["environmentMapImportanceSampling"]):
        raise RuntimeError("Requested environment importance sampling is unavailable")
    if not definition.get("analytic_sun", True) and resolved["analytic_sun_irradiance"] != 0:
        raise RuntimeError("Analytic sun was not disabled")
    if (resolved["spatialResamplingParams"]["numSamples"] != definition["spatial_neighbors"] or
            resolved["temporalResamplingParams"]["maxHistoryLength"] != definition["max_history_length"]):
        raise RuntimeError("Actual reuse budgets differ from requested budgets")
    for key in ("environment_intensity_ev", "environment_rotation_degrees", "emissive_scale"):
        if not math.isclose(resolved[key], expected_scene["lighting"][key], rel_tol=1e-6, abs_tol=1e-6):
            raise RuntimeError(f"Renderer lighting differs from requested {key}")
