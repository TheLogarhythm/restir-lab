"""Compare saved linear HDR captures with checked, pose-matched references."""
import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/run"))
sys.path.insert(0, str(ROOT))
import numpy as np
from rtxdi_common import sha
from experiment.artifacts import save_json
from experiment.reference import (
    CONVERGENCE_METRIC, EPSILON, REFERENCE_SCHEMA_VERSION, ImageCache,
    metrics, reference_ready, regions, suite_captures, validate_lighting,
)
from experiment.runner import relative_path
from experiment.scenes import ACTIVE_SCENES
from scripts.analysis.di_reuse_report import write_report


def csv_file(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows):
    groups = defaultdict(list)
    keys = ("scene", "scenario", "mode", "frame", "region")
    for row in rows:
        groups[tuple(row[k] for k in keys)].append(row)
    result = []
    for key, group in sorted(groups.items()):
        seeds = [r["seed"] for r in group]
        if len(set(seeds)) != len(seeds):
            raise ValueError("Duplicate scene/scenario/mode/frame/seed records")
        summary = dict(zip(keys, key))
        summary.update(seeds=len(group), reference_converged=all(r["reference_converged"] for r in group))
        for name in ("rmse", "nrmse", "rmae", "relative_luminance_offset", "gpu_ms"):
            values = [r[name] for r in group]
            summary[name + "_mean"] = float(np.mean(values))
            summary[name + "_std"] = float(np.std(values, ddof=1)) if len(values) > 1 else None
        result.append(summary)
    return result


def phase(config, frame):
    if config["scenario"] == "static":
        return "startup" if frame <= 32 else "steady"
    if config["scenario"] == "reset":
        return "before-reset" if frame < config["definition"]["reset_frame"] else "after-reset"
    motion = config["definition"]["motion"]
    return "hold" if frame <= motion["start_frame"] else "moving" if frame <= motion["end_frame"] else "stopped"


def validate_comparison(captures):
    """Require matched controls, targets and capture coverage across modes/seeds."""
    controls, poses, coverage = {}, {}, defaultdict(lambda: defaultdict(set))
    for capture in captures:
        config, manifest = capture["config"], capture["manifest"]
        group = (config["scene_id"], config["scenario"])
        settings = {"arguments": {k: v for k, v in config["arguments"].items() if k != "restirDI.diMode"},
                    "gpu": manifest["gpu"], "build": manifest["build"],
                    "definition": {k: v for k, v in config["definition"].items() if k != "seed"}}
        if controls.setdefault(group, settings) != settings:
            raise ValueError("Compared modes/seeds have different settings/build/hardware; use separate reports")
        coverage[group][config["mode"]].add((config["seed"], capture["frame"]["frame"]))
        pose_group = (config["scene_id"], config["scenario"], capture["frame"]["frame"])
        if poses.setdefault(pose_group, capture["key"]) != capture["key"]:
            raise ValueError("Compared modes/seeds have different lighting targets or camera poses")
    for modes in coverage.values():
        if any(points != next(iter(modes.values())) for points in modes.values()):
            raise ValueError("Compared modes have different seed/capture coverage; use matching runs")


def load_references(index_path, reference_root, captures):
    """Validate reference targets, schemas and content hashes before analysis."""
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if (index.get("schema_version") != REFERENCE_SCHEMA_VERSION
            or index.get("convergence_metric") != CONVERGENCE_METRIC):
        raise ValueError("Unsupported reference suite; generate a new suite")
    validate_lighting(captures, index.get("build", {}))
    references = index["references"]
    for capture in captures:
        item = references.get(capture["key"])
        if item is None or item["target"] != capture["target"]:
            raise ValueError("Missing or incompatible reference for " + capture["key"])
    for key in {c["key"] for c in captures}:
        item = references[key]
        for field in ("image", "convergence"):
            if sha(reference_root / item[field]) != item[field + "_sha256"]:
                raise ValueError("Reference image or convergence record was modified")
        checks = json.loads((reference_root / item["convergence"]).read_text(encoding="utf-8"))
        if (checks.get("schema_version") != REFERENCE_SCHEMA_VERSION
                or checks.get("convergence_metric") != CONVERGENCE_METRIC):
            raise ValueError("Unsupported convergence metric/record; generate a new reference suite")
        if checks["converged"] != item["converged"]:
            raise ValueError("Reference index and convergence status disagree")
    return references


