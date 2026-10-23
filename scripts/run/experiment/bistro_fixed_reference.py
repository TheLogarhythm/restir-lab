"""User-selected fixed Bistro references, without an uncertainty acceptance gate."""
from collections import defaultdict
import json
from pathlib import Path

from rtxdi_common import RENDERER, sha
from .artifacts import save_json
from .images import read_pfm
from .reference import (pfm_path, reference_config, target, target_key,
                        validate_lighting)
from .reference_allocation import PROGRESS_UNIT, allocation_totals
from .reference_runner import checkpoint_image, validate_checkpoint
from .runner import relative_path, run_one
from .scenes import validate_assets

POLICY_ID = "user_fixed_single_stream_262144_v1"
FIXED_SEED = 1001
FIXED_SAMPLES = 262144
BATCH_SAMPLES = 64
CLASS_COUNTS = {"local": 64, "environment": 8, "infinite": 4}
REFERENCE_EXE = RENDERER / "build/bin/FullSampleReference.exe"


def policy_metadata():
    """Return a fresh JSON policy; readiness makes no precision claim."""
    return {"policy_id": POLICY_ID, "scene_id": "bistro", "seeds": [FIXED_SEED],
        "local_samples_per_stream": FIXED_SAMPLES, "batch_counts": dict(CLASS_COUNTS),
        "resolution": [1920, 1080], "precision_checks": "not_evaluated",
        "label": "User-specified fixed-sample single-stream reference"}


