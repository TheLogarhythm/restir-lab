"""Independent-seed PDF error/cost summaries; no pooled-frame uncertainty claims."""
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
import shutil
import tempfile

import numpy as np

from .pdf_artifacts import METHODS, METRIC_DEFINITIONS, _captures, _config_alignment, _hash, _phase, _validate_rois
from experiment.error_metrics import smape_map, trmae_map
from experiment.images import read_pfm
from experiment.reference import metrics as spatial_metrics

ERRORS = ("smape", "rmae", "nrmse", "trmae")
COSTS = ("gpu_ms", "initial_ms", "spatial_ms")
METRICS = ERRORS + COSTS
GROUP = ("condition", "scenario", "phase", "region")
REFERENCE_PHASES = {"startup": "1-32", "motion-change": "33-64", "recovery": "65-96"}


def _timings(directory, count):
    path = Path(directory) / "timings.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or any(key not in rows[0] for key in ("frame", *COSTS)):
        raise ValueError(f"Missing total/initial/spatial GPU timing columns: {path}")
    try:
        if [int(row["frame"]) for row in rows] != list(range(1, count + 1)):
            raise ValueError("Timing frames must be complete, ordered, and unique")
        result = {}
        for row in rows:
            values = {key: float(row[key]) for key in COSTS}
            if any(not math.isfinite(value) or value < 0 for value in values.values()) or values["gpu_ms"] <= 0:
                raise ValueError("GPU timings must be finite and nonnegative, with positive total")
            result[int(row["frame"])] = values
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid GPU timings in {path}: {exc}") from exc
    return result


def _seed_neutral(config):
    """Sampling RNG differs across seeds; all scene and estimator controls agree."""
    config = json.loads(json.dumps(config))
    config.pop("seed", None)
    config.get("definition", {}).pop("seed", None)
    for frame in config.get("frames", []):
        frame.pop("sampling_frame", None)
    return config


def _prepare(condition):
    condition_id = condition["id"]
    scenario = condition["scenario"]
    if not isinstance(condition_id, str) or not condition_id or scenario not in ("static", "motion", "lighting"):
        raise ValueError("Each condition requires a nonempty id and static/motion/lighting scenario")
    assessment = condition.get("reference_assessment")
    if assessment is not None and not isinstance(assessment, dict):
        raise ValueError("reference_assessment must be a JSON receipt object")
    assessment = json.loads(json.dumps(assessment, allow_nan=False))
    runs = condition["runs"]
    if len(runs) != 3 or sorted(run.get("seed") for run in runs) != [1, 2, 3]:
        raise ValueError("Each condition requires exactly independent seeds 1, 2, 3")
    refs = condition["references"]
    if any(type(frame) is not int or frame < 1 for frame in refs):
        raise ValueError("Reference frames must be positive integer keys")
    if scenario == "static":
        if 128 not in refs:
            raise ValueError("Static summaries require reference frame 128")
        frames, count = [128], 128
    else:
        frames, count = list(range(1, 97)), 96
        if sorted(refs) != frames:
            raise ValueError("Temporal summaries require all reference frames 1..96")
    reference_paths = {frame: Path(refs[frame]).resolve() for frame in frames}
    for path in reference_paths.values():
        if not path.is_file():
            raise ValueError(f"Missing reference: {path}")
    shape = read_pfm(reference_paths[frames[0]]).shape
    expected = condition.get("expected_resolution", (1920, 1080))
    if shape != (expected[1], expected[0], 3):
        raise ValueError("Reference resolution does not match expected_resolution")
    rois = _validate_rois(condition.get("rois", ()), shape[1], shape[0])
    regions = {"full": (slice(None), slice(None))}
    regions.update({roi["name"]: (slice(roi["y"], roi["y"] + roi["height"]),
                  slice(roi["x"], roi["x"] + roi["width"])) for roi in rois})
    if len(regions) != len(rois) + 1:
        raise ValueError("ROI name 'full' is reserved")
    sources, timing, alignment, configs = {}, {}, {}, []
    provenance = {"references": {str(frame): {"path": str(path), "sha256": _hash(path)}
                  for frame, path in reference_paths.items()}, "runs": []}
    for run in sorted(runs, key=lambda run: run["seed"]):
        seed = run["seed"]
        alignment[seed] = _config_alignment(run["off_dir"], run["on_dir"], expected_seed=seed)
        config_path = Path(run["off_dir"]) / "config.json"
        if config_path.is_file():
            configs.append(_seed_neutral(json.loads(config_path.read_text(encoding="utf-8"))))
        for method, key in zip(METHODS, ("off_dir", "on_dir")):
            directory = Path(run[key]).resolve()
            captures = _captures(directory)
            if set(captures) != set(refs):
                raise ValueError(f"Capture/reference frame alignment mismatch: {directory}")
            sources[(seed, method)] = captures
            timing[(seed, method)] = _timings(directory, count)
            provenance["runs"].append({"seed": seed, "method": method, "directory": str(directory),
                "timings_sha256": _hash(directory / "timings.csv"),
                "images": {str(frame): _hash(captures[frame]) for frame in frames}})
    if configs and (len(configs) != 3 or any(config != configs[0] for config in configs[1:])):
        raise ValueError("Scene/estimator controls differ between independent seeds")
    return dict(id=condition_id, scenario=scenario, frames=frames, references=reference_paths,
                shape=shape, regions=regions, sources=sources, timing=timing,
                provenance=provenance, alignment=alignment, rois=rois, reference_assessment=assessment)