def read_timings(directory, config):
    """Validate complete per-frame timings and aggregate them by experiment phase."""
    with (directory / "timings.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or "gpu_ms" not in rows[0] or "frame" not in rows[0]:
        raise ValueError(f"Missing frame/GPU timings: {directory}")
    by_frame = {int(row["frame"]): row for row in rows}
    expected = {frame["frame"] for frame in config["frames"]}
    if len(by_frame) != len(rows) or set(by_frame) != expected:
        raise ValueError(f"Duplicate or incomplete timing frame coverage: {directory}")
    fields = [name for name in rows[0] if name.endswith("_ms")]
    for row in rows:
        for name in fields:
            value = float(row[name])
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid {name} at frame {row['frame']}: {directory}")
            row[name] = value
    by_phase = defaultdict(list)
    for frame, row in by_frame.items():
        by_phase[phase(config, frame)].append(row)
    phases = [{
        "scene": config["scene_id"], "scenario": config["scenario"],
        "mode": config["mode"], "seed": config["seed"], "phase": name,
        "frames": len(group), "headless": bool(config["arguments"]["device.headless"]),
        **{field: float(np.mean([row[field] for row in group])) for field in fields},
    } for name, group in by_phase.items()]
    return by_frame, phases


def collect_measurements(captures, references, reference_root, output, record, load_image):
    rows, timing_rows, run_times = [], [], {}
    for capture in captures:
        config, directory = capture["config"], capture["directory"]
        if directory not in run_times:
            run_times[directory], phases = read_timings(directory, config)
            timing_rows.extend(phases)
            for name in ("config.json", "manifest.json", "resolved.json", "timings.csv"):
                record["input_sha256"][relative_path(directory / name, output)] = sha(directory / name)
        ref = references[capture["key"]]
        reference = load_image(reference_root / ref["image"])
        image = load_image(capture["image"])
        record["input_sha256"][relative_path(capture["image"], output)] = sha(capture["image"])
        for name, region in regions(*reference.shape[:2]).items():
            rows.append({"scene": config["scene_id"], "scenario": config["scenario"], "mode": config["mode"],
                         "seed": config["seed"], "frame": capture["frame"]["frame"], "region": name,
                         "reference_key": capture["key"], "reference_converged": ref["converged"],
                         **metrics(image[region], reference[region]),
                         "gpu_ms": float(run_times[directory][capture["frame"]["frame"]]["gpu_ms"])})
    return rows, timing_rows


def recheck_references(rows, references, reference_root):
    # Reusing a reference for a better method/new seed can demand more precision.
    for key in {row["reference_key"] for row in rows}:
        matching = [row for row in rows if row["reference_key"] == key]
        best = {name: min(r["rmae"] for r in matching if r["region"] == name) for name in {r["region"] for r in matching}}
        checks = json.loads((reference_root / references[key]["convergence"]).read_text(encoding="utf-8"))
        ready = reference_ready(checks["checkpoints"], best, checks["reference_noise_ratio"], checks["convergence_metric"]) and references[key]["converged"]
        references[key]["converged"] = ready
        for row in matching:
            row["reference_converged"] = ready


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--references", required=True, type=Path)
    parser.add_argument("--scene", nargs="+")
    parser.add_argument("--scenario", choices=["static", "motion", "reset"])
    parser.add_argument("--output", type=Path, help="New directory; default <baseline>/analysis")
    args = parser.parse_args()
    baseline, reference_root = args.baseline.resolve(), args.references.resolve()
    output = (args.output or baseline / "analysis").resolve()
    if output.exists():
        parser.error("Output already exists; choose a new --output directory")
    captures = suite_captures(baseline, args.scene or ACTIVE_SCENES, args.scenario)
    validate_comparison(captures)
    index_path = reference_root / "reference-index.json"
    references = load_references(index_path, reference_root, captures)
    output.mkdir(parents=True, exist_ok=False)
    record = {
        "status": "running", "baseline": relative_path(baseline, output),
        "references": relative_path(reference_root, output),
        "reference_index_sha256": sha(index_path),
        "script_sha256": sha(Path(__file__)),
        "report_source_sha256": sha(Path(__file__).with_name("di_reuse_report.py")),
        "metrics_source_sha256": sha(ROOT / "scripts/run/experiment/reference.py"),
        "epsilon": EPSILON, "convergence_metric": CONVERGENCE_METRIC,
        "convergence_regions": ["full"],
        "selection": {"scenes": args.scene, "scenario": args.scenario},
        "input_sha256": {},
    }
    save_json(output / "analysis.json", record)
    load_image = ImageCache()
    try:
        rows, timing_rows = collect_measurements(
            captures, references, reference_root, output, record, load_image)
        recheck_references(rows, references, reference_root)
        summaries = summarize(rows)
        csv_file(output / "metrics.csv", rows)
        csv_file(output / "summary.csv", summaries)
        csv_file(output / "timings.csv", timing_rows)
        presentation = write_report(output, captures, summaries, timing_rows, references, reference_root, load_image)
        ready = presentation["reference_converged"]
        record.update(status="completed", reference_converged=ready, captures=len(captures))
    except BaseException:
        record["status"] = "incomplete"
        raise
    finally:
        save_json(output / "analysis.json", record)
    print(output / "summary.md")


if __name__ == "__main__":
    main()
