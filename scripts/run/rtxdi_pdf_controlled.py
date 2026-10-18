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
from experiment.controlled_reference_run import REFERENCE_EXE, ReferenceManager
from experiment.controlled_outputs import generate_versioned
from experiment.controlled_budget import BudgetExceeded, ExperimentBudget
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
    def __init__(self, directory):
        self.root = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.budget = ExperimentBudget(directory)
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
            before_segment=lambda: self.budget.timeout(21600))

    def notify(self, **updates):
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

    def condition_report(self, condition, raw_report, *, mode="combined", neighbors=4, area="formal"):
        runs = raw_report["runs"]
        captures = self.captures([path for run in runs for path in (run["off_dir"], run["on_dir"])])
        references = self.references.ensure(captures, condition["rois"])
        assessment = {}
        if condition["scenario"] != "static":
            while True:
                quality = check_temporal_references(captures, references, condition["rois"])
                quality_path = self.root / area / condition["id"] / f"temporal-reference-{mode}-{neighbors}.json"
                save_json(quality_path, quality)
                if quality["passed"]:
                    break
                if not quality["refine_keys"]:
                    raise RuntimeError("Temporal reference check failed without refinable targets")
                for key in quality["refine_keys"]:
                    group = [c for c in captures if c["key"] == key]
                    self.references.ensure(group, condition["rois"],
                        min_samples=self.references.index["references"][key]["samples"])
                references = {key: self.references.paths(key) for key in references}
            assessment["temporal"] = quality
        else:
            assessment["differences"] = assess_static_reference_differences(captures, references, condition["rois"])
        mapping = {c["frame"]["frame"]: references[c["key"]]["image"] for c in captures}
        return {"id": condition["id"], "scenario": condition["scenario"], "runs": runs,
                "references": mapping, "rois": condition["rois"], "reference_assessment": assessment}

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

    def execute(self, pilot_only=False):
        technical = self.technical_pilot()
        validate_technical_gate(technical, self.build, self.matrix_hash)
        if pilot_only:
            self.notify(status="technical_pilot_completed", stage="awaiting_method_renders")
            return
        raw = {}
        order = ("cornell-static", "arcade-static", "bistro-interior-static", "bistro-exterior-static",
                 "bistro-interior-motion", "bistro-exterior-motion", "arcade-motion", "bistro-lighting")
        for name in order:
            self.notify(phase="method_renders", stage="condition", condition=name)
            raw[name] = self.condition_runs(self.matrix[name])
        # One focused spatial-only ablation, and bounded three-budget curves.
        self.notify(phase="ablation", stage="spatial_only")
        condition = copy.deepcopy(self.matrix["bistro-interior-static"])
        condition["id"] += "-spatial-only"
        spatial_condition = condition
        spatial_raw = self.condition_runs(condition, mode="spatial", area="ablation")
        equal_raw = []
        for name in ("bistro-interior-static", "bistro-exterior-static"):
            for budget in (2, 4, 8):
                condition = copy.deepcopy(self.matrix[name])
                if budget == 4:
                    report = raw[name]
                    report = {**report, "id": f"{name}-neighbors-{budget}"}
                else:
                    condition["id"] += f"-neighbors-{budget}"
                    self.notify(phase="equal_time", stage="budget", condition=name, neighbors=budget)
                    report = self.condition_runs(condition, neighbors=budget, area="equal-time")
                equal_raw.append((condition, budget, report))
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
    args = parser.parse_args()
    root = suite_path(args.output_name)
    with exclusive_worker(root):
        worker = None
        try:
            worker = ControlledExperiment(root)
            worker.execute(args.pilot_only)
        except BaseException as error:
            status = "failed"
            if isinstance(error, BudgetExceeded):
                status = "budget_exhausted"
            elif worker is not None:
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
