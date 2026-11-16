"""Configure and run the approved six-view, four-method ReSTIR PT comparison."""
import argparse
import csv
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess

from . import spatial_capture as capture, spatial_measure as measure, spatial_inputs as inputs
from . import run, capture_lifecycle
from .process_utils import exclusive_operation, check_renderer_idle

ROOT = capture.ROOT
DEFAULT_CONFIG = ROOT / "experiments/configs/pt-6-views-spatial-compare.json"
METHODS = {"temporal-off": ("baseline", False), "temporal-on": ("baseline", True),
           "cgns": ("cgns", True), "pdf": ("pdf-similarity", True)}


def workspace_path(value):
    """Config paths are portable, repository-relative, existing inputs."""
    if not isinstance(value, str) or "\\" in value or ":" in value:
        raise ValueError("Expected a repository-relative input path")
    path = (ROOT / value).resolve(strict=True)
    if Path(value).is_absolute() or ".." in Path(value).parts or not path.is_relative_to(ROOT):
        raise ValueError("Input path escapes repository")
    return path


def plan(config_path=DEFAULT_CONFIG):
    path = Path(config_path).resolve(strict=True)
    raw = path.read_bytes()
    spec = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=capture.settings._unique_object)
    keys = {"schema_version", "name", "base_experiment", "views", "methods",
            "warmup_frames", "quality_frames", "timing_frames", "quality_seed_offsets", "timing_seed_offset"}
    if (set(spec) != keys or type(spec["schema_version"]) is not int or spec["schema_version"] != 2
            or spec["name"] != "pt-6-views-spatial-compare"):
        raise ValueError("Unsupported fixed-view suite configuration")
    seeds = spec["quality_seed_offsets"]
    if (not isinstance(seeds, list) or len(seeds) != 4
            or any(type(seed) is not int or seed < 0 for seed in seeds)
            or len(set(seeds)) != 4):
        raise ValueError("Expected four distinct nonnegative quality seed offsets")
    if type(spec["timing_seed_offset"]) is not int or spec["timing_seed_offset"] != 0:
        raise ValueError("Timing uses one realization with seed offset zero")
    if (not isinstance(spec["methods"], list) or len(spec["methods"]) != 4
            or set(spec["methods"]) != set(METHODS)):
        raise ValueError("Expected exactly the four approved method labels")
    views = spec["views"]
    if not isinstance(views, list) or len(views) != 6 or len(set(views)) != 6:
        raise ValueError("Expected six distinct fixed-view configurations")
    view_paths = [workspace_path(v) for v in views]
    if len({p.stem for p in view_paths}) != 6:
        raise ValueError("View names must be unique")
    base, digest = capture.settings.load_config_snapshot(workspace_path(spec["base_experiment"]))
    experiments = {}
    for phase in ("quality", "timing"):
        capture.capture_schedule(spec["warmup_frames"], spec[phase + "_frames"])
        value = json.loads(json.dumps(base))
        value["name"] = spec["name"] + "-" + phase
        value["render"].update(warmup_frames=spec["warmup_frames"], capture_count=spec[phase + "_frames"])
        experiments[phase] = capture.settings.validate_config(value)
    if "pdf-similarity" not in base["methods"]:
        raise ValueError("PDF similarity is missing from the base experiment")
    last_quality_frame = spec["warmup_frames"] + spec["quality_frames"]
    for seed in seeds:
        capture.seed_record(last_quality_frame, seed_offset=seed)
    ordered_seeds = sorted(seeds)
    if any(b - a < last_quality_frame for a, b in zip(ordered_seeds, ordered_seeds[1:])):
        raise ValueError("Quality seed ranges overlap")
    jobs = []
    for index, view in enumerate(view_paths):
        # Rotate method order across scenes; never run renderers concurrently.
        labels = spec["methods"][index % 4:] + spec["methods"][:index % 4]
        for label in labels:
            method, temporal = METHODS[label]
            jobs.append({"id": view.stem + "/" + label, "view": view.stem, "label": label,
                         "view_config": view.relative_to(ROOT).as_posix(),
                         "method": method, "temporal_reuse": temporal})
    return {"name": spec["name"], "suite_config": path.relative_to(ROOT).as_posix(),
            "suite_config_sha256": hashlib.sha256(raw).hexdigest(),
            "base_config": spec["base_experiment"], "base_config_sha256": digest,
            "experiments": experiments, "quality_seed_offsets": seeds, "timing_seed_offset": 0,
            "quality_frames": capture.capture_schedule(spec["warmup_frames"], spec["quality_frames"]),
            "timing_frames": capture.capture_schedule(spec["warmup_frames"], spec["timing_frames"]),
            "timing_render_frames": spec["warmup_frames"] + spec["timing_frames"] + 1,
            "jobs": jobs}


