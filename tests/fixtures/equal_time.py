"""Independent seed curves shared by equal-time and reference-policy checks."""
import copy
import csv
import json


def equal_time_fixture(directory, *, reference_change=None, disjoint=False):
    directory.mkdir()
    rows, conditions = [], []
    for view in ("interior", "exterior"):
        for budget, base_time in ((2, 2.), (4, 4.), (8, 8.)):
            condition_id = f"bistro-{view}-static-neighbors-{budget}"
            methods = {key: {"per_seed": {}} for key in ("False", "True")}
            metric_methods = {metric: copy.deepcopy(methods) for metric in ("smape", "rmae", "nrmse")}
            for seed in (1, 2, 3):
                for method in ("pdf-off", "pdf-on"):
                    on = method == "pdf-on"
                    time = base_time + (seed - 1) * .25 + int(on)
                    error = 40 - 2 * time + seed - (2 * seed - 1 if on else 0)
                    row = {"condition": condition_id, "scenario": "static", "phase": "static-final",
                           "region": "full", "seed": seed, "method": method,
                           "gpu_ms": time + (20 if disjoint and on else 0),
                           "smape": error, "rmae": error / 10, "nrmse": error / 20}
                    rows.append(row)
                    if reference_change is not None:
                        for metric in metric_methods:
                            current = row[metric]
                            scale = 1 if metric == "smape" else .1 if metric == "rmae" else .05
                            change = reference_change * scale if on else 0
                            metric_methods[metric][str(on)]["per_seed"][str(seed)] = {
                                "current": current, "half_a": current + change,
                                "half_b": current - change, "previous": current + change / 2}
            assessment = None if reference_change is None else {"differences": {"passed": True,
                "regions": {"full": {"static": {"metrics": {metric: {"methods": values}
                    for metric, values in metric_methods.items()}}}}}}
            conditions.append({"id": condition_id, "scenario": "static", "reference_assessment": assessment})
    analysis = {"schema_version": 1, "references_accepted": True, "seeds": [1, 2, 3],
                "conditions": conditions, "seed_metrics": rows}
    write_equal_time_fixture(directory, analysis)
    return analysis


def write_equal_time_fixture(directory, analysis):
    (directory / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
    with (directory / "seed-metrics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(analysis["seed_metrics"][0]))
        writer.writeheader()
        writer.writerows(analysis["seed_metrics"])
