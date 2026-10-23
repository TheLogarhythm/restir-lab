"""Render the controlled PDF methods first, then validate references and errors."""
import argparse
from contextlib import contextmanager
import copy
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import traceback

import numpy as np

from rtxdi_common import ROOT, RENDERER, sha
from experiment.artifacts import save_json
from experiment.controlled_suite import build_config, completed_run, conditions
from experiment.controlled_reference_run import (REFERENCE_EXE, ReferenceManager, ReferencePrecisionError,
                                                reference_is_ready, validate_scene_policies)
from experiment.controlled_outputs import generate_versioned
from experiment.controlled_outputs import RECEIPT_NAME, _canonical, _matches
from experiment.controlled_budget import BudgetExceeded, ExperimentBudget
from experiment.controlled_launch import validate_launch_plan, claim_launch, load_scene_reference_policies
from experiment.controlled_evaluation import (selection_spec, select_reference_captures,
                                              target_inventory, quality_captures,
                                              reference_execution_order, validate_reference_priority_scenes)
from experiment.controlled_temporal import assess_static_reference_differences, check_temporal_references
from experiment.error_metrics import luminance, trmae_map
from experiment.images import preview_rgb, read_pfm
from experiment.reference import suite_captures
from experiment.runner import preflight, run_one
from experiment.scenes import validate_assets

PDF_EXE = RENDERER / "build/bin/FullSamplePdf.exe"
sys.path.insert(0, str(ROOT))
from scripts.analysis.pdf_artifacts import export_condition
from scripts.analysis import pdf_artifacts
from scripts.analysis.pdf_equal_time import analyze_equal_time
from scripts.analysis.pdf_summary import summarize_suite


def suite_path(name):
    if not re.fullmatch(r"pdf-controlled-[A-Za-z0-9_-]+", name):
        raise ValueError("Use a dedicated pdf-controlled-* directory under runs/")
    unresolved = ROOT / "runs" / name
    path = unresolved.resolve()
    if path.parent != (ROOT / "runs").resolve() or unresolved.is_symlink() or path.name != name:
        raise ValueError("Controlled suite must remain directly inside runs/")
    return path


def validate_pilot_gate(receipt, build, matrix_hash, reference_build):
    if (receipt.get("passed") is not True or receipt.get("matrix_sha256") != matrix_hash
            or receipt.get("build") != build or receipt.get("validation_version") != 2
            or receipt.get("reference_build") != reference_build
            or receipt.get("lighting_influence", {}).get("passed") is not True):
        raise ValueError("Quantitative reports require a passed reference pilot for this build and matrix")


def validate_technical_gate(receipt, build, matrix_hash):
    if (receipt.get("technical_passed") is not True or receipt.get("validation_version") != 1
            or receipt.get("kind") != "technical_only" or receipt.get("build") != build
            or receipt.get("matrix_sha256") != matrix_hash
            or receipt.get("references_accepted") is not False):
        raise ValueError("Method renders require a passed technical pilot for this build and matrix")


def validate_retained_raw_product(output, report):
    receipt = json.loads((output / RECEIPT_NAME).read_text())
    identity = receipt["identity"]
    normalized_report = json.loads(json.dumps([report], default=str))
    if _canonical(identity["reports"])[1] != _canonical(normalized_report)[1]:
        raise ValueError("Retained raw product points to different method runs")
    if any(not Path(path).is_file() or sha(Path(path)) != digest for path, digest in identity["inputs"].items()):
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
        reports = identity["reports"]
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
        inputs = identity["inputs"]
        if not isinstance(inputs, dict) or not inputs:
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