def phase_jobs(planned, phase):
    """Expand independent quality realizations; timing remains one run per method."""
    if phase not in ("quality", "timing"):
        raise ValueError("Unknown experiment phase")
    offsets = planned["quality_seed_offsets"] if phase == "quality" else [planned["timing_seed_offset"]]
    for offset in offsets:
        for job in planned["jobs"]:
            run_id = job["id"] + "/" + phase
            if phase == "quality":
                run_id += f"/seed-{offset:06d}"
            yield {**job, "run_id": run_id, "seed_offset": offset}


def check_inputs(planned):
    """Read and verify the six current views and existing references; no renderer."""
    catalog = inputs.reference_catalog(planned["experiments"]["quality"], require_images=True)
    result, keys = {}, set()
    for job in planned["jobs"]:
        if job["view"] in result:
            continue
        path = workspace_path(job["view_config"])
        config = capture.views.load_config(path)
        key = config["scene_id"], config["view_id"]
        item = catalog[key]
        if config != item["config"]:
            raise ValueError("Suite view differs from the frozen view: " + job["view"])
        capture.reference_extension_batch.recheck_view(item["entry"], config)
        keys.add(key)
        result[job["view"]] = {
            "scene_id": key[0], "view_id": key[1], "adapted": item["entry"]["adapted"],
            "config_path": job["view_config"], "config_sha256": run.sha(path),
            "resolved_config": config, "asset_sha256": item["entry"]["asset_sha256"],
            "source_sha256": item["entry"]["source_sha256"],
            "reference": {"path": Path(item["reference"]["path"]).relative_to(ROOT).as_posix(),
                          "sha256": item["reference"]["sha256"]}}
    if keys != set(catalog):
        raise ValueError("Suite must cover the six frozen views exactly once")
    return result


def identity(planned, views):
    files = {Path(__file__), Path(measure.__file__), Path(capture.__file__), Path(inputs.__file__)}
    for method in ("baseline", "cgns", "pdf-similarity"):
        files.update(capture.dependency_files(method))
    files.add(workspace_path(planned["experiments"]["quality"]["reference_catalog"]))
    return {"plan": planned, "views": views,
            "source_sha256": {p.relative_to(ROOT).as_posix(): run.sha(p) for p in sorted(files)}}


def environment():
    gpu = subprocess.check_output([
        "nvidia-smi",
        "--query-gpu=name,uuid,driver_version,memory.total,memory.used,temperature.gpu,clocks.sm,power.draw",
        "--format=csv"], text=True).strip()
    return {"utc": datetime.now(timezone.utc).isoformat(), "os": platform.platform(),
            "python": platform.python_version(), "gpu_snapshot_csv": gpu,
            "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "git_status": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True),
            "gpu_snapshot_note": "Point-in-time observations; not peak VRAM or a continuous telemetry trace"}


def batch_path(output):
    path = Path(output).resolve()
    base = ROOT / "runs/pt-fixed-view-batches"
    if not path.is_relative_to(base) or path == base:
        raise ValueError("Use a new batch subdirectory under runs/pt-fixed-view-batches")
    for parent in (path, *path.parents):
        if not parent.is_relative_to(base):
            break
        manifest = parent / "manifest.json"
        if manifest.is_file() and json.loads(manifest.read_text(encoding="utf8")).get("kind") == "falcor_pt_stage_archive":
            raise ValueError("A capture batch cannot be nested inside a stage archive")
    return path


def runtime_key(method, adapted):
    return method + (":gltf-v3" if adapted else ":reference")


def diagnostics_off():
    capture_lifecycle.check_shader_environment()
    if os.environ.get("RESTIR_LAB_CGNS_VERIFY_IDS") == "1":
        raise ValueError("Disable CGNS ID diagnostics before this experiment")