def _measure(condition):
    """Reference is decoded once per frame; previous images are bounded to six runs."""
    rows, previous_images, previous_ref = [], {}, None
    for frame in condition["frames"]:
        reference = read_pfm(condition["references"][frame])
        if reference.shape != condition["shape"]:
            raise ValueError("Reference sequence dimensions changed")
        current_images = {}
        for (seed, method), captures in sorted(condition["sources"].items()):
            image = read_pfm(captures[frame])
            if image.shape != condition["shape"]:
                raise ValueError("Method/reference dimensions differ")
            current_images[(seed, method)] = image
            for name, region in condition["regions"].items():
                spatial = spatial_metrics(image[region], reference[region])
                temporal = None
                if previous_ref is not None and condition["scenario"] != "static":
                    temporal = float(np.mean(trmae_map(image[region], previous_images[(seed, method)][region],
                        reference[region], previous_ref[region])))
                rows.append({"condition": condition["id"], "scenario": condition["scenario"],
                    "seed": seed, "method": method, "frame": frame,
                    "previous_frame": frame - 1 if temporal is not None else None,
                    "phase": "static-final" if condition["scenario"] == "static" else _phase(frame),
                    "region": name, "smape": float(np.mean(smape_map(image[region], reference[region]))),
                    "rmae": spatial["rmae"], "nrmse": spatial["nrmse"], "trmae": temporal})
        previous_ref, previous_images = reference, current_images
    return rows


def _seed_metrics(frame_rows, prepared):
    conditions = {condition["id"]: condition for condition in prepared}
    groups = defaultdict(list)
    for row in frame_rows:
        groups[tuple(row[key] for key in (*GROUP, "seed", "method"))].append(row)
    results = []
    for key, rows in sorted(groups.items()):
        result = dict(zip((*GROUP, "seed", "method"), key))
        for metric in ERRORS:
            values = [row[metric] for row in rows if row[metric] is not None]
            result[metric] = float(np.mean(values)) if values else None
        result["frame_count"] = len(rows)
        result["temporal_pair_count"] = sum(row["trmae"] is not None for row in rows)
        condition = conditions[result["condition"]]
        timed_frames = list(range(41, 129)) if result["scenario"] == "static" else [row["frame"] for row in rows]
        times = condition["timing"][(result["seed"], result["method"])]
        for metric in COSTS:
            result[metric] = float(np.mean([times[frame][metric] for frame in timed_frames]))
        result["timing_frame_count"] = len(timed_frames)
        results.append(result)
    return results


def _aggregate(rows, keys, metrics):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[key] for key in keys)].append(row)
    results = []
    for key, group in sorted(groups.items()):
        if sorted(row["seed"] for row in group) != [1, 2, 3]:
            raise ValueError("Every aggregate requires exactly three independent seeds")
        result = dict(zip(keys, key))
        result["seeds"] = 3
        for metric in metrics:
            values = [row[metric] for row in group]
            complete = all(value is not None for value in values)
            result[f"{metric}_mean"] = float(np.mean(values)) if complete else None
            result[f"{metric}_sd"] = float(np.std(values, ddof=1)) if complete else None
        results.append(result)
    return results


