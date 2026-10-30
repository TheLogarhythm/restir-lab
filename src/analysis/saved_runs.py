"""Shared offline image summaries and conservative independent-run analysis."""

import json
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from image_io.images import read_image
from metrics.error_metrics import smape
from metrics.sequence_metrics import Frame, SequenceRun, analyze_sequence
from records import load_frame, read_run
from records.readers import validate_record
from records.provenance import package_source_hashes, sha256


def _reference_record(path):
    path = Path(path).resolve()
    return {
        "path": str(path),
        "sha256": sha256(path),
        "target_or_convergence_certified": False,
        "validation": "Caller-supplied image; transport equivalence and convergence are caller responsibility",
    }


def _validate_reference(record):
    if sha256(record["path"]) != record["sha256"]:
        raise ValueError("Reference image changed during analysis")


def describe_run(run, reference_image=None):
    """Describe either backend; an explicit reference is not certified ground truth."""
    validate_record(run)
    reference = None
    reference_record = None
    if reference_image is not None:
        reference_record = _reference_record(reference_image)
        reference = read_image(reference_record["path"])
        if reference.shape != (run.height, run.width, 3):
            raise ValueError("Reference dimensions differ from run")
    rows = []
    for frame in run.frames:
        rgb = load_frame(run, frame.index)
        rows.append(
            {
                "frame": frame.index,
                "image": frame.image.relative_to(run.directory).as_posix(),
                "sha256": frame.sha256,
                "history_reset": frame.reset,
                "sampling_frame": frame.sampling_frame,
                "min": float(rgb.min()),
                "max": float(rgb.max()),
                "mean_rgb": float(np.mean(rgb, dtype=np.float64)),
                "smape_percent": (
                    smape(rgb, reference) if reference is not None else None
                ),
            }
        )
    if reference_record is not None:
        _validate_reference(reference_record)
    validate_record(run)
    return {
        "schema_version": 1,
        "status": "completed",
        "backend": run.backend,
        "run_directory": str(run.directory),
        "manifest_sha256": run.manifest_sha256,
        "resolution": [run.width, run.height],
        "seed": run.seed,
        "capabilities": sorted(run.capabilities),
        "limitations": list(run.limitations),
        "transport": run.provenance["transport"],
        "record_files": run.provenance["record_files"],
        "reference": reference_record,
        "frames": rows,
        "analysis_source_sha256": package_source_hashes(),
    }


def _settings(run):
    config = run.config
    return {
        "mode": config["mode"],
        "scenario": config["scenario"],
        "definition": {
            k: v
            for k, v in config["definition"].items()
            if k not in ("seed", "geometry_export")
        },
        "arguments": {
            k: v for k, v in config["arguments"].items() if k != "device.headless"
        },
        "build": run.provenance["manifest"]["build"],
        "rng_schedule": run.provenance["rng_schedule"],
    }


def independent_sequences(runs, frames):
    """Normalize repeats of one method; missing RNG/history evidence is an error."""
    runs, frames = list(runs), list(frames)
    if len(runs) < 2 or any(
        "independent_trials" not in run.capabilities for run in runs
    ):
        raise ValueError(
            "At least two runs with recorded independent RNG/control evidence are required"
        )
    if len({run.backend for run in runs}) != 1:
        raise ValueError("Cross-backend transport equivalence is not certified")
    if (
        not frames
        or any(type(f) is not int for f in frames)
        or any(b != a + 1 for a, b in zip(frames, frames[1:]))
    ):
        raise ValueError("Measured frames must be a contiguous increasing interval")
    seeds = [run.seed for run in runs]
    if len(set(seeds)) != len(runs) or any(seed is None for seed in seeds):
        raise ValueError("Independent runs require unique recorded seeds")
    controls, settings, targets, lighting = None, None, None, None
    used_sampling_frames = set()
    sequences = []
    for run in runs:
        validate_record(run)
        current_controls = [
            {k: v for k, v in row.items() if k != "sampling_frame"}
            for row in run.controls
        ]
        current_settings = _settings(run)
        current_targets = [run.frame(index).target for index in frames]
        current_lighting = run.provenance["lighting_signature"]
        if controls is not None and (
            current_controls != controls
            or current_settings != settings
            or current_targets != targets
            or current_lighting != lighting
        ):
            raise ValueError(
                "Independent runs differ in full controls, settings, target or lighting provenance"
            )
        controls, settings, targets, lighting = (
            current_controls,
            current_settings,
            current_targets,
            current_lighting,
        )
        sampling = {row["sampling_frame"] for row in run.controls}
        if used_sampling_frames.intersection(sampling):
            raise ValueError("Independent RNG sampling schedules overlap")
        used_sampling_frames.update(sampling)
        sequences.append(
            SequenceRun(
                f"{run.backend}:{run.seed}",
                [
                    Frame(index, run.frame(index).image, reset=run.frame(index).reset)
                    for index in frames
                ],
            )
        )
    return sequences