def prepare(config_path, output):
    output = batch_path(output)
    if output.exists():
        raise ValueError("Batch already exists; run/resume it or choose a new batch ID")
    diagnostics_off()
    check_renderer_idle()
    planned = plan(config_path)
    views = check_inputs(planned)
    input_identity = identity(planned, views)
    experiment = planned["experiments"]["quality"]
    paths = inputs.prepare_runtimes(experiment, compare_method="cgns")
    paths.update(inputs.prepare_runtimes(experiment, compare_method="pdf-similarity"))
    snapshots = inputs.runtime_snapshots(experiment, paths)
    runtimes = {runtime_key(method, adapted): {"path": path.relative_to(ROOT).as_posix(),
                 "verification": snapshots[method, adapted]} for (method, adapted), path in paths.items()}
    if identity(plan(config_path), check_inputs(planned)) != input_identity:
        raise ValueError("Experiment inputs changed while preparing runtimes")
    output.mkdir(parents=True, exist_ok=False)
    (output / "configs").mkdir()
    for phase, config in planned["experiments"].items():
        run.save(output / "configs" / (phase + ".json"), config)
    run.save(output / "config.resolved.json", planned)
    run.save(output / "references.json", {v: item["reference"] for v, item in views.items()})
    run.save(output / "environment.json", environment())
    state = {"schema_version": 1, "kind": "falcor_pt_six_view_comparison", "status": "prepared",
             "identity": input_identity, "runtimes": runtimes, "jobs": {},
             "metric_support": {"smape": "reference and HDR required",
                "frame_and_stage_times": "64 delayed GPU timestamp samples per timing run",
                "spatial_relative_covariance": "four independent quality realizations; no reference required",
                "temporal_relative_covariance": "four aligned 16-frame quality sequences; no reference required"}}
    capture_lifecycle.atomic_json(output / "manifest.json", state)
    return output / "manifest.json"