def _paired(seed_metrics):
    groups = defaultdict(dict)
    for row in seed_metrics:
        groups[tuple(row[key] for key in (*GROUP, "seed"))][row["method"]] = row
    results = []
    relative_metrics = tuple(f"{metric}_relative_percent" for metric in ("smape", "rmae", "trmae", "gpu_ms"))
    for key, pair in sorted(groups.items()):
        off, on = pair["pdf-off"], pair["pdf-on"]
        result = dict(zip((*GROUP, "seed"), key))
        for metric in METRICS:
            result[metric] = on[metric] - off[metric] if off[metric] is not None and on[metric] is not None else None
        for field in relative_metrics:
            metric = field.removesuffix("_relative_percent")
            result[field] = 100 * result[metric] / off[metric] if result[metric] is not None and off[metric] != 0 else None
        results.append(result)
    return results, relative_metrics


def _nested(value, *keys):
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _assessment_pair(assessment, region, phase, metric):
    """Read the manager's static/temporal receipts without borrowing other phases."""
    if not assessment:
        return None
    if phase == "static-final" and metric != "trmae":
        source = assessment.get("differences", assessment)
        return _nested(source, "regions", region, "static", "metrics", metric, "paired_difference")
    if phase in REFERENCE_PHASES:
        source = assessment.get("temporal", assessment)
        phase_receipt = _nested(source, "regions", region, REFERENCE_PHASES[phase])
        return (_nested(phase_receipt, "paired_difference") if metric == "trmae" else
                _nested(phase_receipt, "metrics", metric, "paired_difference"))
    return None


def _reference_direction(delta, receipt):
    """Resolve a direction only when the receipt covers this measured delta."""
    if delta is None:
        return "not-applicable", "not applicable", None
    if receipt is None:
        return "unassessed", "no resolved difference", None
    def finite_number(value):
        return type(value) in (int, float) and math.isfinite(value)
    if not isinstance(receipt, dict) or not finite_number(receipt.get("current")):
        return "invalid-assessment", "no resolved difference", None
    current = receipt["current"]
    if not math.isclose(current, delta, rel_tol=1e-8, abs_tol=1e-10):
        return "mismatch", "no resolved difference", None
    variants = receipt.get("variants")
    reported_change = receipt.get("max_reference_change")
    if (not isinstance(variants, dict) or not {"half_a", "half_b", "previous"} <= set(variants)
            or not all(finite_number(value) for value in variants.values())
            or not finite_number(reported_change) or reported_change < 0):
        return "invalid-assessment", "no resolved difference", None
    observed_change = max(abs(value - current) for value in variants.values())
    if not math.isclose(reported_change, observed_change, rel_tol=1e-8, abs_tol=1e-10):
        return "invalid-assessment", "no resolved difference", None
    # Use the computed summary delta for the final bound, even within receipt tolerance.
    change = max(abs(value - delta) for value in variants.values())
    if delta == current == 0 and all(value == 0 for value in variants.values()) and receipt.get("state") == "equal":
        return "equal", "equal in assessed references", change
    if (receipt.get("direction_resolved") is True and receipt.get("state") == "resolved"
            and abs(delta) > change):
        return "resolved", "improves" if delta < 0 else "worsens", change
    return "inconclusive", "no resolved difference", change


def _annotate_reference_directions(differences, prepared):
    assessments = {condition["id"]: condition["reference_assessment"] for condition in prepared}
    for row in differences:
        for metric in ERRORS:
            receipt = _assessment_pair(assessments[row["condition"]], row["region"], row["phase"], metric)
            status, direction, change = _reference_direction(row[f"{metric}_mean"], receipt)
            row[f"{metric}_reference_status"] = status
            row[f"{metric}_direction"] = direction
            row[f"{metric}_reference_max_change"] = change


def _direction_label(difference, metric):
    status = difference[f"{metric}_reference_status"]
    if status == "resolved":
        return "improvement resolved" if difference[f"{metric}_direction"] == "improves" else "worsening resolved"
    if status == "equal":
        return "equal in assessed references"
    if status == "not-applicable":
        return "n/a"
    reasons = {"unassessed": " (unassessed)", "mismatch": " (receipt mismatch)",
               "invalid-assessment": " (invalid assessment)"}
    return "no resolved difference" + reasons.get(status, "")


def _csv(path, rows):
    if not rows:
        raise ValueError("Refusing to write an empty summary table")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _number(value):
    return "n/a" if value is None else f"{value:.4g}"


