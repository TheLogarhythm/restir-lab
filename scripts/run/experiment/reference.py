"""Reference targets, linear-image metrics and independent-pair convergence."""
from collections import OrderedDict
import copy
import hashlib
import json
from pathlib import Path
import numpy as np
from rtxdi_common import sha
from rtxdi_build import lighting_signature
from .config import make_config
from .images import read_pfm

EPSILON = 1e-12
REFERENCE_SCHEMA_VERSION = 3
CONVERGENCE_METRIC = {"name": "RMAE", "version": 1,
    "normalization": "mean_absolute_reference", "agreement": "half_stream_difference"}
SURFACE_ARGUMENTS = ("rendering.rayQuery", "rendering.pixelJitter", "postProcessing.textures",
                     "gbuffer.alphaTested", "gbuffer.transparent", "gbuffer.rasterizeGBuffer")


def pfm_path(stem):
    """The sole on-disk HDR artifact format for experiment runs."""
    return Path(stem).with_suffix(".pfm.gz")


class ImageCache:
    """Bounded LRU of decoded images; no temporary files or retained gzip buffers."""
    def __init__(self, max_bytes=512 * 1024**2):
        if max_bytes <= 0:
            raise ValueError("Image cache size must be positive")
        self.max_bytes = max_bytes
        self.bytes = 0
        self.images = OrderedDict()

    def __call__(self, path):
        path = Path(path).resolve()
        if path in self.images:
            self.images.move_to_end(path)
            return self.images[path]
        image = read_pfm(path)
        image.setflags(write=False)
        if image.nbytes <= self.max_bytes:
            while self.bytes + image.nbytes > self.max_bytes:
                _, old = self.images.popitem(last=False)
                self.bytes -= old.nbytes
            self.images[path] = image
            self.bytes += image.nbytes
        return image


def pair(image, reference):
    image, reference = np.asarray(image, dtype=np.float64), np.asarray(reference, dtype=np.float64)
    if image.shape != reference.shape or image.ndim != 3 or image.shape[-1] != 3 or not image.size:
        raise ValueError("Images must have matching nonempty H x W x 3 shapes")
    if not np.isfinite(image).all() or not np.isfinite(reference).all():
        raise ValueError("Non-finite image values")
    return image, reference


def rmae(image, reference):
    image, reference = pair(image, reference)
    return float(np.mean(np.abs(image - reference)) / (np.mean(np.abs(reference)) + EPSILON))


def metrics(image, reference):
    image, reference = pair(image, reference)
    mse = float(np.mean(np.square(image - reference)))
    energy = float(np.mean(np.square(reference)))
    luminance = np.array([0.2126, 0.7152, 0.0722])
    mean_y = float(np.mean(reference @ luminance))
    return {"rmse": float(np.sqrt(mse)), "nrmse": float(np.sqrt(mse / (energy + EPSILON))),
            "rmae": rmae(image, reference),
            "relative_luminance_offset": float(np.mean((image - reference) @ luminance) / (mean_y + EPSILON))}


def convergence(a, b, previous=None):
    a, b = pair(a, b)
    reference = (a + b) * 0.5
    error = metrics(a, b)  # Only its absolute RMSE is used; normalize against their average.
    rmse = error["rmse"] * 0.5
    return {"stream_disagreement_rmae": metrics(a, reference)["rmae"],
            "change_rmae": None if previous is None else metrics(previous, reference)["rmae"],
            "estimated_reference_rmse": rmse,
            "estimated_reference_nrmse": float(rmse / np.sqrt(np.mean(reference**2) + EPSILON)),
            "change_nrmse": None if previous is None else metrics(previous, reference)["nrmse"]}


def reference_ready(checkpoints, best_errors, ratio, metric):
    """Recheck full-image RMAE; quadrant metrics are diagnostic only."""
    if metric != CONVERGENCE_METRIC:
        raise ValueError("Unsupported convergence metric; generate a new reference suite")
    if (not 0 < ratio < 1 or "full" not in best_errors
            or not np.isfinite(best_errors["full"]) or best_errors["full"] < 0):
        raise ValueError("Invalid reference precision threshold")
    samples = [c["samples_per_class_per_stream"] for c in checkpoints]
    if any(type(n) is not int or n <= 0 for n in samples) or any(b != 2*a for a, b in zip(samples, samples[1:])):
        raise ValueError("Invalid reference checkpoint sequence")
    for checkpoint in checkpoints:
        if "full" not in checkpoint["regions"]:
            raise ValueError("Missing full-image reference checkpoint error")
        for values in (checkpoint["regions"]["full"],):
            for field in ("stream_disagreement_rmae", "change_rmae"):
                value = values[field]
                if value is None and field == "change_rmae":
                    continue
                if value is None or not np.isfinite(value) or value < 0:
                    raise ValueError("Invalid reference checkpoint error")
    if len(checkpoints) < 3:
        return False
    threshold = ratio * best_errors["full"]
    return all(values["change_rmae"] is not None
        and values["stream_disagreement_rmae"] <= threshold
        and values["change_rmae"] <= threshold
        for values in (checkpoint["regions"]["full"] for checkpoint in checkpoints[-2:]))