def timing_csv(directory, schedule):
    rows = json.loads((directory / "timings.json").read_text(encoding="utf8"))
    selected = [r for r in rows if r["gpu_measured_frame"] in schedule]
    events = sorted({k for r in selected for k in r["events_previous_frame"] if k.endswith("/gpu_time")})
    wall = {r["rendered_frame"]: r["render_wall_ms_current_frame"] for r in rows}
    with (directory / "frames.csv").open("w", newline="", encoding="utf8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["frame", "render_wall_ms"] + events)
        writer.writeheader()
        for row in selected:
            frame = row["gpu_measured_frame"]
            writer.writerow({"frame": frame, "render_wall_ms": wall[frame],
                             **{k: row["events_previous_frame"][k]["value"]
                                for k in events if k in row["events_previous_frame"]}})


def verify_attempt(directory, job, phase, planned, config_path, view, runtime):
    meta = json.loads((directory / "manifest.json").read_text(encoding="utf8"))
    experiment = planned["experiments"][phase]
    schedule = planned[phase + "_frames"]
    seed_offset = job["seed_offset"]
    options = capture.graph_options(job["method"], experiment, temporal_reuse=job["temporal_reuse"])
    expected = {"status": "completed", "requested_method": job["method"],
                "temporal_reuse": job["temporal_reuse"], "experiment_config": experiment,
                "experiment_config_sha256": run.sha(config_path),
                "requested_graph_options": options, "capture_frames": schedule,
                "resolution": [1920, 1080], "seed_policy": capture.seed_policy(job["temporal_reuse"], seed_offset),
                "scene_id": view["scene_id"], "view_id": view["view_id"],
                "runtime_verification": runtime["verification"], "runtime": runtime["path"]}
    if meta.get("seed_offset", 0) != seed_offset or any(meta.get(k) != value for k, value in expected.items()):
        raise ValueError("Completed attempt identity differs: " + str(directory))
    if run.sha(directory / "render.py") != meta["render_script_sha256"]:
        raise ValueError("Generated render script changed")
    if phase == "quality":
        inputs.validate_artifacts(directory, meta["artifacts"], schedule, 1920, 1080,
                                    temporal_reuse=job["temporal_reuse"], seed_offset=seed_offset)
        last_frame = schedule[-1]
    else:
        if meta.get("save_hdr") or meta.get("drain_last_frame") is not True or list(directory.glob("*.exr")):
            raise ValueError("Timing must be HDR-free with final timestamp drainage")
        validation = measure.validate_timings(directory / "timings.json", schedule, drain_last_frame=True)
        if validation != json.loads((directory / "timing-validation.json").read_text(encoding="utf8")):
            raise ValueError("Timing validation changed")
        last_frame = schedule[-1] + 1
    capture.verify_scene_records(directory, view["resolved_config"], options, last_frame, view["adapted"])
    names = ["manifest.json", "render.py", "resolved.py", "resolved-camera.json", "scene-state.json",
             "scene-audit.json", "timings.json", "timing-validation.json", "frames.csv"]
    return {name: run.sha(directory / name) for name in names if (directory / name).is_file()}


def execute(config_path, output, *, retry_failed=False):
    output = batch_path(output)
    diagnostics_off()
    state_path = output / "manifest.json"
    state = json.loads(state_path.read_text(encoding="utf8"))
    planned = plan(config_path)
    views = check_inputs(planned)
    if identity(planned, views) != state["identity"]:
        raise ValueError("Inputs changed since preparation; use a new batch")
    for phase, config in planned["experiments"].items():
        if capture.settings.load_config(output / "configs" / (phase + ".json")) != config:
            raise ValueError("Prepared configuration snapshot changed")
    verified_runtimes = set()
    for job in planned["jobs"]:
        adapted = views[job["view"]]["adapted"]
        key = runtime_key(job["method"], adapted)
        if key in verified_runtimes:
            continue
        verified_runtimes.add(key)
        print("Verifying runtime:", key, flush=True)
        record = state["runtimes"][runtime_key(job["method"], adapted)]
        parameters = (planned["experiments"]["quality"]["methods"][job["method"]]["shader"]
                      if job["method"] != "baseline" else None)
        if capture.validate_runtime(workspace_path(record["path"]), job["method"], adapted, parameters) != record["verification"]:
            raise ValueError("Prepared runtime changed")
    state["status"] = "running"
    state.pop("error", None)
    capture_lifecycle.atomic_json(state_path, state)
    active_record = None
    try:
        # Export all quality data before the uninterrupted timing jobs.
        for phase in ("quality", "timing"):
            config_path_phase = output / "configs" / (phase + ".json")
            for job in phase_jobs(planned, phase):
                key = job["run_id"]
                attempt, exists = capture_lifecycle.choose_attempt(output / "jobs" / key, retry_failed=retry_failed)
                view = views[job["view"]]
                runtime = state["runtimes"][runtime_key(job["method"], view["adapted"])]
                previous = state["jobs"].get(key, {})
                print(key, "validating completed attempt" if exists else "starting", flush=True)
                if not exists:
                    state["jobs"][key] = {"status": "running", "seed_offset": job["seed_offset"],
                                          "attempt": attempt.relative_to(output).as_posix()}
                    active_record = state["jobs"][key]
                    try:
                        capture_lifecycle.atomic_json(state_path, state)
                        active_record["environment_before"] = environment()
                        capture_lifecycle.atomic_json(state_path, state)
                        arguments = dict(config_path=workspace_path(job["view_config"]), output=attempt,
                                         runtime=workspace_path(runtime["path"]), method=job["method"],
                                         experiment_path=config_path_phase, temporal_reuse=job["temporal_reuse"])
                        if phase == "quality":
                            capture.launch(**arguments, seed_offset=job["seed_offset"])
                        else:
                            measure.launch(**arguments, drain_last_frame=True)
                            timing_csv(attempt, planned["timing_frames"])
                    except BaseException as error:
                        capture_lifecycle.preserve_failure(attempt, error)
                        raise
                hashes = verify_attempt(attempt, job, phase, planned, config_path_phase, view, runtime)
                if phase == "timing" and "frames.csv" not in hashes:
                    # Recover a crash between validated GPU completion and CSV export.
                    timing_csv(attempt, planned["timing_frames"])
                    hashes["frames.csv"] = run.sha(attempt / "frames.csv")
                if exists and previous.get("status") == "completed" and previous.get("files_sha256") != hashes:
                    raise ValueError("Completed attempt files changed")
                state["jobs"][key] = {**state["jobs"].get(key, {}), "status": "completed",
                                     "seed_offset": job["seed_offset"],
                                     "attempt": attempt.relative_to(output).as_posix(), "files_sha256": hashes}
                capture_lifecycle.atomic_json(state_path, state)
                active_record = None
        if identity(plan(config_path), check_inputs(planned)) != state["identity"]:
            raise ValueError("Inputs changed during experiment")
        state["status"] = "completed"
        run.save(output / "environment-final.json", environment())
    except BaseException as error:
        state.update(status="failed", error=str(error))
        if active_record is not None:
            active_record.update(status="failed", error=str(error))
        raise
    finally:
        capture_lifecycle.atomic_json(state_path, state)
    return state_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in ("plan", "check", "prepare", "run"):
        modes.add_argument("--" + mode, action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    if args.plan:
        print(json.dumps(plan(args.config), indent=2))
    elif args.check:
        views = check_inputs(plan(args.config))
        print(json.dumps({"status": "verified", "views": list(views), "references": len(views),
                          "renderers_launched": 0}, indent=2))
    else:
        if args.output is None:
            parser.error("--output is required for prepare/run")
        with exclusive_operation(ROOT / "build/falcor/.fixed-view-suite.lock"):
            result = (prepare(args.config, args.output) if args.prepare else
                      execute(args.config, args.output, retry_failed=args.retry_failed))
        print(result)


if __name__ == "__main__":
    main()
