"""Exact-budget single-stream references; paired precision references stay separate."""
import copy
import json
import math
from pathlib import Path

from rtxdi_common import RENDERER, sha
from .artifacts import save_json
from .config import NEE_SAMPLE_COUNTS
from .images import read_pfm
from .reference import reference_config, target_key, validate_lighting
from .reference_allocation import allocation_totals, count_map, PROGRESS_UNIT
from .reference_runner import BUILD_FIELDS, checkpoint_image, validate_checkpoint
from .runner import relative_path, run_one, frozen_input_guard

EXE = RENDERER / "build/bin/FullSampleReference.exe"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_policy(policy):
    fields = {"kind","seed","local_samples","max_local_samples","batch_counts","checkpoints","local_sampling"}
    if not isinstance(policy, dict) or set(policy) != fields or policy["kind"] != "fixed_budget":
        raise ValueError("Invalid fixed-budget reference policy")
    counts = count_map(policy["batch_counts"], minimum=1, maximum=64)
    seed, samples, cap = (policy[k] for k in ("seed","local_samples","max_local_samples"))
    batch = counts["local"]
    if (type(seed) is not int or not 0 <= seed <= 4095 or type(samples) is not int
            or type(cap) is not int or not 2*batch <= samples <= cap <= 1048576*batch
            or samples % batch or cap % batch or policy["local_sampling"] not in NEE_SAMPLE_COUNTS):
        raise ValueError("Invalid fixed-budget seed, sample target, cap or sampling mode")
    checkpoints = policy["checkpoints"]
    if (not isinstance(checkpoints,list) or not checkpoints or checkpoints[-1] != samples
            or any(type(n) is not int or n < 2*batch or n > samples or n % batch for n in checkpoints)
            or any(b <= a for a,b in zip(checkpoints,checkpoints[1:]))):
        raise ValueError("Fixed-budget checkpoints must increase to the exact target within the cap")
    return copy.deepcopy(policy)


def make_config(sample, policy, samples, previous=None):
    policy = validate_policy(policy)
    if samples not in policy["checkpoints"]:
        raise ValueError("Checkpoint not in the fixed-budget policy")
    base = copy.deepcopy(sample["config"])
    base["definition"]["geometry_export"] = False
    parent = read_json(previous.parent/"config.json") if previous else None
    totals = allocation_totals(parent) if parent else None
    config = reference_config(base, sample["frame"], [samples], policy["batch_counts"]["local"],
        policy["seed"], policy["local_sampling"], previous_samples=totals["local"] if totals else 0,
        resume_image=previous, class_counts=policy["batch_counts"], previous_class_samples=totals)
    if previous:
        config["reference"].update(resume_image_sha256=sha(previous),
                                   resume_config_sha256=sha(previous.parent/"config.json"))
    return config


