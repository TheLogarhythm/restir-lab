"""Analyze aligned saved runs; this command never launches rendering."""
import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/run"))

import numpy as np
from rtxdi_common import sha
from experiment.reference import validate_lighting
from experiment.images import read_pfm
from experiment.sequence_metrics import Frame, SequenceRun, analyze_sequence, validate_alignment


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _csv(path, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


# Preserve the sequence adapter while sharing capture/geometry validation.
from experiment.saved_runs import (load_run, geometry_target as _geometry_target,
                                   SharedRegions as _SharedRegions)


def _load_run(directory, measured):
    item = load_run(directory, measured)
    frames = [Frame(index, item["captures"][index]["image"],
                    reset=item["captures"][index]["frame"]["reset"]) for index in measured]
    return {**item, "run":SequenceRun(str(item["config"]["seed"]), frames)}


def analyze_manifest(inputs, output):
    """Consume explicit saved-run paths/measurement frames; return JSON-ready results.

    Paths are relative to inputs. References are one static PFM or frame->PFM mapping.
    Geometry names one controlled run, optionally with static_frame for reuse.
    Scenes, budgets, reference convergence and independence claims remain the caller's
    experiment design; we verify capture hashes, target/control alignment and seeds.
    """
    inputs, output = Path(inputs).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"Analysis output already exists: {output}")
    spec = _json(inputs)
    measured = spec.get("frames", [])
    if (not measured or any(type(f) is not int or f < 0 for f in measured)
            or any(b != a + 1 for a,b in zip(measured,measured[1:]))):
        raise ValueError("frames must be an explicit contiguous measurement interval")
    methods = spec.get("methods")
    if not isinstance(methods, dict) or not methods:
        raise ValueError("methods must map method names to independent run directories")
    loaded, targets, controls, seeds = {}, {}, None, None
    geometry_targets = {}
    sampling_schedules = {}
    provenance = {}
    for name, paths in methods.items():
        if not isinstance(name, str) or not name or not isinstance(paths, list) or len(paths) < 2:
            raise ValueError("Each method requires a name and at least two independent runs")
        runs = [_load_run(inputs.parent / path, measured) for path in paths]
        validate_alignment([item["run"] for item in runs], spec.get("lag", 3))
        actual_seeds = {item["config"]["seed"] for item in runs}
        if seeds is not None and seeds != actual_seeds:
            raise ValueError("Compared methods must have matching independent seed coverage")
        seeds = actual_seeds
        settings = None
        for item in runs:
            config = item["config"]
            current = {
                "mode": config["mode"],
                "definition": {k:v for k,v in config["definition"].items() if k not in ("seed", "geometry_export")},
                "arguments": {k:v for k,v in config["arguments"].items() if k != "device.headless"},
                "build": item["manifest"].get("build", {})}
            if settings is not None and settings != current:
                raise ValueError("Independent runs within one method must have identical settings/build")
            settings = current
            seed = config["seed"]
            sampling = tuple(f["sampling_frame"] for f in config["frames"])
            if seed in sampling_schedules and sampling != sampling_schedules[seed]:
                raise ValueError("Compared methods have different RNG schedules for the same seed")
            if seed not in sampling_schedules:
                if any(set(sampling).intersection(other) for other in sampling_schedules.values()):
                    raise ValueError("Independent runs have overlapping RNG sampling_frame streams")
                sampling_schedules[seed] = sampling
            schedule = [{k:v for k,v in f.items() if k != "sampling_frame"}
                        for f in item["config"]["frames"]]
            if controls is not None and schedule != controls:
                raise ValueError("Compared runs/methods have different full frame control schedules")
            controls = schedule
            for frame in measured:
                capture = item["captures"][frame]
                key = capture["key"]
                if targets.setdefault(frame,key) != key:
                    raise ValueError("Compared runs/methods have different image targets")
                geometry_targets[frame] = _geometry_target(capture["target"])
        loaded[name] = runs
        provenance[name] = [{"directory":str(item["directory"]), "seed":item["config"]["seed"],
                             "manifest_sha256":sha(item["directory"]/"manifest.json"),
                             "config_sha256":item["manifest"]["config_sha256"],
                             "images":{str(f): item["records"][f]["image_sha256"] for f in measured}}
                            for item in runs]
    all_captures = [item["captures"][f] for runs in loaded.values() for item in runs for f in measured]
    validate_lighting(all_captures, all_captures[0]["manifest"].get("build", {}))
    references = spec.get("references")
    reference_hashes = {}
    if references is not None:
        if isinstance(references, str):
            references = inputs.parent / references
            reference_hashes["static"] = {"path":str(references.resolve()), "sha256":sha(references)}
        elif isinstance(references, dict):
            if set(references) != {str(f) for f in measured}:
                raise ValueError("Reference frame coverage must match measured frames exactly")
            references = {f: inputs.parent / references[str(f)] for f in measured}
            reference_hashes = {str(f): {"path":str(p.resolve()), "sha256":sha(p)} for f,p in references.items()}
        else:
            raise ValueError("references must be a static path or frame-to-path mapping")
    geometry = spec.get("geometry")
    if geometry is not None:
        if not isinstance(geometry, dict) or not isinstance(geometry.get("run"), str):
            raise ValueError("geometry must name a shared source run")
        # The source may include a static capture outside the measurement interval.
        source_directory = inputs.parent / geometry["run"]
        source_frame = geometry.get("static_frame")
        source_data = _load_run(source_directory, [source_frame] if source_frame is not None else measured)
        geometry = {**geometry, "data": source_data}
    expected_shape = (all_captures[0]["config"]["height"], all_captures[0]["config"]["width"], 3)
    def load_image(path):
        rgb = read_pfm(path)
        if rgb.shape != expected_shape:
            raise ValueError("Image dimensions differ from declared run resolution")
        return rgb

    output.mkdir(parents=True, exist_ok=False)
    _save(output/"analysis.json", {"status":"running", "inputs_sha256":sha(inputs)})
    try:
        masks = (_SharedRegions(geometry, geometry_targets, output, spec.get("classification_radius",30),
                                spec.get("hard_percent",10)) if geometry is not None else None)
        results = {name: analyze_sequence([item["run"] for item in runs], references=references,
                    masks=masks, regions=spec.get("regions"), lag=spec.get("lag",3),
                    radius=spec.get("radius",8), epsilon=spec.get("epsilon",1e-4),
                    block_rows=spec.get("block_rows",64), image_loader=load_image)
                   for name,runs in loaded.items()}
        rows, summaries = [], []
        for name, result in results.items():
            for frame in result["frames"]:
                for region, values in frame["regions"].items():
                    rows.append({"method":name, "frame":frame["frame"], "region":region,
                                 "temporal_end_frame":frame["temporal_end_frame"], **values})
            for region, values in result["summary"].items():
                summaries.append({"method":name, "region":region, **values})
        _csv(output/"frame-metrics.csv", rows)
        _csv(output/"summary.csv", summaries)
        result = {"schema_version":1, "status":"completed", "inputs_sha256":sha(inputs),
                  "sources":provenance, "references":reference_hashes,
                  "reference_validation":"Caller-supplied images: hashes/dimensions checked; target matching and convergence not certified",
                  "classification_radius":spec.get("classification_radius",30),
                  "hard_percent":spec.get("hard_percent",10),
                  "shared_regions":masks.records if masks is not None else {}, "methods":results}
        _save(output/"analysis.json", result)
        return result
    except Exception as error:
        _save(output/"analysis.json", {"status":"failed", "error":str(error), "inputs_sha256":sha(inputs)})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True, help="JSON with saved methods/runs and measurement frames")
    parser.add_argument("--output", type=Path, required=True, help="New analysis directory")
    args = parser.parse_args()
    analyze_manifest(args.inputs, args.output)
    print(f"Saved sequence metrics: {args.output}")


if __name__ == "__main__":
    main()