def _same_json(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _same_json(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _same_json(a, b) for a, b in zip(actual, expected))
    return actual == expected


def validate_bistro_policy(value):
    """Reject every deviation from the explicitly selected fixed policy."""
    if not _same_json(value, policy_metadata()):
        raise ValueError("Fixed Bistro reference policy differs from the user-selected settings")
    return policy_metadata()


def _capture_target(capture):
    try:
        config, value = capture["config"], capture["target"]
        if (config["scene_id"] != "bistro" or value["scene_id"] != "bistro"
                or type(config["width"]) is not int or type(config["height"]) is not int
                or [config["width"], config["height"]] != [1920, 1080]
                or value["resolution"] != [1920, 1080]
                or capture["key"] != target_key(value)
                or target(config, capture["frame"], value["asset_sha256"]) != value):
            raise ValueError("Fixed reference requires the exact Bistro physical target at 1080p")
    except (KeyError, TypeError) as error:
        raise ValueError("Invalid fixed Bistro capture target") from error


def _read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value
    except (OSError, ValueError) as error:
        raise ValueError(f"Invalid fixed reference artifact: {path}") from error


def _validate_chain(directory, image, sample, samples, build=None):
    """Follow only necessary earlier checkpoints in this exact seed1001 stream."""
    if type(samples) is not int or not 128 <= samples <= FIXED_SAMPLES or samples % BATCH_SAMPLES:
        raise ValueError("Fixed reference checkpoint is outside the authorized sample cap")
    expected = checkpoint_image(directory, FIXED_SEED, samples, BATCH_SAMPLES)
    if expected is None or Path(image).resolve() != expected.resolve():
        raise ValueError("Fixed reference must use the completed seed1001 checkpoint directly")
    config = _read_json(image.with_name("config.json"))
    ref = config.get("reference", {})
    if (type(config.get("seed")) is not int or config["seed"] != FIXED_SEED
            or ref.get("checkpoints") != [samples]
            or ref.get("batch_samples_per_light_class") != BATCH_SAMPLES):
        raise ValueError("Fixed reference checkpoint seed, samples or batch differ")
    resumed = ref.get("resume_batches", 0)
    if type(resumed) is not int or not 0 <= resumed < samples // BATCH_SAMPLES:
        raise ValueError("Invalid fixed reference resume accumulation")
    previous_samples, previous_image = resumed * BATCH_SAMPLES, None
    if resumed:
        if not isinstance(ref.get("resume_image"), str):
            raise ValueError("Fixed reference resume dependency is missing")
        previous_image = checkpoint_image(directory, FIXED_SEED, previous_samples, BATCH_SAMPLES)
        source = (image.parent / ref["resume_image"]).resolve()
        if previous_image is None or source != previous_image.resolve():
            raise ValueError("Fixed reference resume dependency differs from the authorized seed1001 chain")
        _validate_chain(directory, previous_image, sample, previous_samples, build)
    validate_checkpoint(image, sample, FIXED_SEED, samples, BATCH_SAMPLES, build,
        previous_samples=previous_samples, previous_image=previous_image, sampling="POWER_RIS")
    # Hashes and declared runtime dimensions cannot establish the HDR payload's
    # dimensions or finite pixels. Decode every required checkpoint before use;
    # read_pfm rejects malformed/truncated and non-finite RGB data itself.
    if read_pfm(image).shape != (1080, 1920, 3):
        raise ValueError("Fixed Bistro reference HDR resolution differs from 1080p RGB")
    return config


def _highest_checkpoint(directory, sample, build):
    candidates = []
    for checkpoint in (directory / f"seed-{FIXED_SEED}").glob("checkpoint-*"):
        try:
            samples = int(checkpoint.name.removeprefix("checkpoint-"))
        except ValueError:
            continue
        # Do not open manifests or configs outside the authorized stream/cap.
        if (checkpoint.name == f"checkpoint-{samples}"
                and 128 <= samples < FIXED_SAMPLES and samples % BATCH_SAMPLES == 0):
            candidates.append(samples)
    for samples in sorted(candidates, reverse=True):
        image = checkpoint_image(directory, FIXED_SEED, samples, BATCH_SAMPLES)
        if image is not None:
            config = _validate_chain(directory, image, sample, samples, build)
            return samples, image, allocation_totals(config)
    return 0, None, None


def _inside(directory, value):
    if not isinstance(value, str) or not value:
        raise ValueError("Missing fixed reference artifact path")
    base = Path(directory).resolve()
    path = (Path(directory) / value).resolve()
    if not path.is_relative_to(base):
        raise ValueError("Fixed reference artifact path leaves its suite")
    return path


def fixed_record_paths(directory, record):
    """Validate saved fixed-policy settings and every bound artifact before reuse."""
    policy = policy_metadata()
    if (not isinstance(record, dict) or record.get("policy_id") != POLICY_ID
            or record.get("ready") is not True or record.get("converged") is not None
            or record.get("precision_verified") is not False
            or record.get("precision_checks") != "not_evaluated"
            or record.get("uncertainty_checks") != "not_evaluated"
            or not _same_json(record.get("seeds"), [FIXED_SEED])
            or type(record.get("samples")) is not int or record["samples"] != FIXED_SAMPLES
            or record.get("sample_count_unit") != PROGRESS_UNIT
            or not _same_json(record.get("batch_counts"), CLASS_COUNTS)
            or not _same_json(record.get("resolution"), [1920, 1080])
            or any(name in record for name in ("previous_image", "convergence"))):
        raise ValueError("Invalid fixed Bistro reference record")
    validate_bistro_policy(record.get("reference_policy"))
    value = record.get("target", {})
    if (not isinstance(value, dict) or value.get("scene_id") != "bistro"
            or value.get("resolution") != [1920, 1080]):
        raise ValueError("Fixed reference record target differs")
    pose_directory = (Path(directory) / "bistro" / target_key(value)).resolve()
    paths = {name: _inside(directory, record.get(name))
             for name in ("image", "config", "manifest", "policy_metadata")}
    image = paths["image"]
    checkpoint = pose_directory / f"seed-{FIXED_SEED}/checkpoint-{FIXED_SAMPLES}"
    attempt = image.parent.name.removeprefix("attempt-")
    if (image.parent.parent != checkpoint or not attempt.isdecimal()
            or image.parent.name != f"attempt-{int(attempt)}"
            or image.name != f"frame-{FIXED_SAMPLES // BATCH_SAMPLES:04d}.pfm.gz"
            or paths["config"] != image.with_name("config.json")
            or paths["manifest"] != paths["image"].with_name("manifest.json")
            or paths["policy_metadata"] != pose_directory / "fixed-policy.json"
            or record.get("stream_images") != [record["image"]]
            or record.get("stream_sha256") != [record["image_sha256"]]):
        raise ValueError("Fixed reference streams or checkpoint evidence differ")
    for name, path in paths.items():
        if not path.is_file() or sha(path) != record.get(f"{name}_sha256"):
            raise ValueError(f"Fixed reference artifact is missing or modified: {path}")
    validate_bistro_policy(_read_json(paths["policy_metadata"]))
    config = _validate_chain(pose_directory, paths["image"], {"target": value}, FIXED_SAMPLES)
    if (config["reference"].get("allocation", {}).get("batch_counts") != CLASS_COUNTS
            or record.get("class_samples_by_stream") != {str(FIXED_SEED): allocation_totals(config)}):
        raise ValueError("Fixed reference allocation differs from the requested budgets")
    return {"image": paths["image"], "streams": [paths["image"]], "reference_policy": policy}


def ensure_fixed_bistro(manager, captures):
    """Reuse or finish one capped conventional stream for each Bistro physical key."""
    captures = list(captures)
    groups = defaultdict(list)
    for capture in captures:
        _capture_target(capture)
        groups[capture["key"]].append(capture)
    validate_lighting(captures, manager.build)
    for key, group in groups.items():
        sample = group[0]
        if any(capture["target"] != sample["target"] for capture in group):
            raise ValueError("Fixed reference physical target key collision")
        asset_hash = sample["target"]["asset_sha256"]
        if asset_hash not in manager.assets:
            scene = {**sample["config"]["scene"],
                     "registry": sample["manifest"]["scene"]["registry"]}
            manager.assets[asset_hash] = validate_assets(scene)
        assets = manager.assets[asset_hash]
        if assets["sha256"] != asset_hash:
            raise ValueError("Reference assets differ from the captured target")
        previous_record = manager.index["references"].get(key, {})
        if previous_record.get("policy_id") == POLICY_ID:
            fixed_record_paths(manager.directory, previous_record)
        directory = manager.directory / "bistro" / key
        image = checkpoint_image(directory, FIXED_SEED, FIXED_SAMPLES, BATCH_SAMPLES)
        if image is None:
            previous_samples, previous_image, previous_totals = _highest_checkpoint(
                directory, sample, manager.build)
            if manager.before_segment is not None:
                manager.before_segment()
            timeout = manager.timeout if manager.before_segment is None else lambda: min(
                manager.timeout, manager.before_segment())
            manager.notify(stage="reference", target=key, scene="bistro", stream_seed=FIXED_SEED,
                samples=FIXED_SAMPLES, reference_batch_counts=dict(CLASS_COUNTS),
                reference_sample_count_unit=PROGRESS_UNIT, reference_policy=policy_metadata())
            config = reference_config(sample["config"], sample["frame"], [FIXED_SAMPLES],
                BATCH_SAMPLES, FIXED_SEED, "POWER_RIS", previous_samples=previous_samples,
                resume_image=previous_image, class_counts=CLASS_COUNTS,
                previous_class_samples=previous_totals)
            if previous_image is not None:
                config["reference"].update(resume_image_sha256=sha(previous_image),
                    resume_config_sha256=sha(previous_image.with_name("config.json")))
            checkpoint = directory / f"seed-{FIXED_SEED}/checkpoint-{FIXED_SAMPLES}"
            attempt_number = 0
            while (checkpoint / f"attempt-{attempt_number}").exists():
                attempt_number += 1
            attempt = checkpoint / f"attempt-{attempt_number}"
            run_one(config, attempt, manager.build, assets, timeout, executable=REFERENCE_EXE)
            image = pfm_path(attempt / f"frame-{FIXED_SAMPLES // BATCH_SAMPLES:04d}")
        config = _validate_chain(directory, image, sample, FIXED_SAMPLES, manager.build)
        if config["reference"].get("allocation", {}).get("batch_counts") != CLASS_COUNTS:
            raise ValueError("Fixed Bistro reference final batch allocation differs")
        metadata_path = directory / "fixed-policy.json"
        if metadata_path.exists():
            validate_bistro_policy(_read_json(metadata_path))
        else:
            save_json(metadata_path, policy_metadata())
        record = {"target": sample["target"], "policy_id": POLICY_ID,
            "ready": True, "converged": None, "precision_verified": False,
            "precision_checks": "not_evaluated", "uncertainty_checks": "not_evaluated",
            "seeds": [FIXED_SEED], "samples": FIXED_SAMPLES, "sample_count_unit": PROGRESS_UNIT,
            "batch_counts": dict(CLASS_COUNTS), "resolution": [1920, 1080],
            "reference_policy": policy_metadata(),
            "class_samples_by_stream": {str(FIXED_SEED): allocation_totals(config)}}
        for name, path in (("image", image), ("config", image.with_name("config.json")),
                           ("manifest", image.with_name("manifest.json")),
                           ("policy_metadata", metadata_path)):
            record[name] = relative_path(path, manager.directory)
            record[f"{name}_sha256"] = sha(path)
        record.update(stream_images=[record["image"]], stream_sha256=[record["image_sha256"]])
        fixed_record_paths(manager.directory, record)
        manager.index["references"][key] = record
        save_json(manager.index_path, manager.index)
        manager.notify(stage="reference_ready", target=key, samples=FIXED_SAMPLES,
                       reference_policy=policy_metadata(), precision_verified=False)
    return {key: fixed_record_paths(manager.directory, manager.index["references"][key]) for key in groups}
