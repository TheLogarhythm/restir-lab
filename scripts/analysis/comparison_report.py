"""Offline comparison reports from saved analysis; exposure is display-only."""
import base64
import copy
import json
from pathlib import Path
import numpy as np
from PIL import Image

from scripts.analysis.comparison_analysis import ROOT
from experiment.artifacts import save_json
from experiment.comparison_config import validate_display, validate_spec
from experiment.fixed_reference import read_json
from experiment.images import read_pfm, preview_rgb
from rtxdi_common import sha
from scripts.analysis.comparison_diagnostics import file_record
from experiment.runner import relative_path


def checked_path(record, base):
    path = (base / record["path"]).resolve()
    if sha(path) != record["sha256"]:
        raise ValueError(f"Report source/artifact changed: {path}")
    return path


def error_rgb(error):
    q = np.clip(error / 100, 0, 1)
    return np.rint(np.stack((q, .65*np.sqrt(q), .1*q), axis=-1)*255).astype(np.uint8)


def delta_rgb(delta):
    q = np.rint(delta * 327.67).astype(np.int32) + 32768
    return np.stack((q >> 8, q & 255, np.zeros_like(q)), axis=-1).astype(np.uint8)


def delta_metadata(delta):
    ordered = np.sort(np.abs(delta).ravel())
    counts = ordered.size - np.searchsorted(ordered, np.arange(1,1001)/10, side="right")
    return {"clipped_pixels_by_tenth_pp":counts.tolist(), "pixels":int(delta.size),
            "min_pp":float(delta.min()), "max_pp":float(delta.max()),
            "display_encoding":"signed 16-bit / 327.67 pp; max quantization error 0.00153 pp"}


def validate_coverage(data):
    """Validate names and axes before using any saved analysis key as an output path."""
    spec = data["spec"]
    validate_spec(spec)
    if set(data["views"]) != set(spec["views"]):
        raise ValueError("Report view coverage differs")
    for view in data["views"].values():
        if set(view["captures"]) != {str(f) for f in spec["acquisition"]["capture_frames"]}:
            raise ValueError("Report frame coverage differs")
        for capture in view["captures"].values():
            if set(capture["groups"]) != set(spec["groups"]) or set(capture["references"]) != set(spec["references"]):
                raise ValueError("Report group/reference coverage differs")
            for algorithm, group in capture["groups"].items():
                names = spec["groups"][algorithm]
                if any(group[k] != names[k] for k in names) or set(group["methods"]) != {names["original"],names["cgns"]}:
                    raise ValueError("Report method/reference binding differs")
                if any(set(method["per_seed"]) != {str(s) for s in spec["seeds"]} for method in group["methods"].values()):
                    raise ValueError("Report seed coverage differs")


def display_images(data, analysis_root, display):
    """Yield derived pixels with an exact source record; no metric computation."""
    def radiance(record, ev):
        path = checked_path(record,analysis_root)
        image = read_pfm(path)
        checked_path(record,analysis_root)
        return preview_rgb(image,ev)
    for view, value in data["views"].items():
        ev = display["exposure_ev"][view]
        for frame, capture in value["captures"].items():
            prefix = f"{view}/frame-{frame}"
            for component, reference in capture["references"].items():
                source = reference["image"]
                yield f"{prefix}/references/{component}", radiance(source,ev), source, {"kind":"radiance", "exposure_ev":ev}
            for algorithm, group in capture["groups"].items():
                for method, row in group["methods"].items():
                    for seed, sample in row["per_seed"].items():
                        source = sample["hdr"]
                        yield f"{prefix}/methods/{method}/seed-{seed}", radiance(source,ev), source, {"kind":"radiance", "exposure_ev":ev}
                source = group["maps"]
                with np.load(checked_path(source,analysis_root),allow_pickle=False) as maps:
                    for role in ("original", "cgns"):
                        yield f"{prefix}/{algorithm}/{role}-error", error_rgb(maps[role]), source, {"kind":"smape", "array":role, "range_percent":[0,100]}
                    yield f"{prefix}/{algorithm}/delta", delta_rgb(maps["improvement"]), source, {"kind":"delta", "array":"improvement", **delta_metadata(maps["improvement"])}
                checked_path(source,analysis_root)


def render_html(analysis, report, output):
    analysis, output = Path(analysis).resolve(), Path(output).resolve()
    checked_path(report["analysis"], output)
    data = copy.deepcopy(read_json(analysis))
    checked_path(report["analysis"], output)
    data["display"] = report["display"]
    def embed(key):
        record = report["artifacts"][key]
        path = checked_path(record["image"],output)
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    for view, value in data["views"].items():
        for frame, capture in value["captures"].items():
            prefix = f"{view}/frame-{frame}"
            for component, reference in capture["references"].items():
                reference["preview"] = embed(f"{prefix}/references/{component}")
            for algorithm, group in capture["groups"].items():
                for method, row in group["methods"].items():
                    for seed, sample in row["per_seed"].items():
                        sample["preview"] = embed(f"{prefix}/methods/{method}/seed-{seed}")
                for role in ("original", "cgns"):
                    group["methods"][group[role]]["error_preview"] = embed(f"{prefix}/{algorithm}/{role}-error")
                key = f"{prefix}/{algorithm}/delta"
                group["delta"] = {**report["artifacts"][key]["transform"], "display":embed(key)}
    data["report_provenance"] = {k:v for k,v in report.items() if k not in ("artifacts", "html")}
    payload = json.dumps(data, ensure_ascii=True, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c")
    return Path(__file__).with_suffix(".html").read_text(encoding="utf-8").replace("__ANALYSIS_JSON__",payload)


def generate(analysis, output, *, display=None):
    analysis, output = Path(analysis).resolve(), Path(output).resolve()
    analysis_record = file_record(analysis,output)
    data = read_json(analysis)
    checked_path(analysis_record,output)
    if data.get("schema_version") != 3 or data.get("status") != "completed" or not data.get("views"):
        raise ValueError("Report requires a completed comparison analysis")
    validate_coverage(data)
    display = copy.deepcopy(data["spec"]["display"] if display is None else display)
    validate_display(display,data["views"])
    output.mkdir(parents=True,exist_ok=False)
    report = {"schema_version":3, "analysis":analysis_record, "display":display,
              "generator_sha256":sha(Path(__file__)), "template_sha256":sha(Path(__file__).with_suffix(".html")),
              "artifacts":{}}
    images = output / "images"
    images.mkdir()
    for key, pixels, source, transform in display_images(data,analysis.parent,display):
        path = images / (key + ".png")
        path.parent.mkdir(parents=True,exist_ok=True)
        Image.fromarray(pixels).save(path)
        report["artifacts"][key] = {"image":file_record(path,output),
            "source":{"path":relative_path(checked_path(source,analysis.parent),output), "sha256":source["sha256"]}, "transform":transform}
    html = output / "comparison.html"
    html.write_text(render_html(analysis,report,output),encoding="utf-8")
    checked_path(analysis_record,output)
    for artifact in report["artifacts"].values(): checked_path(artifact["source"],output)
    report["html"] = file_record(html,output)
    save_json(output / "report.json",report)
    return html
