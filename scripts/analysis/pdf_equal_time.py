"""Interpolate bounded equal-time estimates from the measured PDF budget sweep."""
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from statistics import mean, stdev
import tempfile

from .pdf_artifacts import _reference_policy_metadata


METHODS = ("pdf-off", "pdf-on")
METRICS = ("smape", "rmae", "nrmse")
VARIANTS = ("current", "half_a", "half_b", "previous")
VIEWS = ("bistro-interior", "bistro-exterior")
BUDGETS = (2, 4, 8)
CONDITION = re.compile(r"^(bistro-(?:interior|exterior))(?:-static)?-neighbors-(\d+)$")


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("Metric and GPU timing values must be finite numbers")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("Metric and GPU timing values must be finite and nonnegative")
    return value


def _rows(records):
    selected = {}
    for record in records:
        match = CONDITION.fullmatch(record.get("condition", ""))
        if not match or record.get("region") != "full":
            continue
        view, budget = match[1], int(match[2])
        if (record.get("scenario") != "static" or record.get("phase") != "static-final"
                or budget not in BUDGETS or str(record.get("seed")) not in ("1", "2", "3")
                or record.get("method") not in METHODS):
            raise ValueError("Equal-time inputs require static budgets 2/4/8, seeds 1/2/3 and both methods")
        seed, method = int(record["seed"]), record["method"]
        key = (view, budget, seed, method)
        if key in selected:
            raise ValueError("Duplicate measured budget/seed/method point")
        values = {metric: _number(record[metric]) for metric in ("gpu_ms", *METRICS)}
        if values["gpu_ms"] <= 0:
            raise ValueError("Measured GPU timing must be positive")
        selected[key] = {"view": view, "condition": record["condition"], "neighbors": budget,
                         "seed": seed, "method": method, **values}
    expected = {(view, budget, seed, method) for view in VIEWS for budget in BUDGETS
                for seed in (1, 2, 3) for method in METHODS}
    if set(selected) != expected:
        raise ValueError("Equal-time comparison requires both Bistro views and every budget/seed/method point")
    return selected


def _interpolate(curve, target, field):
    if not curve[0]["gpu_ms"] <= target <= curve[-1]["gpu_ms"]:
        raise ValueError("Equal-time interpolation cannot extrapolate")
    lower = max((row for row in curve if row["gpu_ms"] <= target), key=lambda row: row["gpu_ms"])
    upper = min((row for row in curve if row["gpu_ms"] >= target), key=lambda row: row["gpu_ms"])
    weight = 0. if upper is lower else (target - lower["gpu_ms"]) / (upper["gpu_ms"] - lower["gpu_ms"])
    value = lower[field] + weight * (upper[field] - lower[field])
    return value, lower, upper, weight


def _aggregate(values):
    return {"mean": mean(values), "sd": stdev(values)}


def _reference_values(point, metric, conditions):
    """Aggregate receipts cannot reconstruct differently weighted seed curves."""
    try:
        assessment = conditions[point["condition"]]["reference_assessment"]
        source = assessment.get("differences", assessment)
        methods = source["regions"]["full"]["static"]["metrics"][metric]["methods"]
        key = "True" if point["method"] == "pdf-on" else "False"
        values = methods[key]["per_seed"][str(point["seed"])]
        values = {variant: _number(values[variant]) for variant in VARIANTS}
        if not math.isclose(values["current"], point[metric], rel_tol=1e-8, abs_tol=1e-10):
            return None
        return values
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def _assess_reference(curves, target, metric, conditions, delta):
    if any(conditions[point["condition"]].get("reference_policy")
           for curve in curves.values() for point in curve):
        return {"reference_status": "not_evaluated", "direction": "not_evaluated",
                "reference_variants": None, "reference_max_change": None}
    variants = defaultdict(dict)
    for key, curve in curves.items():
        assessed = []
        for point in curve:
            values = _reference_values(point, metric, conditions)
            if values is None:
                return {"reference_status": "unassessed", "direction": "no resolved difference",
                        "reference_variants": None, "reference_max_change": None}
            assessed.append({"gpu_ms": point["gpu_ms"], **values})
        for variant in VARIANTS:
            variants[variant][key] = _interpolate(assessed, target, variant)[0]
    estimates = {}
    for variant, values in variants.items():
        differences = [values[seed, "pdf-on"] - values[seed, "pdf-off"] for seed in (1, 2, 3)]
        estimates[variant] = {**_aggregate(differences), "seed_differences": differences}
    change = max(abs(row["mean"] - delta) for row in estimates.values())
    equal = all(row["mean"] == delta == 0 for row in estimates.values())
    resolved = abs(delta) > change
    return {"reference_status": "equal" if equal else "resolved" if resolved else "inconclusive",
            "direction": "equal in assessed references" if equal else (
                "improves" if delta < 0 else "worsens") if resolved else "no resolved difference",
            "reference_variants": estimates, "reference_max_change": change,
            "reference_paired_range": [min(row["mean"] for row in estimates.values()),
                                       max(row["mean"] for row in estimates.values())]}


