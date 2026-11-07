"""Conventional path-spp policy, independent from fixed local-light budgets."""
import copy
import json
from pathlib import Path

from rtxdi_common import ROOT, RENDERER, sha
from .reference import reference_config
from .transport import profile, target, path_sample_schedule

EXE = RENDERER / "build/bin/FullSamplePathReference.exe"


def policy(component):
    profile(component)
    return {"kind": "fixed_path_spp", "schema_version": 1, "component": component,
            "seed": 1001, "spp": 8192, "checkpoints": [4096, 8192], "paths_per_iteration": 1}


def validate_policy(value):
    if not isinstance(value, dict) or value != policy(value.get("component")):
        raise ValueError("Unsupported fixed path-spp policy")
    if any(type(value[key]) is not int for key in ("schema_version", "seed", "spp", "paths_per_iteration")):
        raise ValueError("Path-spp policy requires integer counts")
    return copy.deepcopy(value)


def validate_schedule(config):
    ref = config["reference"]
    if (ref.get("estimator") != "conventional_path_tracing" or ref.get("paths_per_iteration") != 1
            or ref.get("accumulation") != "FP32 running mean"):
        raise ValueError("Not a conventional one-path-per-iteration checkpoint")
    samples = path_sample_schedule(config["seed"], ref["completed_spp"],
                                   completed_spp=ref.get("resume_batches", 0))
    if len(config["frames"]) != len(samples):
        raise ValueError("Path-spp frame count differs")
    for index, (frame, sample) in enumerate(zip(config["frames"], samples)):
        if (frame["frame"] != sample["completed_spp"] or frame["sampling_frame"] != sample["sampling_frame"]
                or frame["reset"] is not (index == 0) or frame["capture"] is not (index == len(samples) - 1)):
            raise ValueError("Path sample schedule was changed or repeated")


def validate_runtime(output, config, resolved):
    validate_schedule(config)
    expected = {"max_surface_scattering": config["transport"]["max_surface_scattering"],
                "paths_per_iteration": 1, "reference_mis": "off-disjoint-support",
                "reference_roulette": False, "reference_cutoff": 0.0,
                "reference_glass": "legacy-DI"}
    for key, value in expected.items():
        if type(resolved.get(key)) is not type(value) or resolved[key] != value:
            raise ValueError(f"Path reference runtime differs: {key}")
    counter = json.loads((Path(output) / "path-checkpoint.json").read_text())
    samples = config["reference"]["completed_spp"]
    if counter != {"completed_spp": samples, "next_sample_index": samples, "paths_per_iteration": 1}:
        raise ValueError("Path reference checkpoint count differs")


def make_config(base, pose, component, spp, *, seed=1001, completed_spp=0, previous=None):
    samples = path_sample_schedule(seed, spp, completed_spp=completed_spp)
    if spp < 2 or bool(completed_spp) != (previous is not None):
        raise ValueError("Path checkpoint resume requires its completed parent image")
    base = copy.deepcopy(base)
    base["definition"].pop("transport_schema", None)
    base["definition"]["geometry_export"] = False
    config = reference_config(base, pose, [spp], 1, seed, "POWER_RIS",
                              previous_samples=completed_spp, resume_image=previous)
    config["diagnostics"] = False
    config["definition"]["path_reference_schema"] = 1
    config["transport"] = profile(component)
    config["reference"] = {
        "schema_version": 1, "estimator": "conventional_path_tracing",
        "checkpoints": [spp], "completed_spp": spp, "paths_per_iteration": 1,
        "sample_count_unit": "camera-conditioned path samples per pixel",
        "nee_samples_per_present_class_per_scattering_vertex": 1,
        "local_sampling": "power PDF mipmap, direct sampling, no RIS pool",
        "bsdf_sampling": "Lambert/GGX mixture with discrete mirror below roughness 0.03",
        "bsdf_pdf": "visible-GGX D*G1(V)/(4*N.V); discrete delta mass",
        "environment_proposal_floor": 1.0 / 1024,
        "mis": "off: indexed continuous endpoints via NEE; delta/unindexed endpoints via BSDF",
        "russian_roulette": False, "radiance_clamp": False, "throughput_cutoff": 0.0,
        "accumulation": "FP32 running mean", "resume_batches": completed_spp,
        "first_sample_index": samples[0]["sample_index"], "next_sample_index": spp,
    }
    if previous is not None:
        previous = Path(previous).resolve()
        parent_path = previous.parent / "config.json"
        parent = json.loads(parent_path.read_text())
        manifest = json.loads((previous.parent / "manifest.json").read_text())
        validate_schedule(parent)
        captures = [c for c in manifest.get("captures", []) if c["frame"] == completed_spp]
        if (manifest.get("status") != "completed" or manifest.get("config_sha256") != sha(parent_path)
                or len(captures) != 1 or captures[0].get("image_sha256") != sha(previous)
                or parent["reference"]["completed_spp"] != completed_spp or parent["seed"] != seed
                or parent["transport"] != config["transport"]
                or target(parent, parent["frames"][-1], manifest["scene"]["sha256"], component)
                   != target(config, config["frames"][-1], manifest["scene"]["sha256"], component)):
            raise ValueError("Path reference parent identity/count/target differs")
        config["reference"].update(resume_image=str(previous), resume_image_sha256=sha(previous),
                                   resume_config_sha256=sha(parent_path))
    validate_schedule(config)
    return config


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find_checkpoint(folder):
    """Never retry a failed run implicitly or replace an existing completion."""
    attempts = sorted(Path(folder).glob("attempt-*"))
    if not attempts:
        return None
    complete = []
    for attempt in attempts:
        manifest = attempt / "manifest.json"
        if not manifest.is_file() or read_json(manifest).get("status") != "completed":
            raise ValueError(f"Checkpoint needs explicit diagnosis before recovery: {attempt}")
        complete.append(attempt)
    if len(complete) != 1:
        raise ValueError("Multiple completed checkpoint attempts; refusing ambiguous input")
    return complete[0]