def _markdown(summaries, differences):
    lookup = {tuple(row[key] for key in (*GROUP, "method")): row for row in summaries}
    lines = ["# PDF controlled comparison", "",
        "Each value is a mean across independent seeds 1/2/3; SD is the sample standard deviation of the three seed means. "
        "Frames/pixels are averaged within each phase and seed first. Paired differences are PDF on minus PDF off. "
        "A resolved direction requires its paired difference to exceed the change measured with independent half-stream and previous-checkpoint references.", "",
        "Static image errors use frame 128; static GPU cost averages frames 41–128. Temporal phases use frames 1–32, 33–64 and 65–96. "
        "TRMAE pairs belong to their later frame (31/32/32 pairs); motion includes 32→33 and recovery includes 64→65. "
        "Total gpu_ms is the recorded total including all instrumented passes; initial/spatial costs are separate diagnostics. "
        "Logical 30 FPS is the playback interval, not a performance claim.", "",
        "| Condition | Scenario / phase | SMAPE off → on (%) | Paired Δ SMAPE (pp, mean ± SD) | SMAPE direction | TRMAE off → on | TRMAE direction | GPU off → on (ms) | Paired GPU change (%) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for difference in differences:
        if difference["region"] != "full":
            continue
        group = tuple(difference[key] for key in GROUP)
        off, on = (lookup[(*group, method)] for method in METHODS)
        delta = difference["smape_mean"]
        def transition(metric):
            return f"{_number(off[metric + '_mean'])} → {_number(on[metric + '_mean'])}"
        condition_id = difference["condition"].replace("|", "\\|")
        lines.append(f"| {condition_id} | {difference['scenario']} / {difference['phase']} | {transition('smape')} | "
            f"{_number(delta)} ± {_number(difference['smape_sd'])} | {_direction_label(difference, 'smape')} | "
            f"{transition('trmae')} | {_direction_label(difference, 'trmae')} | {transition('gpu_ms')} | "
            f"{_number(difference['gpu_ms_relative_percent_mean'])} |")
    lines += ["", "Full-image conclusions remain separate by condition/scenario. Identical preselected ROI diagnostics, "
        "RMAE, NRMSE, per-method SDs, paired seed variability and initial/spatial cost appear in the CSV tables. "
        "Reference half-stream/checkpoint/gradient acceptance is supplied by the caller and is recorded explicitly; "
        "this module does not infer acceptance from an image or its filename.", ""]
    return "\n".join(lines)


def summarize_suite(output, condition_reports, *, references_accepted):
    """Write all-seed metrics and cautious numerical directions for accepted inputs.

    Each condition supplies id, scenario (static/motion/lighting), runs (exactly
    seed 1/2/3 with off_dir/on_dir), references (integer frame -> PFM path), and
    optional preselected rois/expected_resolution (default 1920x1080), plus an
    optional reference_assessment receipt for interpreting paired differences.
    Without that matching assessment, error directions remain unresolved. Root-level
    reference half-stream/checkpoint and gradient validation must precede this
    explicit acceptance flag. A fresh output directory is required.
    """
    if references_accepted is not True:
        raise ValueError("References must be explicitly accepted before summarizing")
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Refusing to overwrite an existing suite summary")
    if not condition_reports or len({condition["id"] for condition in condition_reports}) != len(condition_reports):
        raise ValueError("Condition IDs must be nonempty and unique")
    prepared = [_prepare(condition) for condition in condition_reports]
    frame_rows = [row for condition in prepared for row in _measure(condition)]
    seed_rows = _seed_metrics(frame_rows, prepared)
    summaries = _aggregate(seed_rows, (*GROUP, "method"), METRICS)
    paired, relative_metrics = _paired(seed_rows)
    differences = _aggregate(paired, GROUP, (*METRICS, *relative_metrics))
    _annotate_reference_directions(differences, prepared)
    result = {"schema_version": 1, "references_accepted": True, "seeds": [1, 2, 3],
        "metric_definitions": METRIC_DEFINITIONS,
        "aggregation": "Average frames/pairs within each seed and phase, then mean/sample SD across independent seeds",
        "difference": "PDF on minus PDF off; relative changes computed within each seed before aggregation",
        "conditions": [{"id": condition["id"], "scenario": condition["scenario"], "rois": condition["rois"],
                        "config_alignment": condition["alignment"], "inputs": condition["provenance"],
                        "reference_assessment": condition["reference_assessment"]} for condition in prepared],
        "frame_metrics": frame_rows, "seed_metrics": seed_rows, "summaries": summaries, "paired_differences": differences}
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        for name, rows in (("frame-metrics", frame_rows), ("seed-metrics", seed_rows), ("summary", summaries),
                           ("paired-seed-differences", paired), ("paired-differences", differences)):
            _csv(stage / f"{name}.csv", rows)
        (stage / "summary.md").write_text(_markdown(summaries, differences), encoding="utf-8")
        (stage / "analysis.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        stage.rename(output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return result