def validate_chain(directory, image, sample, policy, samples, build):
    """Validate the full ancestry, exact allocation/build/target and FP32 HDR payload."""
    policy = validate_policy(policy)
    batch, seed = policy["batch_counts"]["local"], policy["seed"]
    if samples not in policy["checkpoints"]:
        raise ValueError("Reference checkpoint exceeds or differs from the fixed budget")
    expected = checkpoint_image(directory, seed, samples, batch)
    if expected is None or Path(image).resolve() != expected.resolve():
        raise ValueError("Fixed reference must use its exact completed single-stream checkpoint")
    config = read_json(image.parent/"config.json")
    ref = config.get("reference", {})
    previous = ref.get("resume_batches",0)*batch
    if type(previous) is not int or not 0 <= previous < samples:
        raise ValueError("Invalid reference accumulation history")
    parent_image = None
    if previous:
        parent_image = checkpoint_image(directory,seed,previous,batch)
        if parent_image is None:
            raise ValueError("Missing reference parent checkpoint")
        validate_chain(directory,parent_image,sample,policy,previous,build)
    validate_checkpoint(image,sample,seed,samples,batch,build,
                        previous_samples=previous,previous_image=parent_image,sampling=policy["local_sampling"])
    expected_counts = {k:v*(samples//batch) for k,v in policy["batch_counts"].items()}
    if (allocation_totals(config) != expected_counts
            or ref.get("accumulation") != "FP32 running mean"
            or ref.get("allocation",{}).get("batch_counts") != policy["batch_counts"]):
        raise ValueError("Fixed reference accumulation or light-class allocation differs")
    width,height = sample["target"]["resolution"]
    if read_pfm(image).shape != (height,width,3):
        raise ValueError("Fixed reference HDR dimensions differ from target")
    return config


def reference_timeout(iterations, previous_iterations, observed):
    """Four times observed wall throughput plus startup, never a method-run timeout."""
    if not 0 <= previous_iterations < iterations:
        raise ValueError("Invalid reference iteration range")
    seconds_per_iteration = 2.0  # Conservative startup estimate until first checkpoint.
    if observed is not None:
        if (observed["iterations"] <= 0 or not math.isfinite(observed["seconds"])
                or observed["seconds"] <= 0):
            raise ValueError("Invalid observed reference throughput")
        seconds_per_iteration = observed["seconds"]/observed["iterations"]
    return max(600, math.ceil(120 + 4*(iterations-previous_iterations)*seconds_per_iteration))


def reference_record(root, sample, policy, image, build):
    config = validate_chain(root/sample["key"],image,sample,policy,policy["local_samples"],build)
    record = {"target":sample["target"],"ready":True,"converged":None,
        "precision_verified":False,"precision_checks":"not_evaluated","seeds":[policy["seed"]],
        "samples":policy["local_samples"],"sample_count_unit":PROGRESS_UNIT,
        "batch_counts":policy["batch_counts"],"iterations":policy["local_samples"]//policy["batch_counts"]["local"],
        "cumulative_samples":allocation_totals(config)}
    for field,path in (("image",image),("config",image.parent/"config.json"),("manifest",image.parent/"manifest.json")):
        record[field] = relative_path(path,root)
        record[field+"_sha256"] = sha(path)
    return record


def ensure_reference(root, sample, policy, build, assets, *, progress=None, input_guard=None):
    """Serial checkpoint execution; failures require diagnosis, never an implicit retry."""
    root = Path(root).resolve()
    policy = validate_policy(policy)
    validate_lighting([sample],build)
    if sample["key"] != target_key(sample["target"]) or assets["sha256"] != sample["target"]["asset_sha256"]:
        raise ValueError("Reference target or assets differ")
    directory = root/sample["key"]
    previous_image, observed = None,None
    for samples in policy["checkpoints"]:
        batch = policy["batch_counts"]["local"]
        image = checkpoint_image(directory,policy["seed"],samples,batch)
        if image is None:
            checkpoint = directory/f"seed-{policy['seed']}/checkpoint-{samples}"
            if checkpoint.exists():
                raise RuntimeError(f"Incomplete checkpoint requires diagnosis before recovery: {checkpoint}")
            config = make_config(sample,policy,samples,previous_image)
            previous_iterations = config["reference"].get("resume_batches",0)
            timeout = reference_timeout(samples//batch,previous_iterations,observed)
            if progress:
                progress({"status":"rendering","target":sample["key"],"local_samples_completed":previous_iterations*batch,
                          "local_samples_target":samples,"timeout_seconds":timeout,"observed":observed})
            attempt = checkpoint/"attempt-1"
            guard=frozen_input_guard(config,EXE,build,assets,input_guard)
            run_one(config,attempt,build,assets,timeout,executable=EXE,input_guard=guard)
            image = checkpoint_image(directory,policy["seed"],samples,batch)
        config = validate_chain(directory,image,sample,policy,samples,build)
        manifest = read_json(image.parent/"manifest.json")
        observed = {"iterations":len(config["frames"]),
                    "seconds":manifest["wall_seconds_including_startup_and_export"]}
        previous_image = image
        if progress:
            progress({"status":"checkpoint_completed","target":sample["key"],
                      "local_samples_completed":samples,"local_samples_target":policy["local_samples"],
                      "observed":observed})
    return reference_record(root,sample,policy,previous_image,build)


def load_references(index_path, captures, *, expected_policy=None, expected_build=None):
    """Read-only: fixed ready never implies converged, and no averaged substitute is accepted."""
    index_path = Path(index_path).resolve()
    root, index = index_path.parent, read_json(index_path)
    if index.get("schema_version") != 1 or index.get("kind") != "fixed_budget_references":
        raise ValueError("Unsupported fixed-budget reference index")
    policy = validate_policy(index["policy"])
    if expected_policy is not None and policy != validate_policy(expected_policy):
        raise ValueError("Reference budget differs from the requested fixed policy")
    build = index["build"]
    if any(k not in build for k in BUILD_FIELDS) or (expected_build is not None and
            any(build[k] != expected_build.get(k) for k in BUILD_FIELDS)):
        raise ValueError("Reference build differs from the frozen build")
    validate_lighting(captures,build)
    for sample in captures:
        row = index["references"].get(sample["key"])
        if row is None or row.get("target") != sample["target"]:
            raise ValueError("Missing or incompatible fixed reference target")
        image = (root/row["image"]).resolve()
        if not image.is_relative_to(root):
            raise ValueError("Fixed reference path leaves its suite")
        expected = reference_record(root,sample,policy,image,build)
        if row != expected:
            raise ValueError("Fixed reference record, precision status or artifact hashes differ")
    return index["references"]