def export_raw_condition(output, off_dir, on_dir, *, exposure_ev=0., write_videos=True,
                         expected_resolution=(1920, 1080), expected_frames=None, fps=30,
                         check_budget=lambda: None):
    """Export seed-one visual comparisons without claiming reference accuracy."""
    check_budget()
    if type(fps) is not int or fps != 30 or not math.isfinite(exposure_ev):
        raise ValueError("Visual comparisons require 30 FPS and finite shared exposure")
    output = Path(output).resolve()
    if output.exists():
        raise ValueError(f"Refusing to overwrite existing visual comparison: {output}")
    sources = {"pdf-off": pdf_artifacts._captures(off_dir), "pdf-on": pdf_artifacts._captures(on_dir)}
    frames = sorted(sources["pdf-off"])
    if set(frames) != set(sources["pdf-on"]):
        raise ValueError("PDF off/on capture frame alignment mismatch")
    if expected_frames is not None and (len(set(expected_frames)) != len(expected_frames)
            or sorted(expected_frames) != frames):
        raise ValueError("Capture frames do not match expected_frames")
    if write_videos and any(b != a + 1 for a, b in zip(frames, frames[1:])):
        raise ValueError("Continuous visual comparison videos require consecutive captures")
    alignment = pdf_artifacts._config_alignment(off_dir, on_dir)
    if not alignment["checked"]:
        raise ValueError("Method visual comparisons require aligned seed-one run configs")
    width, height = expected_resolution
    if any(type(value) is not int or value < 1 for value in (width, height)):
        raise ValueError("Expected resolution must contain positive integer width,height")
    provenance = {}
    for method, paths in sources.items():
        provenance[method] = {}
        for frame, path in sorted(paths.items()):
            check_budget()
            if read_pfm(path).shape != (height, width, 3):
                raise ValueError(f"Image resolution mismatch for {path}")
            provenance[method][str(frame)] = {"path": str(path.resolve()), "sha256": sha(path)}
    executable = shutil.which("ffmpeg") if write_videos else None
    if write_videos and not executable:
        raise ValueError("FFmpeg is required for visual comparison videos")
    from PIL import Image
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    writer = None
    try:
        if write_videos:
            (stage / "videos").mkdir()
            writer = pdf_artifacts._VideoWriter(stage / "videos/comparison.mp4", (1920, 1080), fps, executable)
        selected = {frames[-1], *(frame for frame in pdf_artifacts.KEYFRAMES if frame in frames)}
        for frame in frames:
            check_budget()
            display = [Image.fromarray(preview_rgb(read_pfm(sources[method][frame]), exposure_ev))
                       for method in ("pdf-off", "pdf-on")]
            footer = f"Reference pending; visual comparison only | {exposure_ev:g} EV | frame {frame}"
            for method, image in zip(("pdf-off", "pdf-on"), display):
                pdf_artifacts._save_rgb(stage / f"frames/{method}/frame-{frame:04d}.png", image)
            if frame in selected:
                pdf_artifacts._save_rgb(stage / f"panels/frame-{frame:04d}.png",
                    pdf_artifacts._panel(display, ["PDF off", "PDF on"], footer=footer))
            if writer is not None:
                writer.append(pdf_artifacts._presentation(display, ["PDF off", "PDF on"], frame, footer))
        if writer is not None:
            writer.close()
            writer = None
        receipt = {"schema_version": 1, "kind": "method_visual_comparison", "references_accepted": False,
            "seed": 1, "frames": frames, "source_resolution": [width, height], "fps": fps,
            "logical_fps_not_performance": True, "display_transform": "Reinhard + sRGB",
            "exposure_ev": exposure_ev, "config_alignment": alignment, "inputs": provenance,
            "videos": ["videos/comparison.mp4"] if write_videos else []}
        save_json(stage / "manifest.json", receipt)
        check_budget()
        stage.rename(output)
        return receipt
    finally:
        if writer is not None and not writer.log.closed:
            writer.close(abort=True)
        if stage.exists():
            shutil.rmtree(stage)


def lighting_influence(base, peak, rois, *, load_image=read_pfm):
    """Require positive receiver illumination above measured reference variation."""
    values = []
    for record in (base, peak):
        values.append({"mean": luminance(load_image(record["image"])),
            "previous": luminance(load_image(record["previous_image"])),
            "a": luminance(load_image(record["streams"][0])),
            "b": luminance(load_image(record["streams"][1]))})
    rows = {}
    for roi in rois:
        x, y, width, height = (roi[k] for k in ("x", "y", "width", "height"))
        mask = (slice(y, y + height), slice(x, x + width))
        before, after = values
        signal = float(np.mean(after["mean"][mask] - before["mean"][mask]))
        noise = sum(float(np.mean(np.abs(v["a"][mask] - v["b"][mask]))) * .5 for v in values)
        drift = sum(float(np.mean(np.abs(v["mean"][mask] - v["previous"][mask]))) for v in values)
        threshold = 3 * max(noise, drift, 1e-12)
        rows[roi["name"]] = {"luminance_increase": signal, "half_stream_uncertainty": noise,
            "checkpoint_change": drift, "threshold": threshold, "passed": signal > threshold}
    return {"passed": any(row["passed"] for row in rows.values()), "receivers": rows}