def _view(view, points, conditions):
    measured = [point for key, point in sorted(points.items()) if key[0] == view]
    source_conditions = [conditions[name] for name in sorted({point["condition"] for point in measured})]
    policies = [condition.get("reference_policy") for condition in source_conditions]
    if any(policy is not None for policy in policies):
        if any(policy is None or policy != policies[0] for policy in policies):
            raise ValueError(f"Equal-time reference policies differ across neighbor budgets for {view}")
        # Canonical policy validation also rejects subtly altered fixed budgets.
        for policy in policies:
            _reference_policy_metadata(policy)
        if any("inputs" in condition for condition in source_conditions):
            try:
                hashes = [condition["inputs"]["references"]["128"]["sha256"] for condition in source_conditions]
            except (KeyError, TypeError) as error:
                raise ValueError(f"Missing frame-128 reference provenance for {view}") from error
            if (any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes)
                    or len(set(hashes)) != 1):
                raise ValueError(f"Frame-128 reference hashes differ across neighbor budgets for {view}")
    curves = {}
    for seed in (1, 2, 3):
        for method in METHODS:
            curve = sorted((point for point in measured if point["seed"] == seed and point["method"] == method),
                           key=lambda point: point["gpu_ms"])
            if len({point["gpu_ms"] for point in curve}) != len(curve):
                raise ValueError(f"Ambiguous duplicate measured GPU times for {view}, seed {seed}, {method}")
            curves[seed, method] = curve
    ranges = [{"seed": seed, "method": method, "gpu_ms": [curve[0]["gpu_ms"], curve[-1]["gpu_ms"]]}
              for (seed, method), curve in curves.items()]
    low = max(row["gpu_ms"][0] for row in ranges)
    high = min(row["gpu_ms"][1] for row in ranges)
    result = {"view": view, "measured_points": measured, "curve_ranges": ranges,
              "status": "no-overlap", "shared_gpu_ms": None, "target_gpu_ms": None,
              "estimates": [], "paired_differences": {}}
    if low > high:
        return result
    target = (low + high) / 2
    result.update(status="interpolated", shared_gpu_ms=[low, high], target_gpu_ms=target)
    estimates = {}
    for (seed, method), curve in curves.items():
        values = {metric: _interpolate(curve, target, metric)[0] for metric in METRICS}
        _, lower, upper, weight = _interpolate(curve, target, "smape")
        closest = min(curve, key=lambda point: (abs(point["gpu_ms"] - target), point["gpu_ms"], point["neighbors"]))
        record = {"view": view, "seed": seed, "method": method, "estimate_kind": "piecewise-linear interpolated",
                  "target_gpu_ms": target, "lower_neighbors": lower["neighbors"], "upper_neighbors": upper["neighbors"],
                  "lower_gpu_ms": lower["gpu_ms"], "upper_gpu_ms": upper["gpu_ms"], "interpolation_weight": weight,
                  "closest_condition": closest["condition"], "closest_neighbors": closest["neighbors"],
                  "closest_gpu_ms": closest["gpu_ms"], "closest_distance_ms": abs(closest["gpu_ms"] - target), **values}
        estimates[seed, method] = record
        result["estimates"].append(record)
    for metric in METRICS:
        differences = [estimates[seed, "pdf-on"][metric] - estimates[seed, "pdf-off"][metric] for seed in (1, 2, 3)]
        paired = {**_aggregate(differences), "seed_differences": differences}
        paired.update(_assess_reference(curves, target, metric, conditions, paired["mean"]))
        paired["method_estimates"] = {method: _aggregate([estimates[seed, method][metric] for seed in (1, 2, 3)])
                                      for method in METHODS}
        result["paired_differences"][metric] = paired
    return result