def validate_checkpoint(directory, base, component, spp, build, assets, *, previous=None, seed=1001):
    """Reconstruct exact controls and validate one checkpoint against its parent."""
    from .artifacts import validate_run_outputs
    from .images import read_pfm
    from .runner import relative_path
    import numpy as np
    directory = Path(directory).resolve()
    manifest, config = read_json(directory / "manifest.json"), read_json(directory / "config.json")
    parent_count = read_json(previous.parent / "config.json")["reference"]["completed_spp"] if previous else 0
    expected = make_config(base, base["frames"][-1], component, spp, seed=seed,
                           completed_spp=parent_count, previous=previous)
    expected.update(output=".", repository_root=relative_path(ROOT, directory))
    if previous:
        expected["reference"]["resume_image"] = relative_path(previous, directory)
    if (config != expected or manifest.get("status") != "completed"
            or manifest.get("config_sha256") != sha(directory / "config.json")
            or manifest.get("build") != build or manifest.get("scene") != assets):
        raise ValueError("Path checkpoint controls/build/assets differ from frozen inputs")
    image = directory / f"frame-{spp:04d}.pfm.gz"
    captures = manifest.get("captures", [])
    if len(captures) != 1 or captures[0].get("frame") != spp or captures[0].get("image_sha256") != sha(image):
        raise ValueError("Path checkpoint image hash/count differs")
    validate_run_outputs(directory, config)
    rgb = read_pfm(image)
    if rgb.shape != (config["height"], config["width"], 3) or not np.isfinite(rgb).all():
        raise ValueError("Path checkpoint HDR shape/finite check failed")
    return image


def ensure_reference(root, base, component, build, assets, *, input_guard=None, progress=None):
    """Exact 4096 -> 8192 chain, using the existing durable run/guard mechanism."""
    from .artifacts import save_json
    from .fixed_reference import reference_timeout
    from .runner import run_one, frozen_input_guard, relative_path
    from .transport import target_key
    root = Path(root)
    requested = policy(component)
    value = target(base, base["frames"][-1], assets["sha256"], component)
    key = target_key(value)
    previous, observed, checkpoints = None, None, []
    for spp in requested["checkpoints"]:
        if input_guard:
            input_guard()
        folder = root / key / f"checkpoint-{spp}"
        directory = find_checkpoint(folder)
        previous_count = checkpoints[-1]["spp"] if checkpoints else 0
        if directory is None:
            directory = folder / "attempt-1"
            config = make_config(base, base["frames"][-1], component, spp,
                                 completed_spp=previous_count, previous=previous)
            if progress:
                progress({"component": component, "target": key, "spp_target": spp,
                          "completed_spp": previous_count, "directory": str(directory), "status": "rendering"})
            guard = frozen_input_guard(config, EXE, build, assets, input_guard)
            run_one(config, directory, build, assets,
                    reference_timeout(spp, previous_count, observed), executable=EXE, input_guard=guard)
        image = validate_checkpoint(directory, base, component, spp, build, assets, previous=previous)
        manifest = read_json(directory / "manifest.json")
        observed = {"iterations": spp - previous_count, "seconds": manifest["wall_seconds_including_startup_and_export"]}
        checkpoints.append({"spp": spp, "image": relative_path(image, root), "image_sha256": sha(image),
                            "manifest_sha256": sha(directory / "manifest.json"),
                            "config_sha256": sha(directory / "config.json")})
        previous = image
    record = {"target": value, "target_key": key, "policy": requested, "checkpoints": checkpoints,
              "build": build, "ready": True, "precision_verified": False,
              "sample_unit": "camera-conditioned path samples per pixel"}
    save_json(root / key / "reference.json", record)
    return record


def load_reference(root, record, base, component, build, assets):
    """Validate the complete ancestry, never just a final image or target label."""
    from .transport import target_key
    root = Path(root)
    value = target(base, base["frames"][-1], assets["sha256"], component)
    requested = validate_policy(record["policy"])
    if (record.get("target") != value or record.get("target_key") != target_key(value)
            or requested != policy(component) or record.get("build") != build
            or [c["spp"] for c in record["checkpoints"]] != requested["checkpoints"]):
        raise ValueError("Reference target/policy/build/chain differs")
    previous = None
    for checkpoint in record["checkpoints"]:
        image = (root / checkpoint["image"]).resolve()
        folder = (root / record["target_key"] / f"checkpoint-{checkpoint['spp']}").resolve()
        directory = find_checkpoint(folder)
        if (directory is None or image.parent != directory.resolve()
                or image.name != f"frame-{checkpoint['spp']:04d}.pfm.gz"
                or not image.is_relative_to(root.resolve())):
            raise ValueError("Reference checkpoint is not the sole canonical completed attempt")
        if (sha(image) != checkpoint["image_sha256"]
                or sha(image.parent / "manifest.json") != checkpoint["manifest_sha256"]
                or sha(image.parent / "config.json") != checkpoint["config_sha256"]):
            raise ValueError("Reference checkpoint inputs changed")
        validated = validate_checkpoint(image.parent, base, component, checkpoint["spp"], build, assets, previous=previous)
        if validated != image:
            raise ValueError("Reference checkpoint image path differs")
        previous = image
    return previous