@contextmanager
def exclusive_worker(directory):
    """The OS releases this named mutex even after an interrupted worker."""
    if os.name != "nt":
        raise RuntimeError("This D3D12 experiment worker requires Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    identity = hashlib.sha256(str(directory.resolve()).lower().encode()).hexdigest()[:24]
    ctypes.set_last_error(0)
    handle = kernel.CreateMutexW(None, True, "Local\\restir-pdf-" + identity)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        raise RuntimeError("Another worker already owns this experiment suite")
    try:
        yield
    finally:
        kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


class ControlledExperiment:
    def __init__(self, directory, *, reference_window=None, validation_only=False, reference_policies=None):
        self.reference_policies = validate_scene_policies(reference_policies)
        self.root = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.budget = ExperimentBudget(directory, authorization=reference_window)
        self.references_only = reference_window is not None
        if self.references_only and not validation_only:
            self.budget.check()
        matrix_path = directory / "conditions.json"
        matrix = conditions()
        if matrix_path.exists():
            if json.loads(matrix_path.read_text(encoding="utf-8")) != matrix:
                raise ValueError("Frozen condition matrix changed; inspect before resuming")
        else:
            save_json(matrix_path, matrix)
        self.matrix = {c["id"]: c for c in matrix}
        self.matrix_hash = sha(matrix_path)
        self.build = preflight(matrix[0]["definition"], PDF_EXE)
        self.reference_build = preflight(matrix[0]["definition"], REFERENCE_EXE)
        self.assets = {}
        self.state_path = directory / "state.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        if self.state.get("matrix_sha256", self.matrix_hash) != self.matrix_hash:
            raise ValueError("Saved worker state refers to a different matrix")
        self.state.update(worker_pid=os.getpid(), status="running", matrix_sha256=self.matrix_hash,
                          build=self.build, reference_build=self.reference_build,
                          worker_source_sha256=sha(Path(__file__)), execution_budget=self.budget.record)
        self.notify(stage="starting")
        self.references = ReferenceManager(directory / "references", self.reference_build, self.notify,
            before_segment=lambda: self.budget.timeout(21600), scene_policies=self.reference_policies)

    def notify(self, **updates):
        references = getattr(self, "references", None)
        if isinstance(references, ReferenceManager):
            updates.update(accepted_references=references.accepted_count,
                           precision_passed_references=references.accepted_count,
                           ready_references=references.ready_count,
                           fixed_budget_references=references.fixed_budget_count)
        self.state.update(updates, updated_utc=datetime.now(timezone.utc).isoformat())
        save_json(self.state_path, self.state)
        print(json.dumps(updates, ensure_ascii=False), flush=True)

    def render(self, condition, seed, enabled, *, area="formal", mode="combined", neighbors=4, tag=None,
               sampling_offset=0):
        config = build_config(condition, seed, enabled, mode, neighbors)
        for frame in config["frames"]:
            frame["sampling_frame"] += sampling_offset
        if condition["scene"]["scene_id"] not in self.assets:
            self.assets[condition["scene"]["scene_id"]] = validate_assets(condition["scene"])
        assets = self.assets[condition["scene"]["scene_id"]]
        parent = self.root / area / (tag or condition["id"]) / mode / f"neighbors-{neighbors}" / f"seed-{seed}" / ("on" if enabled else "off")
        for attempt in sorted(parent.glob("attempt-*")):
            if completed_run(attempt, config):
                manifest = json.loads((attempt / "manifest.json").read_text())
                if manifest["build"] != self.build or manifest["scene"]["sha256"] != assets["sha256"]:
                    raise ValueError("Completed render uses a different build or scene assets")
                return attempt
        if getattr(self, "references_only", False):
            raise ValueError(f"Completed method run required; references-only cannot render: {parent}")
        number = 0
        while (parent / f"attempt-{number}").exists():
            number += 1
        self.budget.check()
        self.notify(stage="render", condition=condition["id"], seed=seed, pdf=enabled, area=area)
        attempt = parent / f"attempt-{number}"
        run_one(config, attempt, self.build, assets, timeout=lambda: self.budget.timeout(1800), executable=PDF_EXE)
        self.budget.check()
        return attempt

    @staticmethod
    def captures(paths):
        return [capture for path in paths for capture in suite_captures(path)]

    def technical_pilot(self):
        self.notify(phase="pilot", stage="technical_checks")
        chosen = ("cornell-static", "bistro-interior-static", "bistro-exterior-static",
                  "bistro-interior-motion", "bistro-lighting")
        runs = {}
        for name in chosen:
            condition = self.matrix[name]
            # Earlier pilots round-tripped held start orientations through a
            # quaternion. Preserve them and validate the exact-start schedule anew.
            tag = name + "-exact-start" if condition["scenario"] == "motion" else None
            runs[name] = [self.render(condition, 1, enabled, area="pilot", tag=tag)
                          for enabled in (False, True)]
        # Exact replay checks the entire stochastic pipeline, independently of references.
        replay = self.render(self.matrix["cornell-static"], 1, False, area="pilot", tag="cornell-replay")
        for frame in (1, 20, 40, 128):
            a = read_pfm(runs["cornell-static"][0] / f"frame-{frame:04d}.pfm.gz")
            b = read_pfm(replay / f"frame-{frame:04d}.pfm.gz")
            if not np.array_equal(a, b):
                raise RuntimeError("Pilot deterministic replay differs")
        # Reset/fresh equality remains a separate technical check, not a baseline campaign.
        reset_condition = copy.deepcopy(self.matrix["cornell-static"])
        reset_condition["scenario"] = "reset"
        reset_condition["definition"]["captures"]["reset"] = [65]
        reset = self.render(reset_condition, 1, True, area="pilot", tag="cornell-reset")
        fresh_condition = copy.deepcopy(self.matrix["cornell-static"])
        fresh_condition["definition"].update(frames=2, reset_frame=2,
            motion={"start_frame": 1, "end_frame": 2},
            captures={scenario: [1] for scenario in ("static", "motion", "reset")})
        fresh = self.render(fresh_condition, 1, True, area="pilot", tag="cornell-fresh", sampling_offset=64)
        if not np.array_equal(read_pfm(reset / "frame-0065.pfm.gz"), read_pfm(fresh / "frame-0001.pfm.gz")):
            raise RuntimeError("Pilot reset/fresh radiance differs")
        resets = [json.loads(line)["frame"] for line in (reset / "resolved-frames.jsonl").read_text().splitlines()
                  if json.loads(line)["history_reset"]]
        if resets != [1, 65]:
            raise RuntimeError("Pilot did not acknowledge both history resets")
        receipt = {"technical_passed": True, "validation_version": 1, "kind": "technical_only",
            "matrix_sha256": self.matrix_hash, "build": self.build, "references_accepted": False,
            "checks": ["finite HDR/runtime state", "deterministic replay", "exact reset/fresh radiance",
                       "camera/light state and correspondence"],
            "runs": {name: [str(path.relative_to(self.root)) for path in paths] for name, paths in runs.items()},
            "completed_utc": datetime.now(timezone.utc).isoformat()}
        save_json(self.root / "pilot-technical-validation.json", receipt)
        self.notify(stage="technical_pilot_accepted", technical_pilot_passed=True)
        return receipt

    def reference_pilot(self, technical):
        validate_technical_gate(technical, self.build, self.matrix_hash)
        self.notify(phase="reference_validation", stage="pilot_references")
        receipt_path = self.root / "pilot-validation.json"
        if receipt_path.exists() and json.loads(receipt_path.read_text()).get("validation_version") == 2:
            receipt = json.loads(receipt_path.read_text())
            validate_pilot_gate(receipt, self.build, self.matrix_hash, self.reference_build)
            for key in receipt["reference_keys"]:
                self.references.paths(key)
            self.notify(temporal_scale=receipt["temporal_scale"], pilot_passed=True)
            return receipt
        runs = {name: [self.root / path for path in paths] for name, paths in technical["runs"].items()}
        # Three representative poses plus peak lighting validate the actual reference path.
        reference_keys = set()
        for name in ("cornell-static", "bistro-interior-static", "bistro-exterior-static"):
            captures = self.captures(runs[name])
            reference_keys.update(self.references.ensure(captures, self.matrix[name]["rois"]))
        lighting = [c for c in self.captures(runs["bistro-lighting"])
                    if c["frame"]["frame"] in (32, 48)]
        reference_keys.update(self.references.ensure(lighting, self.matrix["bistro-lighting"]["rois"]))
        light_keys = {c["frame"]["frame"]: c["key"] for c in lighting}
        while True:
            light_records = [self.references.paths(light_keys[frame]) for frame in (32, 48)]
            influence = lighting_influence(*light_records, self.matrix["bistro-lighting"]["rois"])
            save_json(self.root / "pilot-lighting-influence.json", influence)
            if influence["passed"]:
                break
            self.notify(stage="refining_lighting_influence", lighting_influence=influence)
            for key in set(light_keys.values()):
                self.references.ensure([c for c in lighting if c["key"] == key],
                    self.matrix["bistro-lighting"]["rois"],
                    min_samples=self.references.index["references"][key]["samples"])
        base = read_pfm(light_records[0]["image"])
        # A held lighting state has a known zero reference gradient. Freeze a
        # shared display range from its pilot noise rather than auto-scaling maps.
        high = 0.
        for path in runs["bistro-lighting"]:
            previous = read_pfm(path / "frame-0001.pfm.gz")
            for frame in range(2, 33):
                image = read_pfm(path / f"frame-{frame:04d}.pfm.gz")
                high = max(high, float(np.percentile(trmae_map(image, previous, base, base), 99)))
                previous = image
        temporal_scale = [0., max(high, 1e-6)]
        receipt = {"passed": True, "validation_version": 2, "lighting_influence": influence,
            "matrix_sha256": self.matrix_hash, "build": self.build,
            "reference_build": self.reference_build, "reference_keys": sorted(reference_keys),
            "temporal_scale": temporal_scale,
            "checks": ["finite HDR/runtime state", "deterministic replay", "exact reset/fresh radiance",
                       "camera/light state and correspondence", "two-checkpoint RMAE/SMAPE precision", "lighting influence"],
            "runs": {name: [str(path.relative_to(self.root)) for path in paths] for name, paths in runs.items()},
            "completed_utc": datetime.now(timezone.utc).isoformat()}
        save_json(receipt_path, receipt)
        self.notify(stage="pilot_accepted", pilot_passed=True, temporal_scale=temporal_scale)
        return receipt

    def condition_runs(self, condition, *, mode="combined", neighbors=4, area="formal"):
        runs = []
        for seed in (1, 2, 3):
            paths = {}
            for enabled in ((False, True) if seed % 2 else (True, False)):
                paths[enabled] = self.render(condition, seed, enabled, area=area, mode=mode, neighbors=neighbors)
            runs.append({"seed": seed, "off_dir": paths[False], "on_dir": paths[True]})
        return {"id": condition["id"], "scenario": condition["scenario"], "runs": runs,
                "references": {}, "rois": condition["rois"]}

    def reference_policy(self, condition):
        scene = condition.get("scene", {}).get("scene_id")
        return getattr(self, "reference_policies", {}).get(scene)

    def preserved_reports(self, raw):
        if not getattr(self, "reference_policies", {}).get("bistro"):
            return {}
        reports = {}
        for name, condition in self.matrix.items():
            if self.reference_policy(condition) is not None:
                continue
            relative = self.state.get("products", {}).get(f"analysis/{name}")
            if not relative:
                raise ValueError(f"Missing retained completed condition report: {name}")
            reports[name] = load_retained_condition_report(self.root / relative, condition, raw[name], root=self.root)
        return reports

    def condition_report(self, condition, raw_report, *, mode="combined", neighbors=4, area="formal"):
        runs = raw_report["runs"]
        captures = self.captures([path for run in runs for path in (run["off_dir"], run["on_dir"])])
        evaluation = selection_spec(condition["scenario"]) if getattr(self, "references_only", False) else None
        if evaluation is not None:
            captures = select_reference_captures(captures, condition["scenario"])
            references = {c["key"]: self.references.paths(c["key"]) for c in captures}
        else:
            references = self.references.ensure(captures, condition["rois"])
        assessment = {}
        policy = self.reference_policy(condition)
        if policy is not None:
            assessment = {name: fixed_reference_assessment(policy) for name in ("temporal", "differences")}
            if condition["scenario"] == "lighting":
                assessment["lighting_influence"] = fixed_reference_assessment(policy)
        elif condition["scenario"] != "static":
            while True:
                quality = check_temporal_references(captures, references, condition["rois"],
                                                   **({"evaluation": evaluation} if evaluation else {}))
                quality_path = self.root / area / condition["id"] / f"temporal-reference-{mode}-{neighbors}.json"
                save_json(quality_path, quality)
                if quality["passed"]:
                    break
                if not quality["refine_keys"]:
                    raise RuntimeError("Temporal reference check failed without refinable targets")
                for key in quality["refine_keys"]:
                    group = quality_captures(self.reference_quality_captures, {key}) if evaluation else [
                        c for c in captures if c["key"] == key]
                    self.references.ensure(group, condition["rois"],
                        min_samples=self.references.index["references"][key]["samples"])
                references = {key: self.references.paths(key) for key in references}
            assessment["temporal"] = quality
        else:
            assessment["differences"] = assess_static_reference_differences(captures, references, condition["rois"])
        mapping = {c["frame"]["frame"]: references[c["key"]]["image"] for c in captures}
        return {"id": condition["id"], "scenario": condition["scenario"], "runs": runs,
                "references": mapping, "rois": condition["rois"], "reference_assessment": assessment,
                **({"evaluation": evaluation} if evaluation else {}),
                **({"reference_policy": policy} if policy is not None else {})}

    def product(self, destination, reports, generate, *, settings=None):
        """Resume derived products only when their validated inputs still match."""
        inputs = set()
        for report in reports:
            inputs.update(Path(path) for path in report["references"].values())
            for run in report["runs"]:
                for method in ("off_dir", "on_dir"):
                    inputs.update(Path(run[method]) / name for name in
                                  ("manifest.json", "config.json", "captures.json", "timings.csv"))
        sources = [Path(__file__), *(ROOT / "scripts/analysis").glob("pdf_*.py"),
                   *(ROOT / "scripts/run/experiment").glob("*.py")]
        identity = {"reports": json.loads(json.dumps(reports, default=str)), "settings": settings,
                    "inputs": {str(path.resolve()): sha(path) for path in sorted(inputs)},
                    "sources": {path.relative_to(ROOT).as_posix(): sha(path) for path in sources}}
        def bounded_generate(output):
            self.budget.check()
            generate(output)
            self.budget.check()
        actual = generate_versioned(destination, identity, bounded_generate)
        products = {**self.state.get("products", {}),
                    destination.relative_to(self.root).as_posix(): actual.relative_to(self.root).as_posix()}
        self.notify(products=products)
        return actual

    def summary(self, name, reports):
        return self.product(self.root / "analysis" / name, reports,
            lambda output: summarize_suite(output, reports, references_accepted=True))

    def export(self, condition, report, destination):
        temporal_scale = self.state.get("temporal_scale", [0., 1.])
        settings = dict(fps=30, rois=condition["rois"],
            temporal_scale=temporal_scale, exposure_ev=condition["scene"]["preview"]["exposure_ev"],
            write_videos=condition["scenario"] != "static")
        if "evaluation" in report:
            settings.update(evaluation=report["evaluation"], write_videos=False)
        if "reference_policy" in report:
            settings.update(reference_policy=report["reference_policy"], write_videos=False)
        return self.product(destination, [report], lambda output: export_condition(output,
            report["runs"][0]["off_dir"], report["runs"][0]["on_dir"], report["references"],
            references_accepted=True, **settings), settings=settings)

    def export_raw(self, condition, report, destination):
        settings = dict(fps=30, exposure_ev=condition["scene"]["preview"]["exposure_ev"],
            write_videos=condition["scenario"] != "static",
            expected_frames=condition["definition"]["captures"][condition["scenario"]])
        return self.product(destination, [report], lambda output: export_raw_condition(output,
            report["runs"][0]["off_dir"], report["runs"][0]["on_dir"],
            check_budget=self.budget.check, **settings), settings=settings)

    def method_reports(self):
        """One layout for new captures and strict reuse of the 78 retained runs."""
        raw = {}
        order = ("cornell-static", "arcade-static", "bistro-interior-static", "bistro-exterior-static",
                 "bistro-interior-motion", "bistro-exterior-motion", "arcade-motion", "bistro-lighting")
        for name in order:
            raw[name] = self.condition_runs(self.matrix[name])
        spatial = copy.deepcopy(self.matrix["bistro-interior-static"])
        spatial["id"] += "-spatial-only"
        spatial_raw = self.condition_runs(spatial, mode="spatial", area="ablation")
        equal = []
        for name in ("bistro-interior-static", "bistro-exterior-static"):
            for neighbors in (2, 4, 8):
                condition = copy.deepcopy(self.matrix[name])
                if neighbors == 4:
                    report = {**raw[name], "id": f"{name}-neighbors-4"}
                else:
                    condition["id"] += f"-neighbors-{neighbors}"
                    report = self.condition_runs(condition, neighbors=neighbors, area="equal-time")
                equal.append((condition, neighbors, report))
        return raw, spatial, spatial_raw, equal

    def sparse_inputs(self):
        """Verify retained methods/products; never launch a method renderer."""
        self.references_only = True
        technical = json.loads((self.root / "pilot-technical-validation.json").read_text())
        validate_technical_gate(technical, self.build, self.matrix_hash)
        raw, spatial, spatial_raw, equal = self.method_reports()
        reports = [*raw.values(), spatial_raw, *(report for _, _, report in equal)]
        paths = {Path(run[key]) for report in reports for run in report["runs"] for key in ("off_dir", "on_dir")}
        if len(paths) != 78:
            raise ValueError("Sparse resume requires exactly 78 unique completed method runs")
        for name in (*raw, spatial["id"]):
            relative = self.state.get("products", {}).get(f"artifacts/raw/{name}")
            if not relative:
                raise ValueError(f"Missing retained raw product: {name}")
            output = (self.root / relative).resolve()
            if not output.is_relative_to((self.root / "artifacts/raw").resolve()):
                raise ValueError("Raw product escapes its retained output directory")
            validate_retained_raw_product(output, spatial_raw if name == spatial["id"] else raw[name])
        captures = []
        selected = []
        for report in [*raw.values(), spatial_raw, *(r for _, n, r in equal if n != 4)]:
            current = self.captures([path for run in report["runs"] for path in (run["off_dir"], run["on_dir"])])
            for capture in current:
                capture["condition_id"] = report["id"]
            captures.extend(current)
            selected.extend(select_reference_captures(current, report["scenario"]))
        inventory = target_inventory(selected)
        path = self.root / "reference-targets.json"
        if path.exists() and json.loads(path.read_text()) != inventory:
            raise ValueError("Frozen sparse reference target mapping changed")
        save_json(path, inventory)
        self.reference_quality_captures = quality_captures(captures, {row["key"] for row in inventory["states"]})
        scale_path = self.root / "temporal-display-scale.json"
        high, scale_inputs = 0., {}
        for report in raw.values():
            if report["scenario"] == "static":
                continue
            for method in ("off_dir", "on_dir"):
                directory = report["runs"][0][method]
                paths = [directory / f"frame-{frame:04d}.pfm.gz" for frame in (31, 32)]
                old, current = map(read_pfm, paths)
                # The fixed held-state pair has an exactly zero physical gradient.
                zero = np.zeros_like(current)
                high = max(high, float(np.percentile(trmae_map(current, old, zero, zero), 99)))
                scale_inputs.update({str(path.relative_to(self.root)): sha(path) for path in paths})
        calibration = {"pair": [31, 32], "percentile": 99, "reference_gradient": "known zero held state",
                       "range": [0., max(high, 1e-6)], "inputs": scale_inputs}
        if scale_path.exists() and json.loads(scale_path.read_text()) != calibration:
            raise ValueError("Frozen temporal display calibration changed")
        save_json(scale_path, calibration)
        self.state["temporal_scale"] = calibration["range"]
        self.preserved_condition_reports = self.preserved_reports(raw)
        return raw, spatial, spatial_raw, equal, inventory

    def execute_sparse(self, *, validate_only=False):
        raw, spatial, spatial_raw, equal, inventory = self.sparse_inputs()
        preserved = self.preserved_reports(raw)
        if validate_only:
            receipt = {"passed": True, "evaluation_scope": "sparse-v1", "method_runs": 78,
                "raw_products": 9, "reference_states": inventory["state_count"],
                "matrix_sha256": self.matrix_hash, "build": self.build,
                "reference_build": self.reference_build,
                "reference_targets_sha256": sha(self.root / "reference-targets.json"),
                "completed_utc": datetime.now(timezone.utc).isoformat()}
            save_json(self.root / "sparse-preparation-validation.json", receipt)
            self.notify(status="paused", phase="sparse_preparation", stage="ready_for_scheduled_start",
                evaluation_scope="sparse-v1", worker_pid=None, pilot_passed=False)
            return
        self.budget.check()
        self.notify(evaluation_scope="sparse-v1", phase="sparse_references", stage="static_references")
        failures, reports, emitted, rejected = {}, list(preserved.values()), set(preserved), set()
        rois = next(iter(self.matrix.values()))["rois"]
        conditions_to_report = [(condition, raw[condition["id"]], "combined", 4, "formal")
                                for condition in self.matrix.values()]
        conditions_to_report.append((spatial, spatial_raw, "spatial", 4, "ablation"))
        conditions_to_report.extend((condition, report, "combined", n, "equal-time")
                                    for condition, n, report in equal if n != 4)
        selected_by_condition = {condition["id"]: select_reference_captures(self.captures([
            path for run in raw_report["runs"] for path in (run["off_dir"], run["on_dir"])]), condition["scenario"])
            for condition, raw_report, _, _, _ in conditions_to_report}
        equal_reports = []

        def failed(error):
            failures[error.key] = {"samples": error.samples, "error": str(error)}
            save_json(self.root / "reference-failures.json", failures)
            self.notify(stage="reference_cap_reached", reference_failures=failures,
                        accepted_references=self.references.accepted_count)

        def emit_ready():
            # Deliver static/other completed conditions before an expensive later
            # target can consume the remaining reference-and-analysis allowance.
            for condition, raw_report, mode, neighbors, area in conditions_to_report:
                name = condition["id"]
                if name in emitted | rejected:
                    continue
                selected = selected_by_condition[name]
                if any(not reference_is_ready(self.references.index["references"].get(c["key"], {}),
                                              policy=self.reference_policy(condition)) for c in selected):
                    continue
                self.budget.check()
                try:
                    while True:
                        report = self.condition_report(condition, raw_report, mode=mode, neighbors=neighbors, area=area)
                        if condition["scenario"] != "lighting":
                            break
                        if self.reference_policy(condition) is not None:
                            influence = fixed_reference_assessment(self.reference_policy(condition))
                            influence["reference_inputs"] = {str(report["references"][frame]): sha(report["references"][frame])
                                                              for frame in (32, 48)}
                            report["reference_assessment"]["lighting_influence"] = influence
                            save_json(self.root / "sparse-lighting-influence.json", influence)
                            break
                        keys = {c["frame"]["frame"]: c["key"] for c in selected}
                        light_records = [self.references.paths(keys[f]) for f in (32, 48)]
                        influence = lighting_influence(*light_records, condition["rois"])
                        influence["reference_inputs"] = {str(record["image"]): sha(record["image"]) for record in light_records}
                        save_json(self.root / "sparse-lighting-influence.json", influence)
                        if influence["passed"]:
                            break
                        for key in {keys[32], keys[48]}:
                            self.references.ensure(quality_captures(self.reference_quality_captures, {key}), rois,
                                min_samples=self.references.index["references"][key]["samples"])
                    self.export(condition, report, self.root / "artifacts" / name)
                    self.summary(name, [report])
                    emitted.add(name)
                    if area == "formal":
                        reports.append(report)
                        self.summary("main", reports)
                    elif area == "equal-time":
                        equal_reports.append(report)
                    self.notify(completed_conditions=[report["id"] for report in reports])
                except ReferencePrecisionError as error:
                    failed(error)
                    rejected.add(name)

        for row in reference_execution_order(inventory["states"],
                getattr(self, "reference_priority_scenes", ())):
            self.budget.check()
            if getattr(self, "reference_policies", {}).get("bistro") and row["target"]["scene_id"] != "bistro":
                if not reference_is_ready(self.references.index["references"].get(row["key"], {})):
                    raise ValueError("Preserved non-Bistro reference is not precision accepted")
                self.references.paths(row["key"])
                continue
            try:
                self.references.ensure(quality_captures(self.reference_quality_captures, {row["key"]}), rois)
            except ReferencePrecisionError as error:
                failed(error)
            emit_ready()
        skipped = [condition["id"] for condition, *_ in conditions_to_report if condition["id"] not in emitted]
        if reports:
            self.summary("main", reports)
        for report in reports:
            if report["id"] in ("bistro-interior-static", "bistro-exterior-static"):
                equal_reports.append({**report, "id": report["id"] + "-neighbors-4"})
        if len(equal_reports) == 6:
            summary = self.summary("equal-time", equal_reports)
            self.product(self.root / "analysis/equal-time-comparison", equal_reports,
                lambda output: analyze_equal_time(summary, output), settings={"summary_input": str(summary)})
        self.notify(status="sparse_results_ready" if not skipped else "sparse_partial_results",
            phase="analysis", stage="interpret_results", skipped_conditions=skipped,
            reference_failures=failures, completed_conditions=[report["id"] for report in reports])

    def execute(self, pilot_only=False, *, references_only=False, validate_only=False):
        if getattr(self, "reference_policies", {}) and not references_only:
            raise ValueError("Fixed Bistro reference policy requires references-only evaluation")
        if references_only:
            return self.execute_sparse(validate_only=validate_only)
        if getattr(self, "state", {}).get("evaluation_scope") == "sparse-v1":
            raise ValueError("Sparse preparation requires --references-only and its approved reference window")
        technical = self.technical_pilot()
        validate_technical_gate(technical, self.build, self.matrix_hash)
        if pilot_only:
            self.notify(status="technical_pilot_completed", stage="awaiting_method_renders")
            return
        order = ("cornell-static", "arcade-static", "bistro-interior-static", "bistro-exterior-static",
                 "bistro-interior-motion", "bistro-exterior-motion", "arcade-motion", "bistro-lighting")
        raw, spatial_condition, spatial_raw, equal_raw = self.method_reports()
        self.notify(phase="method_renders", stage="raw_renders_completed", raw_renders_completed=True,
                    completed_method_runs=78)
        for name in order:
            self.export_raw(self.matrix[name], raw[name], self.root / "artifacts/raw" / name)
        self.export_raw(spatial_condition, spatial_raw, self.root / "artifacts/raw" / spatial_condition["id"])
        self.notify(stage="raw_visuals_completed", raw_visuals_completed=True)

        # Quantitative products retain the complete original reference gates.
        receipt = self.reference_pilot(technical)
        validate_pilot_gate(receipt, self.build, self.matrix_hash, self.reference_build)
        reports = []
        for name in order:
            condition = self.matrix[name]
            self.notify(phase="reference_validation", stage="condition", condition=name)
            report = self.condition_report(condition, raw[name])
            self.export(condition, report, self.root / "artifacts" / name)
            reports.append(report)
            self.summary(name, [report])
        main_summary = self.summary("main", reports)
        ablation = self.condition_report(spatial_condition, spatial_raw, mode="spatial", area="ablation")
        self.export(spatial_condition, ablation, self.root / "artifacts" / spatial_condition["id"])
        self.summary("spatial-only", [ablation])
        equal_time = []
        for condition, budget, report in equal_raw:
            if budget == 4:
                report = next(r for r in reports if r["id"] == condition["id"])
                report = {**report, "id": f"{condition['id']}-neighbors-{budget}"}
            else:
                report = self.condition_report(condition, report, neighbors=budget, area="equal-time")
            equal_time.append(report)
        budget_summary = self.summary("equal-time", equal_time)
        comparison = self.product(self.root / "analysis/equal-time-comparison", equal_time,
            lambda output: analyze_equal_time(budget_summary, output),
            settings={"summary_input": str(budget_summary)})
        self.notify(status="rendering_and_tables_completed", phase="analysis", stage="interpret_results",
                    completed_conditions=list(order), summary_directory=main_summary.relative_to(self.root).as_posix(),
                    equal_time_directory=comparison.relative_to(self.root).as_posix(),
                    completed_utc=datetime.now(timezone.utc).isoformat())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-name", default="pdf-controlled-20261018")
    parser.add_argument("--pilot-only", action="store_true", help="Validate the technical pilot without generating references")
    parser.add_argument("--references-only", action="store_true", help="Reuse all 78 methods and run fixed sparse reference evaluation")
    parser.add_argument("--reference-window", type=Path, help="Explicitly approved reference/analysis budget authorization")
    parser.add_argument("--validate-only", action="store_true", help="Validate retained methods and sparse targets without rendering")
    parser.add_argument("--launch-plan", type=Path, help="Pinned one-time scheduled launch inputs")
    parser.add_argument("--reference-policy", type=Path, help="Explicit fixed Bistro reference policy")
    args = parser.parse_args()
    if args.references_only != (args.reference_window is not None):
        parser.error("--references-only requires --reference-window, and the window only authorizes references")
    if (args.validate_only or args.launch_plan) and not args.references_only:
        parser.error("Validation and scheduled launch require --references-only")
    if args.reference_policy is not None and not args.references_only:
        parser.error("A reference policy requires --references-only")
    if args.reference_policy is not None and not args.validate_only:
        parser.error("--reference-policy is validation-only; execution requires a pinned --launch-plan")
    if args.pilot_only and args.references_only:
        parser.error("References-only must reuse its completed technical validation")
    if args.validate_only and args.launch_plan:
        parser.error("Validate preparation separately; do not consume a scheduled launch")
    root = suite_path(args.output_name)
    with exclusive_worker(root):
        if args.launch_plan and args.launch_plan.with_name(args.launch_plan.name + ".started.json").exists():
            print("One-time launch was already consumed; preserving saved experiment state.", flush=True)
            return
        worker = None
        try:
            plan = validate_launch_plan(root, args.launch_plan) if args.launch_plan else None
            priority = validate_reference_priority_scenes(
                plan.get("reference_priority_scenes", []) if plan is not None else [])
            policies = load_scene_reference_policies(root, plan, policy_path=args.reference_policy)
            worker = ControlledExperiment(root, reference_window=args.reference_window,
                                          validation_only=args.validate_only, reference_policies=policies)
            worker.reference_priority_scenes = priority
            if plan is not None:
                authorization = worker.budget.record["authorization"]
                if any(plan[key] != authorization[key] for key in ("not_before_utc", "deadline_utc")):
                    raise ValueError("Launch plan and approved budget window differ")
                worker.sparse_inputs()
                claim_launch(args.launch_plan)
            worker.execute(args.pilot_only, references_only=args.references_only, validate_only=args.validate_only)
        except BaseException as error:
            status = "failed"
            if isinstance(error, BudgetExceeded):
                status = "budget_exhausted"
            elif worker is not None and not args.validate_only:
                try:
                    worker.budget.check()
                except BudgetExceeded as exhausted:
                    status, error = "budget_exhausted", exhausted
            if worker is not None:
                worker.notify(status=status, error=str(error), traceback=traceback.format_exc())
            else:
                root.mkdir(parents=True, exist_ok=True)
                path = root / "state.json"
                try:
                    state = json.loads(path.read_text()) if path.exists() else {}
                except (OSError, ValueError):
                    state = {}
                state.update(status=status, worker_pid=os.getpid(), error=str(error),
                             traceback=traceback.format_exc(), updated_utc=datetime.now(timezone.utc).isoformat())
                save_json(path, state)
            if status == "budget_exhausted":
                return
            raise


if __name__ == "__main__":
    main()
