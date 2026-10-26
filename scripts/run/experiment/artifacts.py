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
from .scenes import camera_basis
from .geometry_io import save_geometry, validate_geometry_outputs

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


def cgns_stats(path, width, height, candidates, neighbors):
    """Decode packed per-pixel counters; preserve the raw diagnostic for inspection."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size != width * height * 4:
        raise RuntimeError("Missing or incorrectly sized CGNS diagnostics")
    values = np.fromfile(path, dtype="<u4")
    tried, scored, selected = (values >> shift & 255 for shift in (0, 8, 16))
    if (np.any(values >> 24) or np.any(tried > candidates) or np.any(scored > tried)
            or np.any(selected > np.minimum(neighbors, scored))):
        raise RuntimeError("Invalid CGNS diagnostic counts")
    active = tried > 0
    def active_mean(values):
        return float(values[active].mean()) if active.any() else None
    return {"cgns_active_pixel_fraction": float(active.mean()),
            "cgns_tried_mean_active": active_mean(tried),
            "cgns_scored_mean_active": active_mean(scored),
            "cgns_selected_mean_active": active_mean(selected),
            "cgns_zero_selected_fraction_active": active_mean(selected == 0),
            "cgns_diagnostic_sha256": sha(path)}


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
            if config["definition"].get("cgns", False):
                record.update(cgns_stats(stem.with_suffix(".cgns"), config["width"], config["height"],
                                         config["definition"].get("cgns_candidates", 32),
                                         config["definition"]["spatial_neighbors"]))
        if config.get("geometry_export", False):
            record.update(save_geometry(stem, config["width"], config["height"],
                                        config["scene"]["camera"]["vertical_fov"]))
            temporary_files.extend((stem.with_suffix(".depth32f"), stem.with_suffix(".normals32u")))
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
    expected_history = config["definition"].get("pdf_history_mode", 0)
    # PDF builds must confirm even mode 0. Older ordinary builds omit the field.
    actual_history = resolved.get("pdf_history_mode", None if resolved.get("pdf_similarity", False) else 0)
    if type(actual_history) is not int or actual_history != expected_history:
        raise RuntimeError("Resolved PDF history mode differs from requested mode")
    cgns = config["definition"].get("cgns", False)
    actual_cgns = resolved.get("cgns", False)
    if type(actual_cgns) is not bool or actual_cgns != cgns:
        raise RuntimeError("Resolved CGNS differs from requested mode")
    if "cgns" in resolved:
        for key, default, kind in (("cgns_candidates", 32, int), ("cgns_early_stopping", True, bool)):
            actual = resolved.get(key)
            if type(actual) is not kind or actual != config["definition"].get(key, default):
                raise RuntimeError(f"Resolved CGNS parameter differs: {key}")
    for row in timings:
        if "cgns" in resolved and "neighbor_selection_ms" not in row:
            raise RuntimeError("Missing CGNS neighbor selection timing")
        neighbor_ms = float(row.get("neighbor_selection_ms", 0))
        if (neighbor_ms > 0) != cgns:
            raise RuntimeError("Unexpected CGNS neighbor selection pass execution")
        if neighbor_ms > float(row["gpu_ms"]) + 1e-6:
            raise RuntimeError("CGNS neighbor selection timing exceeds the GPU frame")
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
    validate_frame_states(output, config)
    validate_geometry_outputs(output, config, resolved)


def validate_frame_states(output, config):
    """Require new controls to be acknowledged by the material/light preparation path."""
    path = Path(output) / "resolved-frames.jsonl"
    controlled = (any("logical_time_seconds" in frame or "lighting" in frame for frame in config["frames"])
                  or (config["scenario"] == "motion" and any(
                      key in config["scene"]["motion"] for key in ("end_direction", "end_up"))))
    if not path.is_file():
        if controlled:
            raise RuntimeError("Missing resolved frame states for deterministic controls")
        return  # Older ordinary experiments retain their historical output contract.
    def number(value):
        return type(value) in (int, float) and math.isfinite(value)
    def close(actual, expected):
        return number(actual) and math.isclose(actual, expected, rel_tol=1e-5, abs_tol=1e-6)
    def positive_integer(value):
        return type(value) is int and value > 0
    try:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        if len(records) != len(config["frames"]):
            raise ValueError("Missing or duplicate frame states")
        previous, original_material = None, None
        for record, expected in zip(records, config["frames"]):
            if any(type(record[key]) is not int or record[key] != expected[key]
                   for key in ("frame", "sampling_frame")) or record["history_reset"] is not expected["reset"]:
                raise ValueError("Resolved state sequence/reset differs from requested sequence")
            _, expected_up, expected_direction = camera_basis(expected["direction"], expected["up"])
            for key, value in (("position", expected["position"]), ("direction", expected_direction), ("up", expected_up)):
                if len(record[key]) != 3 or any(not close(a, b) for a, b in zip(record[key], value)):
                    raise ValueError("Resolved camera pose differs from requested pose")
            if "logical_time_seconds" in expected and not close(
                    record["logical_time_seconds"], expected["logical_time_seconds"]):
                raise ValueError("Resolved logical scene time differs from requested time")
            if "lighting" in expected:
                requested, actual = expected["lighting"], record["lighting"]
                if (actual["material"] != requested["material"] or not close(
                        actual["emissive_intensity_multiplier"], requested["emissive_intensity_multiplier"])):
                    raise ValueError("Resolved material lighting differs from requested lighting")
                update = record["material_update"]
                intensity = update["original_emissive_intensity"]
                if (not number(intensity) or intensity <= 0 or not close(update["emissive_intensity"],
                        intensity * requested["emissive_intensity_multiplier"])
                        or update["dirty_before_upload"] is not True
                        or not positive_integer(update["emitting_triangles"])
                        or not positive_integer(update["emitting_geometries"])
                        or type(update["material_id"]) is not int or update["material_id"] < 0):
                    raise ValueError("Material update was not positive, absolute, and dirty before upload")
                identity = (actual["material"], update["material_id"], intensity,
                            update["emitting_triangles"], update["emitting_geometries"], update["emissive_color"])
                if original_material is not None and identity != original_material:
                    raise ValueError("Material/emitter identity changed during lighting modulation")
                original_material = identity
            correspondence = record["light_correspondence"]
            for total, matched, same_offset in (("emissive_triangles", "mapped_emissive_triangles", "same_offset_emissive_triangles"),
                    ("primitive_lights", "mapped_primitive_lights", "same_offset_primitive_lights")):
                values = [correspondence[key] for key in (total, matched, same_offset)]
                if any(type(value) is not int or value < 0 for value in values):
                    raise ValueError("Invalid light correspondence counts")
                wanted = correspondence[total] if previous else 0
                if correspondence[matched] != wanted or correspondence[same_offset] != wanted:
                    raise ValueError("Incomplete or reordered current/previous light correspondence")
                if previous and correspondence[total] != previous["light_correspondence"][total]:
                    raise ValueError("Emitting identities/counts changed during controlled rendering")
            if correspondence["sampling_pdf_mip0_refreshed"] is not True or (
                    config["definition"].get("initial_local_sampling_mode", "UNIFORM") == "POWER_RIS"
                    and correspondence["sampling_pdf_mips_refreshed"] is not True):
                raise ValueError("Light sampling PDF was not refreshed")
            if previous and any(record[key] != previous[key]
                                for key in ("local_lights", "infinite_lights", "environment_present")):
                raise ValueError("Light counts changed during controlled rendering")
            previous = record
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise RuntimeError(f"Invalid resolved frame states: {error}") from error