def analyze_repeats(runs, frames, **options):
    """Return metrics plus saved-input/source hashes and explicit reference evidence.

    references accepts an HDR path or a frame-to-HDR-path mapping. References
    remain caller supplied; their transport equivalence is not certified.
    """
    runs, frames = list(runs), list(frames)
    sequences = independent_sequences(runs, frames)
    owners = {frame.image: (run, frame.index) for run in runs for frame in run.frames}
    references = options.pop("references", None)
    reference_paths, reference_records = {}, {}
    if references is not None:
        for index in frames:
            if isinstance(references, Mapping):
                if index not in references:
                    raise ValueError(f"Missing reference for frame {index}")
                value = references[index]
            else:
                value = references
            path = Path(value).resolve()
            reference_paths[index] = path
            if path not in reference_records:
                reference_records[path] = _reference_record(path)

    def load(path):
        path = Path(path).resolve()
        reference = reference_records.get(path)
        if reference is not None:
            _validate_reference(reference)
        if path in owners:
            run, index = owners[path]
            rgb = load_frame(run, index)
        elif reference is not None:
            rgb = read_image(path)
        else:
            raise ValueError("Image was not bound to the saved analysis")
        if reference is not None:
            _validate_reference(reference)
        return rgb

    result = analyze_sequence(
        sequences,
        image_loader=load,
        references=reference_paths if references is not None else None,
        **options,
    )
    for reference in reference_records.values():
        _validate_reference(reference)
    inputs = []
    for run in runs:
        validate_record(run)
        inputs.append(
            {
                "backend": run.backend,
                "run_directory": str(run.directory),
                "manifest_sha256": run.manifest_sha256,
                "record_files": run.provenance["record_files"],
                "seed": run.seed,
                "transport": run.provenance["transport"],
                "capabilities": sorted(run.capabilities),
                "limitations": list(run.limitations),
                "frames": [
                    {
                        "frame": index,
                        "image": run.frame(index)
                        .image.relative_to(run.directory)
                        .as_posix(),
                        "sha256": run.frame(index).sha256,
                        "history_reset": run.frame(index).reset,
                        "sampling_frame": run.frame(index).sampling_frame,
                    }
                    for index in frames
                ],
            }
        )
    result.update(
        status="completed",
        input_runs=inputs,
        references=[
            {"frame": index, **reference_records[path]}
            for index, path in reference_paths.items()
        ],
        analysis_source_sha256=package_source_hashes(),
    )
    return result


def write_analysis(directory, output, reference_image=None):
    """Write a new analysis directory, never inside or over an input run."""
    directory, output = Path(directory).resolve(), Path(output).resolve()
    if output.is_relative_to(directory):
        raise ValueError("Analysis output must be outside the input run")
    if output.exists():
        raise FileExistsError(output)
    run = read_run(directory)
    output.mkdir(parents=True, exist_ok=False)
    try:
        result = describe_run(run, reference_image)
    except Exception as exc:
        (output / "analysis.json").write_text(
            json.dumps({"status": "failed", "error": str(exc)}, indent=2) + "\n",
            encoding="utf-8",
        )
        raise
    (output / "analysis.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return output / "analysis.json"