def regions(height, width):
    """Full image and fixed quadrants for error diagnostics."""
    result = {"full": (slice(None), slice(None))}
    if height >= 2 and width >= 2:
        for y, (y0, y1) in enumerate(((0, height // 2), (height // 2, height))):
            for x, (x0, x1) in enumerate(((0, width // 2), (width // 2, width))):
                result[f"quadrant-{y}-{x}"] = (slice(y0, y1), slice(x0, x1))
    return result


def target(config, frame, asset_hash):
    # Sampling budgets, seeds and reuse modes change variance, not the lighting target.
    return {"scene_id": config["scene_id"], "asset_sha256": asset_hash,
            "renderer_commit": config["definition"]["renderer_commit"],
            "resolution": [config["width"], config["height"]],
            "camera": {key: frame[key] for key in ("position", "direction", "up")},
            "vertical_fov": config["scene"]["camera"]["vertical_fov"],
            "lighting": config["scene"]["lighting"],
            "analytic_sun": config["definition"].get("analytic_sun", True),
            "surface_settings": {key: config["arguments"].get(key) for key in SURFACE_ARGUMENTS},
            "output": "scene-linear direct illumination + upstream emission/background/glass"}


def target_key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]


def validate_lighting(captures, reference_build):
    expected = lighting_signature(reference_build)
    for capture in captures:
        if lighting_signature(capture["manifest"].get("build", {})) != expected:
            raise ValueError("Baseline and reference lighting implementations differ; regenerate compatible runs")


def suite_captures(suite, scenes=None, scenario=None):
    records = []
    for path in sorted(Path(suite).rglob("manifest.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        config_path = path.with_name("config.json")
        if not config_path.exists():
            continue
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config.get("reference") or (scenes and config["scene_id"] not in scenes) or (
                scenario and config["scenario"] != scenario):
            continue
        if record["status"] != "completed" or sha(config_path) != record["config_sha256"]:
            raise ValueError(f"Incomplete or modified baseline record: {path}")
        if (config["arguments"].get("lighting.indirectMode") != "NONE" or
                config["arguments"].get("denoiser.mode") != "OFF" or
                config["arguments"].get("postProcessing.aaMode") != "OFF" or
                config["arguments"].get("rendering.pixelJitter") != 0 or
                config["arguments"].get("scene.animation") != 0):
            raise ValueError("Reference supports frozen, unprocessed direct-lighting baselines only")
        if config["arguments"].get("restirDI.shading.enableFinalVisibility") != 1:
            raise ValueError("Reference requires baseline final visibility")
        for frame in config["frames"]:
            if frame["capture"]:
                image = pfm_path(path.with_name(f"frame-{frame['frame']:04d}"))
                if not image.is_file():
                    raise ValueError(f"Missing baseline image: {image}")
                saved = next((c for c in record.get("captures", []) if c["frame"] == frame["frame"]), {})
                if saved.get("image_sha256") and sha(image) != saved["image_sha256"]:
                    raise ValueError(f"Baseline image was modified: {image}")
                value = target(config, frame, record["scene"]["sha256"])
                records.append({"directory": path.parent, "config": config, "manifest": record,
                                "frame": frame, "image": image, "target": value, "key": target_key(value)})
    if not records:
        raise ValueError("No completed baseline captures match the selection")
    return records


def reference_config(base, pose, checkpoints, batch_samples, seed, sampling, *,
                     previous_samples=0, resume_image=None):
    if (not checkpoints or any(type(n) is not int or n < 1 for n in checkpoints)
            or type(batch_samples) is not int or not 1 <= batch_samples <= 64
            or any(n % batch_samples for n in checkpoints)
            or any(b != 2 * a for a, b in zip(checkpoints, checkpoints[1:]))):
        raise ValueError("Checkpoints must double and be positive multiples of batch samples (1..64)")
    count = checkpoints[-1] // batch_samples
    if not 2 <= count <= 1048576:
        raise ValueError("Reference requires 2..1048576 batches per stream")
    definition = copy.deepcopy(base["definition"])
    definition.update(frames=count, reset_frame=2, motion={"start_frame": 1, "end_frame": 2},
                      captures={key: [n // batch_samples for n in checkpoints] for key in ("static", "motion", "reset")},
                      initial_local_candidates=batch_samples, initial_environment_candidates=batch_samples,
                      initial_infinite_candidates=batch_samples, initial_brdf_candidates=0,
                      initial_local_sampling_mode=sampling)
    if (type(previous_samples) is not int or previous_samples < 0
            or previous_samples % batch_samples or previous_samples >= checkpoints[0]
            or bool(previous_samples) != (resume_image is not None)):
        raise ValueError("Resume requires an earlier batch-aligned checkpoint and its image")
    scene = copy.deepcopy(base["scene"])
    scene["camera"].update({key: pose[key] for key in ("position", "direction", "up")})
    config = make_config(scene, definition, "initial", "static", seed,
                         [base["width"], base["height"]], headless=True)
    config["arguments"].update({key: base["arguments"][key] for key in SURFACE_ARGUMENTS if key in base["arguments"]})
    config["reference"] = {"schema_version": REFERENCE_SCHEMA_VERSION, "estimator": "conventional_light_sampling", "checkpoints": checkpoints,
                           "batch_samples_per_light_class": batch_samples, "accumulation": "FP32 running mean"}
    if previous_samples:
        config["frames"] = config["frames"][previous_samples // batch_samples:]
        config["frames"][0]["reset"] = True  # Fresh geometry/history, retained reference mean.
        config["reference"].update(resume_batches=previous_samples // batch_samples,
                                   resume_image=str(resume_image))
    return config
