"""Launch the controlled PDF campaign, enforcing its directory and authorization gates."""
import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import traceback
from rtxdi_common import ROOT
from experiment.artifacts import save_json
from experiment.controlled_budget import BudgetExceeded
from experiment.controlled_launch import validate_launch_plan, claim_launch, load_scene_reference_policies
from experiment.controlled_evaluation import validate_reference_priority_scenes
from experiment.controlled_runner import ControlledExperiment


def suite_path(name):
    availability = ROOT / "runs/pdf-similarity-archive/artifact-availability.json"
    if availability.is_file():
        retired = json.loads(availability.read_text(encoding="utf-8"))
        if name == Path(retired["historical_root"]).name:
            raise ValueError("This campaign is archived in runs/pdf-similarity-archive; use scripts/analysis/pdf_archive.py for verification. Start new renders under a new approved campaign name.")
    if not re.fullmatch(r"pdf-controlled-[A-Za-z0-9_-]+", name):
        raise ValueError("Use a dedicated pdf-controlled-* directory under runs/")
    unresolved = ROOT / "runs" / name
    path = unresolved.resolve()
    if path.parent != (ROOT / "runs").resolve() or unresolved.is_symlink() or path.name != name:
        raise ValueError("Controlled suite must remain directly inside runs/")
    return path


@contextmanager
def exclusive_worker(directory):
    """The OS releases this named mutex even after an interrupted worker."""
    if os.name != "nt":
        raise RuntimeError("This D3D12 experiment worker requires Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    identity = hashlib.sha256(str(directory.resolve()).lower().encode()).hexdigest()[:24]
    ctypes.set_last_error(0)
    handle = kernel.CreateMutexW(None, True, "Local\\restir-pdf-" + identity)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        raise RuntimeError("Another worker already owns this experiment suite")
    try:
        yield
    finally:
        kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-name", default="pdf-controlled-20261018")
    parser.add_argument("--pilot-only", action="store_true", help="Validate the technical pilot without generating references")
    parser.add_argument("--references-only", action="store_true", help="Reuse all 78 methods and run fixed sparse reference evaluation")
    parser.add_argument("--reference-window", type=Path, help="Explicitly approved reference/analysis budget authorization")
    parser.add_argument("--validate-only", action="store_true", help="Validate retained methods and sparse targets without rendering")
    parser.add_argument("--launch-plan", type=Path, help="Pinned one-time scheduled launch inputs")
    parser.add_argument("--reference-policy", type=Path, help="Explicit fixed Bistro reference policy")
    args = parser.parse_args()
    if args.references_only != (args.reference_window is not None):
        parser.error("--references-only requires --reference-window, and the window only authorizes references")
    if (args.validate_only or args.launch_plan) and not args.references_only:
        parser.error("Validation and scheduled launch require --references-only")
    if args.reference_policy is not None and not args.references_only:
        parser.error("A reference policy requires --references-only")
    if args.reference_policy is not None and not args.validate_only:
        parser.error("--reference-policy is validation-only; execution requires a pinned --launch-plan")
    if args.pilot_only and args.references_only:
        parser.error("References-only must reuse its completed technical validation")
    if args.validate_only and args.launch_plan:
        parser.error("Validate preparation separately; do not consume a scheduled launch")
    root = suite_path(args.output_name)
    with exclusive_worker(root):
        if args.launch_plan and args.launch_plan.with_name(args.launch_plan.name + ".started.json").exists():
            print("One-time launch was already consumed; preserving saved experiment state.", flush=True)
            return
        worker = None
        try:
            plan = validate_launch_plan(root, args.launch_plan) if args.launch_plan else None
            priority = validate_reference_priority_scenes(
                plan.get("reference_priority_scenes", []) if plan is not None else [])
            policies = load_scene_reference_policies(root, plan, policy_path=args.reference_policy)
            worker = ControlledExperiment(root, reference_window=args.reference_window,
                                          validation_only=args.validate_only, reference_policies=policies)
            worker.reference_priority_scenes = priority
            if plan is not None:
                authorization = worker.budget.record["authorization"]
                if any(plan[key] != authorization[key] for key in ("not_before_utc", "deadline_utc")):
                    raise ValueError("Launch plan and approved budget window differ")
                worker.sparse_inputs()
                claim_launch(args.launch_plan)
            worker.execute(args.pilot_only, references_only=args.references_only, validate_only=args.validate_only)
        except BaseException as error:
            status = "failed"
            if isinstance(error, BudgetExceeded):
                status = "budget_exhausted"
            elif worker is not None and not args.validate_only:
                try:
                    worker.budget.check()
                except BudgetExceeded as exhausted:
                    status, error = "budget_exhausted", exhausted
            if worker is not None:
                worker.notify(status=status, error=str(error), traceback=traceback.format_exc())
            else:
                root.mkdir(parents=True, exist_ok=True)
                path = root / "state.json"
                try:
                    state = json.loads(path.read_text()) if path.exists() else {}
                except (OSError, ValueError):
                    state = {}
                state.update(status=status, worker_pid=os.getpid(), error=str(error),
                             traceback=traceback.format_exc(), updated_utc=datetime.now(timezone.utc).isoformat())
                save_json(path, state)
            if status == "budget_exhausted":
                return
            raise



if __name__ == "__main__":
    main()
