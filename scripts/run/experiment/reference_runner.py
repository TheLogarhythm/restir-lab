"""Reference checkpoint validation, paired-stream execution and convergence records."""
import json
from PIL import Image
from rtxdi_common import sha
from .artifacts import save_json
from .images import read_pfm, write_pfm, preview_rgb
from .reference import (EPSILON, CONVERGENCE_METRIC, REFERENCE_SCHEMA_VERSION,
                        ImageCache, convergence, pfm_path, regions, rmae, target)
from .runner import relative_path

BUILD_FIELDS = ("renderer_commit", "executable_sha256", "shader_sha256", "integration_sha256")


def checkpoint_image(directory, seed, samples, batch):
    """Find the sole completed attempt in the current segmented layout."""
    checkpoint = directory / f"seed-{seed}/checkpoint-{samples}"
    completed = []
    for attempt in checkpoint.glob("attempt-*"):
        manifest = attempt / "manifest.json"
        if not manifest.is_file():
            continue
        if json.loads(manifest.read_text())["status"] == "completed":
            image = pfm_path(attempt / f"frame-{samples // batch:04d}")
            if not image.is_file():
                raise ValueError(f"Missing completed checkpoint image: {image}")
            completed.append(image)
    if len(completed) > 1:
        raise ValueError(f"Multiple completed attempts for {checkpoint}")
    return completed[0] if completed else None


def validate_resume(index, seeds, checkpoints, batch, sampling):
    if (index.get("schema_version") != REFERENCE_SCHEMA_VERSION
            or index.get("convergence_metric") != CONVERGENCE_METRIC
            or any(k not in index.get("build", {}) for k in BUILD_FIELDS)):
        raise ValueError("Unsupported reference suite; generate a new suite")
    settings = index.get("checkpoint_settings", {})
    previous = settings.get("checkpoints", [])
    if (index.get("seeds") != seeds or settings.get("batch_samples") != batch
            or settings.get("local_sampling") != sampling or not previous
            or checkpoints[:len(previous)] != previous):
        raise ValueError("Resume must keep the seeds, batch size, sampling strategy and checkpoint prefix")


class PoseAssessment:
    def __init__(self, captures, ratio, load_image):
        self.captures, self.ratio, self.load_image = captures, ratio, load_image
        self.rows, self.previous, self.streak = [], None, 0

    def add(self, samples, images):
        reference = (images[0] + images[1]) * .5
        masks = regions(*reference.shape[:2])
        checks = {name: convergence(images[0][region], images[1][region],
                  None if self.previous is None else self.previous[region]) for name, region in masks.items()}
        best = dict.fromkeys(masks, float("inf"))
        for capture in self.captures:
            image = self.load_image(capture["image"])
            for name, region in masks.items():
                best[name] = min(best[name], rmae(image[region], reference[region]))
        for name, values in checks.items():
            threshold = self.ratio * best[name]
            values.update(threshold_rmae=threshold, best_baseline_rmae=best[name])
            values["passed"] = (values["change_rmae"] is not None
                                and values["stream_disagreement_rmae"] <= threshold
                                and values["change_rmae"] <= threshold)
        passed = checks["full"]["passed"]
        self.streak = self.streak + 1 if passed else 0
        self.rows.append({"samples_per_class_per_stream": samples, "regions": checks, "passed": passed})
        self.previous = reference
        return self.streak >= 2

    def save(self, directory):
        if not self.rows:
            raise ValueError("No paired checkpoints available for reassessment")
        write_pfm(directory / "reference.pfm.gz", self.previous)
        Image.fromarray(preview_rgb(self.previous, self.captures[0]["config"]["preview"]["exposure_ev"])).save(directory / "reference.png")
        result = {"schema_version": REFERENCE_SCHEMA_VERSION, "convergence_metric": CONVERGENCE_METRIC,
                  "converged": self.streak >= 2, "consecutive_passes": self.streak,
                  "required_consecutive_passes": 2, "convergence_regions": ["full"], "reference_noise_ratio": self.ratio,
                  "samples_per_class_per_stream": self.rows[-1]["samples_per_class_per_stream"],
                  "epsilon": EPSILON, "checkpoints": self.rows,
                  "baseline_image_sha256": {relative_path(c["image"], directory): sha(c["image"]) for c in self.captures},
                  "assumptions": "Empirical half-stream RMAE agreement and checkpoint stability; not an unbiased residual MAE estimate or proof of accuracy. Shared bias is undetected."}
        save_json(directory / "convergence.json", result)
        return result