def _plot(path, views):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    colors = {"pdf-off": "#245A81", "pdf-on": "#B16F17"}
    markers = {"pdf-off": "o", "pdf-on": "^"}
    labels = {"smape": "SMAPE (%)", "rmae": "RMAE", "nrmse": "NRMSE"}
    figure, axes = plt.subplots(2, 3, figsize=(14, 7.4), layout="constrained")
    for row_index, view in enumerate(views):
        for column, metric in enumerate(METRICS):
            axis = axes[row_index, column]
            for method in METHODS:
                points = [point for point in view["measured_points"] if point["method"] == method]
                axis.scatter([point["gpu_ms"] for point in points], [point[metric] for point in points],
                             color=colors[method], marker=markers[method], s=17, alpha=.38, zorder=3)
                groups = [[point for point in points if point["neighbors"] == budget] for budget in BUDGETS]
                means = sorted([(mean(point["gpu_ms"] for point in group), mean(point[metric] for point in group),
                                 stdev(point["gpu_ms"] for point in group), stdev(point[metric] for point in group), budget)
                                for budget, group in zip(BUDGETS, groups)])
                axis.errorbar([item[0] for item in means], [item[1] for item in means],
                              xerr=[item[2] for item in means], yerr=[item[3] for item in means],
                              color=colors[method], marker=markers[method], markersize=5, capsize=3,
                              linewidth=1.15, markerfacecolor="white" if method == "pdf-off" else colors[method], zorder=4)
                for x, y, _, _, budget in means:
                    axis.annotate(str(budget), (x, y), xytext=(4, 6 if method == "pdf-off" else -12),
                                  textcoords="offset points", color=colors[method], fontsize=8)
            if view["status"] == "interpolated":
                axis.axvspan(*view["shared_gpu_ms"], color="#737B82", alpha=.10, zorder=0)
                axis.axvline(view["target_gpu_ms"], color="#333333", linewidth=1, linestyle="--", zorder=2)
            else:
                axis.text(.5, .96, "No common time range", transform=axis.transAxes, ha="center", va="top", fontsize=9)
            axis.set(title=view["view"].replace("bistro-", "Bistro "), xlabel="Measured total GPU time (ms)", ylabel=labels[metric])
            axis.grid(color="#DFE3E6", linewidth=.6)
            axis.set_axisbelow(True)
            axis.spines[["top", "right"]].set_visible(False)
            axis.set_ylim(bottom=0)
    figure.suptitle("PDF budget sweep: measured error and GPU cost", fontsize=15)
    legend = [Line2D([], [], color=colors[method], marker=markers[method], label=method,
                     markerfacecolor="white" if method == "pdf-off" else colors[method]) for method in METHODS]
    legend += [Patch(facecolor="#737B82", alpha=.15, label="Shared range (all 6 curves)"),
               Line2D([], [], color="#333333", linestyle="--", label="Interpolated target")]
    figure.legend(handles=legend, loc="outside lower center", ncol=4, frameon=False)
    figure.get_layout_engine().set(rect=(0, .065, 1, .94))
    figure.savefig(path, dpi=180)
    plt.close(figure)


def _markdown(views, reference_policies=None):
    lines = ["# Bounded equal-time comparison", "",
             "Targets are midpoints of the measured GPU-time range shared by all six seed/method curves in each view. "
             "Values at each target are piecewise-linear interpolated estimates, rather than measured exact-time configurations. "
             "GPU time averages frames 41–128; errors use frame 128. Each paired difference is PDF on minus off; "
             "mean and sample SD use independent seeds 1/2/3. SMAPE is percent and its paired difference is percentage points.", "",
             "| View | Target (ms) | Metric | Off mean ± SD | On mean ± SD | Paired Δ mean ± SD | Reference interpretation |",
             "| --- | ---: | --- | ---: | ---: | ---: | --- |"]
    for view in views:
        if view["status"] == "no-overlap":
            lines.append(f"| {view['view']} | — | no equal-time comparison: no shared measured range | — | — | — | — |")
            continue
        for metric, paired in view["paired_differences"].items():
            def estimate(values):
                return f"{values['mean']:.5g} ± {values['sd']:.3g}"
            interpretation = paired["direction"]
            if paired["reference_status"] == "not_evaluated":
                interpretation = "NOT EVALUATED (fixed reference policy)"
            if paired["reference_status"] == "unassessed":
                interpretation += " (unassessed)"
            lines.append(f"| {view['view']} | {view['target_gpu_ms']:.5g} | {metric.upper()} | "
                         f"{estimate(paired['method_estimates']['pdf-off'])} | {estimate(paired['method_estimates']['pdf-on'])} | "
                         f"{estimate(paired)} | {interpretation} |")
    lines += ["", "![Measured budget points and shared interpolation ranges](frontier.png)", "",
              "Points are individual seeds; error bars are sample SD across three seeds, and labels give neighbor budgets. "
              "The CSV tables retain every measured point, each interpolation bracket/weight, and its closest achieved configuration/time. "
              "Reference directions, where assessed, use matching per-seed current, half-stream and previous-checkpoint values interpolated at the same target; "
              "a direction is resolved only when the paired mean exceeds its largest reference-induced change.", ""]
    if reference_policies:
        lines += ["Fixed-reference policy comparisons mark sensitivity NOT EVALUATED.", ""]
    for name, policy in (reference_policies or {}).items():
        lines += [f"{name}: {_reference_policy_metadata(policy)['reference_caption']}", ""]
    return "\n".join(lines)


