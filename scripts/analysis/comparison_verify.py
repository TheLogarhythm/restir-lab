"""Recompute comparison evidence in independent scratch space and verify reports."""
from pathlib import Path
import tempfile
import numpy as np
from PIL import Image

from scripts.analysis.comparison_analysis import analyze, comparison_source
from scripts.analysis.comparison_report import checked_path, display_images, render_html, validate_coverage
from scripts.analysis.comparison_diagnostics import file_record, check_records
from experiment.fixed_reference import read_json
from experiment.comparison_config import validate_display
from rtxdi_common import sha


def normalized(value, base, destination):
    if isinstance(value, dict):
        if set(value) == {"path", "sha256"}:
            path = (base / value["path"]).resolve()
            if path.is_relative_to(base):
                path = destination / path.relative_to(base)
            return {"path":str(path), "sha256":value["sha256"]}
        return {k:normalized(v,base,destination) for k,v in value.items()}
    if isinstance(value, list):
        return [normalized(v,base,destination) for v in value]
    return value


def verify_report(analysis, report_path):
    analysis, report_path = Path(analysis).resolve(), Path(report_path).resolve()
    data, report = read_json(analysis), read_json(report_path)
    validate_coverage(data)
    root = report_path.parent
    if report.get("schema_version") != 3 or report.get("analysis") != file_record(analysis,root):
        raise ValueError("Report analysis binding differs")
    validate_display(report["display"],data["views"])
    check_records(report,root)
    from scripts.analysis import comparison_report
    generator = Path(comparison_report.__file__)
    if report["generator_sha256"] != sha(generator) or report["template_sha256"] != sha(generator.with_suffix(".html")):
        raise ValueError("Report generator/template differs; regenerate into a new directory")
    expected_keys = set()
    for key, pixels, source, transform in display_images(data,analysis.parent,report["display"]):
        expected_keys.add(key)
        actual = report["artifacts"][key]
        if actual["source"] != file_record(checked_path(source,analysis.parent),root) or actual["transform"] != transform:
            raise ValueError("Report preview source/exposure/map transform differs")
        with Image.open(checked_path(actual["image"],root)) as image:
            if image.mode != "RGB" or not np.array_equal(np.asarray(image),pixels):
                raise ValueError("Report pixels differ from the bound source and display transform")
    if set(report["artifacts"]) != expected_keys:
        raise ValueError("Report image coverage differs")
    html = checked_path(report["html"],root)
    if html.read_text(encoding="utf-8") != render_html(analysis,report,root):
        raise ValueError("Report HTML differs from saved analysis/artifact bindings")
    return {"html_sha256":sha(html), "report_sha256":sha(report_path), "ui_verified":False}


def verify(source, analysis, report=None, *, source_archive=None, scratch_parent=None):
    source, analysis = comparison_source(source), Path(analysis).resolve()
    data = read_json(analysis)
    if data.get("schema_version") != 3 or data.get("status") != "completed":
        raise ValueError("Require completed comparison analysis schema 3")
    if data["source"] != file_record(source,analysis.parent):
        raise ValueError("Analysis source binding differs")
    check_records(data,analysis.parent)
    archived = data["provenance"].get("historical_source_archive")
    if source_archive is None and archived is not None:
        source_archive = checked_path(archived,analysis.parent)
    # Independent scratch: never create files under the historical run or analysis.
    with tempfile.TemporaryDirectory(prefix="comparison-verify-",dir=scratch_parent) as temporary:
        scratch = Path(temporary).resolve() / "analysis"
        expected = analyze(source,scratch,source_archive=source_archive)
        if normalized(data,analysis.parent,analysis.parent) != normalized(expected,scratch,analysis.parent):
            raise ValueError("Analysis differs from recomputed coverage, masks, errors, diagnostics or references")
    result = {"status":"verified", "schema_version":3, "analysis_sha256":sha(analysis),
              "groups":list(data["spec"]["groups"]), "views":len(data["views"]),
              "capture_frames":data["spec"]["acquisition"]["capture_frames"],
              "seeds":data["spec"]["seeds"], "ui_verified":False}
    if report is not None:
        result.update(verify_report(analysis,report))
    return result