def run_pose(directory, captures, checkpoints, batch, seeds, ratio, run_stream, validate=None, load_image=None):
    load_image = load_image or ImageCache()
    assessment = PoseAssessment(captures, ratio, load_image)
    previous_samples, previous_paths, previous_images = 0, dict.fromkeys(seeds), dict.fromkeys(seeds)
    for samples in checkpoints:
        paths = {seed: checkpoint_image(directory, seed, samples, batch) for seed in seeds}
        if run_stream is None and any(path is None for path in paths.values()):
            break
        for seed in seeds:
            if paths[seed] is None:
                paths[seed] = run_stream(seed, samples, previous_samples, previous_paths[seed], previous_images[seed])
            if validate:
                validate(paths[seed], seed, samples, previous_samples, previous_paths[seed])
        images = {seed: read_pfm(paths[seed]) for seed in seeds}
        passed = assessment.add(samples, [images[seed] for seed in seeds])
        previous_samples, previous_paths, previous_images = samples, paths, images
        if passed and run_stream is not None:
            break
    return assessment.save(directory)


def validate_checkpoint(image, sample, seed, samples, batch, build=None, *, previous_samples=None, previous_image=None, sampling=None):
    directory = image.parent
    manifest = json.loads((directory / "manifest.json").read_text())
    config_path = directory / "config.json"
    config = json.loads(config_path.read_text())
    ref = config.get("reference", {})
    if (manifest["status"] != "completed" or sha(config_path) != manifest["config_sha256"]
            or config["seed"] != seed or ref.get("batch_samples_per_light_class") != batch
            or ref.get("schema_version") != REFERENCE_SCHEMA_VERSION or ref.get("checkpoints") != [samples]):
        raise ValueError("Incomplete or incompatible reference checkpoint")
    if sampling is not None and config["definition"].get("initial_local_sampling_mode") != sampling:
        raise ValueError("Resume sampling strategy differs")
    resumed = ref.get("resume_batches", 0)
    if (type(resumed) is not int or resumed < 0
            or previous_samples is not None and resumed * batch != previous_samples
            or [f["frame"] for f in config["frames"]] != list(range(resumed + 1, samples // batch + 1))
            or [f["frame"] for f in config["frames"] if f["capture"]] != [samples // batch]
            or any(f["sampling_frame"] != seed * 1048576 + f["frame"] - 1 for f in config["frames"])):
        raise ValueError("Reference checkpoint accumulation or sampling sequence differs")
    frame = next((f for f in config["frames"] if f["frame"] == samples // batch and f["capture"]), None)
    if frame is None or any(target(config, f, manifest["scene"]["sha256"]) != sample["target"] for f in config["frames"]):
        raise ValueError("Reference checkpoint lighting target differs")
    record = next((c for c in manifest["captures"] if c["frame"] == frame["frame"]), {})
    if not record.get("image_sha256"):
        raise ValueError("Reference checkpoint is missing its image hash")
    if sha(image) != record["image_sha256"]:
        raise ValueError("Reference checkpoint image was modified")
    if build and any(manifest["build"].get(k) != build[k] for k in BUILD_FIELDS):
        raise ValueError("Reference renderer/shaders changed; use a new suite")
    if bool(resumed) != bool(ref.get("resume_image")):
        raise ValueError("Reference checkpoint resume dependency is missing or unexpected")
    if resumed:
        source = (directory / ref["resume_image"]).resolve()
        if previous_image is not None and source != previous_image.resolve():
            raise ValueError("Reference checkpoint resumes from a different stream checkpoint")
        if sha(source) != ref.get("resume_image_sha256"):
            raise ValueError("Reference resume dependency was modified")