def _csv(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def analyze_equal_time(summary_directory, output_directory):
    """Write numeric estimates, a measured cost/error plot and a compact report.

    Input is the accepted-reference pdf_summary output for static Bistro 2/4/8
    neighbor sweeps. No renderer, accumulation, extrapolation or run selection
    occurs here. Existing output directories are never overwritten.
    """
    source, output = Path(summary_directory).resolve(), Path(output_directory).resolve()
    if output.exists():
        raise ValueError("Refusing to overwrite an existing equal-time analysis")
    analysis_path, csv_path = source / "analysis.json", source / "seed-metrics.csv"
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    if analysis.get("references_accepted") is not True:
        raise ValueError("Equal-time inputs require explicitly accepted references")
    with csv_path.open(newline="", encoding="utf-8") as stream:
        points = _rows(list(csv.DictReader(stream)))
    if points != _rows(analysis.get("seed_metrics", [])):
        raise ValueError("CSV and JSON equal-time measurements disagree")
    conditions = {condition["id"]: condition for condition in analysis["conditions"]}
    if len(conditions) != len(analysis["conditions"]) or any(point["condition"] not in conditions for point in points.values()):
        raise ValueError("Missing or duplicate condition metadata")
    reference_policies = {}
    for name, condition in conditions.items():
        metadata = _reference_policy_metadata(condition.get("reference_policy"))
        if metadata and CONDITION.fullmatch(name):
            reference_policies[name] = metadata["reference_policy"]
    views = [_view(view, points, conditions) for view in VIEWS]
    result = {"schema_version": 1, "estimate_kind": "piecewise-linear interpolated, within measured overlap only",
              "seeds": [1, 2, 3], "neighbors": list(BUDGETS), "difference": "PDF on minus off",
              "target_selection": "Midpoint of intersection of all six seed/method measured time ranges per view",
              "aggregation": "Interpolate each seed/method, then mean/sample SD of three paired seed differences",
              "metric_definitions": analysis.get("metric_definitions", {}), "views": views,
              "source": {"directory": str(source), "sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (analysis_path, csv_path)},
                         "reference_assessments": {name: condition.get("reference_assessment") for name, condition in conditions.items()
                                                   if CONDITION.fullmatch(name)}}}
    if reference_policies:
        selected_names = {point["condition"] for point in points.values()}
        result.update(reference_precision_verified=False if selected_names <= set(reference_policies) else None,
                      reference_precision_scope="Per-condition policy and assessment; fixed-policy uncertainty is NOT EVALUATED")
        result["source"]["reference_policies"] = reference_policies
    measured = [point for view in views for point in view["measured_points"]]
    estimates = [row for view in views for row in view["estimates"]]
    paired = [{"view": view["view"], "target_gpu_ms": view["target_gpu_ms"], "metric": metric,
               **{key: values[key] for key in ("mean", "sd", "reference_status", "direction", "reference_max_change")}}
              for view in views for metric, values in view["paired_differences"].items()]
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        _csv(stage / "measured-points.csv", measured, list(measured[0]))
        estimate_fields = list(estimates[0]) if estimates else ["view", "seed", "method", "target_gpu_ms", *METRICS]
        _csv(stage / "interpolated-estimates.csv", estimates, estimate_fields)
        _csv(stage / "paired-differences.csv", paired, list(paired[0]) if paired else
             ["view", "target_gpu_ms", "metric", "mean", "sd", "reference_status", "direction", "reference_max_change"])
        (stage / "analysis.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        (stage / "summary.md").write_text(_markdown(views, reference_policies), encoding="utf-8")
        _plot(stage / "frontier.png", views)
        stage.rename(output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return result
