"""Fail-closed checks and exclusive claims for a one-time reference launch."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil

from rtxdi_common import sha
from .controlled_budget import _utc


def validate_launch_plan(directory, path, *, now=None, free_bytes=None):
    directory, path = Path(directory).resolve(), Path(path).resolve()
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("version") != 1 or Path(plan["suite_root"]).resolve() != directory:
        raise ValueError("Launch plan belongs to a different suite")
    current = _utc(now or datetime.now(timezone.utc), "launch time")
    if not _utc(plan["not_before_utc"], "launch start") <= current < _utc(plan["deadline_utc"], "launch deadline"):
        raise ValueError("Outside the explicitly approved launch window")
    minimum = plan.get("minimum_free_bytes")
    if type(minimum) is not int or minimum <= 0:
        raise ValueError("Launch plan needs a positive disk reserve")
    available = shutil.disk_usage(directory).free if free_bytes is None else free_bytes
    if available < minimum:
        raise ValueError("Insufficient free disk space for reference launch")
    inputs = plan.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        raise ValueError("Launch plan needs pinned inputs")
    for name, digest in inputs.items():
        source = Path(name)
        if not source.is_absolute() or not source.is_file() or sha(source) != digest:
            raise ValueError(f"Prepared launch input changed or disappeared: {name}")
    return plan


def load_scene_reference_policies(directory, plan=None, *, policy_path=None):
    """Select only an explicitly approved, pinned, suite-local scene override.

    A saved override prevents legacy launches from silently restoring the old
    policy. An explicit path without a plan is reserved for validation-only use.
    The authorization binds the unchanged original budget and absolute window.
    """
    from .bistro_fixed_reference import validate_bistro_policy

    directory = Path(directory).resolve()
    declared = plan.get("reference_policy_file") if plan is not None else None
    if plan is not None and policy_path is not None:
        if declared is None or Path(declared).resolve() != Path(policy_path).resolve():
            raise ValueError("Explicit policy path differs from the launch plan")
    selected = declared if declared is not None else policy_path
    if selected is None:
        if (directory / "reference-policy.json").exists():
            raise ValueError("Saved reference policy requires explicit launch selection")
        return {}
    path = Path(selected)
    if (not path.is_absolute() or path.is_symlink() or not path.is_file()
            or not path.resolve().is_relative_to(directory)):
        raise ValueError("Reference policy must be a regular file inside its suite")
    path = path.resolve()
    if plan is not None:
        inputs = plan.get("inputs", {})
        if not isinstance(inputs, dict) or inputs.get(str(path)) != sha(path):
            raise ValueError("Reference policy is not pinned by this launch plan")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if (not isinstance(value, dict) or type(value.get("version")) is not int
                or value["version"] != 1
                or value.get("scope") != "bistro_fixed_single_stream_reference"
                or value.get("approved_by") != "user"):
            raise ValueError("Reference policy needs explicit user authorization")
        approved = _utc(value.get("approved_utc"), "reference policy approval")
        if approved > datetime.now(timezone.utc):
            raise ValueError("Reference policy approval is in the future")
        scenes = value.get("scene_reference_policies")
        if not isinstance(scenes, dict) or set(scenes) != {"bistro"}:
            raise ValueError("Only Bistro has an approved reference override")
        policy = validate_bistro_policy(scenes["bistro"])
        for filename, field in (("reference-window.json", "reference_window_sha256"),
                                ("execution-budget.json", "execution_budget_sha256")):
            bound = directory / filename
            if not bound.is_file() or value.get(field) != sha(bound):
                raise ValueError(f"Reference policy budget/window binding differs: {filename}")
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Invalid approved reference policy: {error}") from error
    return {"bistro": policy}


def claim_launch(path):
    """Consume only after all preflight checks, while holding the suite mutex."""
    path = Path(path)
    with path.with_name(path.name + ".started.json").open("x", encoding="utf-8") as stream:
        json.dump({"pid": os.getpid(), "started_utc": datetime.now(timezone.utc).isoformat(),
                   "launch_plan_sha256": sha(path)}, stream, indent=2)
        stream.write("\n")
