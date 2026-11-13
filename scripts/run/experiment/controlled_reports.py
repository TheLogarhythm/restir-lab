"""Validate saved report evidence without rewriting historical source identities."""
import copy
import hashlib
import json
from pathlib import Path
from rtxdi_common import sha
from .controlled_outputs import RECEIPT_NAME, _canonical, _matches
from .saved_runs import source_record, resolve_source


PATH_SCHEMA = "repository_root_v1"


def portable_reports(reports):
    result = json.loads(json.dumps(reports, default=str))
    for report in result:
        for run in report["runs"]:
            for name in ("off_dir", "on_dir"):
                run[name] = source_record(run[name])
        report["references"] = {frame: source_record(path) for frame, path in report["references"].items()}
    return result


def identity_report_paths(identity):
    schema = identity.get("path_schema")
    if schema is None:
        return copy.deepcopy(identity["reports"])
    if schema != PATH_SCHEMA:
        raise ValueError("Unknown controlled identity path schema")
    reports = copy.deepcopy(identity["reports"])
    def resolve(record):
        if not isinstance(record, dict) or set(record) != {"path", "path_base"}:
            raise ValueError("Invalid controlled source record")
        return str(resolve_source(record["path"], record["path_base"]))
    for report in reports:
        for run in report["runs"]:
            for name in ("off_dir", "on_dir"):
                run[name] = resolve(run[name])
        report["references"] = {frame: resolve(record) for frame, record in report["references"].items()}
    return reports


def identity_inputs(identity):
    schema = identity.get("path_schema")
    inputs = identity["inputs"]
    if schema is None:
        if not isinstance(inputs, dict):
            raise ValueError("Invalid historical controlled input inventory")
        return {Path(path): digest for path, digest in inputs.items()}
    if schema != PATH_SCHEMA or not isinstance(inputs, list):
        raise ValueError("Unknown or invalid controlled input schema")
    result = {}
    for record in inputs:
        if not isinstance(record, dict) or set(record) != {"path", "path_base", "sha256"}:
            raise ValueError("Invalid controlled input record")
        path = resolve_source(record["path"], record["path_base"])
        if path in result:
            raise ValueError("Duplicate controlled input record")
        result[path] = record["sha256"]
    return result


def validate_retained_raw_product(output, report):
    receipt = json.loads((output / RECEIPT_NAME).read_text())
    identity = receipt["identity"]
    normalized_report = json.loads(json.dumps([report], default=str))
    if _canonical(identity_report_paths(identity))[1] != _canonical(normalized_report)[1]:
        raise ValueError("Retained raw product points to different method runs")
    if any(not Path(path).is_file() or sha(Path(path)) != digest for path, digest in identity_inputs(identity).items()):
        raise ValueError("Retained raw product method inputs or timings changed")
    if not _matches(output, receipt["identity_sha256"], _canonical(identity)[1]):
        raise ValueError(f"Retained raw product failed validation: {output}")


def load_retained_condition_report(output, condition, raw_report, *, root):
    """Read a completed historical report while validating its exact saved evidence."""
    root, output = Path(root).resolve(), Path(output).resolve()
    def resolve(value):
        path = Path(value)
        path = (path if path.is_absolute() else root / path).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Retained report input escapes the experiment suite")
        return path
    try:
        if not output.is_relative_to(root / "analysis"):
            raise ValueError("Retained analysis output escapes the experiment suite")
        receipt = json.loads((output / RECEIPT_NAME).read_text(encoding="utf-8"))
        identity = receipt["identity"]
        _, canonical = _canonical(identity)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if not _matches(output, digest, canonical):
            raise ValueError("Retained completed output or its receipt was modified")
        reports = identity_report_paths(identity)
        if not isinstance(reports, list) or len(reports) != 1 or not isinstance(reports[0], dict):
            raise ValueError("Retained condition requires exactly one report")
        report = copy.deepcopy(reports[0])
        if (report.get("id") != condition["id"] or report.get("scenario") != condition["scenario"]
                or report.get("rois", []) != condition["rois"] or report.get("reference_policy") is not None):
            raise ValueError("Retained condition identity, scenario or ROI metadata changed")
        runs = report["runs"]
        if (not isinstance(runs, list) or len(runs) != 3
                or any(type(run.get("seed")) is not int for run in runs)
                or sorted(run["seed"] for run in runs) != [1, 2, 3]):
            raise ValueError("Retained condition requires exactly method seeds 1, 2, 3")
        for run in runs:
            for name in ("off_dir", "on_dir"):
                run[name] = resolve(run[name])
        expected = {run["seed"]: {name: resolve(run[name]) for name in ("off_dir", "on_dir")}
                    for run in raw_report["runs"]}
        if {run["seed"]: {name: run[name] for name in ("off_dir", "on_dir")} for run in runs} != expected:
            raise ValueError("Retained condition refers to different completed method runs")
        references = {}
        for frame, path in report["references"].items():
            if not str(frame).isdecimal() or int(frame) < 1 or int(frame) in references:
                raise ValueError("Retained report has invalid reference frame keys")
            references[int(frame)] = resolve(path)
        if not references:
            raise ValueError("Retained report has no reference images")
        report["references"] = references
        inputs = identity_inputs(identity)
        if not inputs:
            raise ValueError("Retained report input inventory is missing")
        resolved_inputs = {resolve(path): digest for path, digest in inputs.items()}
        if any(not path.is_file() or sha(path) != digest for path, digest in resolved_inputs.items()):
            raise ValueError("Retained report input is missing or changed")
        required = set(references.values())
        required.update(run[method] / name for run in runs for method in ("off_dir", "on_dir")
                        for name in ("manifest.json", "config.json", "captures.json", "timings.csv"))
        if not required <= set(resolved_inputs):
            raise ValueError("Retained report input inventory does not cover its declared sources")
        return report
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Invalid retained report for {condition.get('id')}: {error}") from error


def fixed_reference_assessment(policy):
    reason = ("User-authorized fixed-sample single-stream Bistro reference; "
              "uncertainty not evaluated under original dual-stream standard")
    return {"status": "not_evaluated", "passed": None, "reason": reason,
            "policy_id": policy["policy_id"]}
