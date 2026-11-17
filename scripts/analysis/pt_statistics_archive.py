"""Verify a statistics-only PT archive without treating retired HDR as available."""
from __future__ import annotations
import csv
from pathlib import Path
import numpy as np
from scripts.analysis.pt_archive_common import (
    ROOT, VIEWS, METHODS, SEEDS, child, read, require, sha, verify_inventory,
)

KIND = "falcor_pt_statistics_archive"

def inventory(archive, manifest):
    require(child(archive, "manifest.json").is_file(), "Missing archive file: manifest.json")
    indexed = verify_inventory(
        archive, manifest["files"], allowed_unindexed={"manifest.json"},
        extra_message="Missing or unindexed archive files",
    )
    require(not any(Path(p).suffix.lower() in {".exr", ".hdr"} for p in indexed), "Unexpected HDR in statistics archive")
    return indexed

def rows(archive, name):
    with child(archive, "statistics/" + name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))

def coverage(summary, seeds, frames):
    pairs = {(v, m) for v in VIEWS for m in METHODS}
    require(len(summary) == len(pairs) and {(r["view"], r["method"]) for r in summary} == pairs, "Summary coverage mismatch")
    expected_seeds = {(v, m, s) for v, m in pairs for s in SEEDS}
    require(len(seeds) == len(expected_seeds) and {(r["view"], r["method"], int(r["seed"])) for r in seeds} == expected_seeds, "Seed coverage mismatch")
    expected_frames = {(v, m, s, f) for v, m, s in expected_seeds for f in range(41, 57)}
    require(len(frames) == len(expected_frames) and {(r["view"], r["method"], int(r["seed"]), int(r["frame"])) for r in frames} == expected_frames, "Frame coverage mismatch")
    for row in summary:
        selected = [float(r["smape_percent"]) for r in seeds if (r["view"], r["method"]) == (row["view"], row["method"])]
        require(abs(np.mean(selected) - float(row["smape_percent"])) < 1e-9, "Summary/seed mean mismatch")
        require(abs(np.std(selected, ddof=1) - float(row["smape_seed_sd"])) < 1e-9, "Summary seed SD mismatch")
    for row in seeds:
        selected = [float(r["smape_percent"]) for r in frames if (r["view"], r["method"], int(r["seed"])) == (row["view"], row["method"], int(row["seed"]))]
        require(abs(np.mean(selected) - float(row["smape_percent"])) < 1e-9, "Seed/frame mean mismatch")

def inspect(archive):
    archive = Path(archive).resolve()
    m = read(archive / "manifest.json")
    require(m.get("kind") == KIND, "Not a statistics archive")
    require(m.get("capabilities") == {"redraw_figures": True, "raw_quality_hdr": False, "arbitrary_quality_reanalysis": False}, "Misleading archive capabilities")
    require(set(m["views"]) == VIEWS and set(m["methods"]) == METHODS, "Unexpected view/method coverage")
    return {"kind": KIND, "views": list(m["views"]), "methods": m["methods"],
            "capabilities": m["capabilities"], "summary": m["summary"],
            "integrity_scope": "Manifest only; omit --inspect to verify retained files and statistics",
            "renderer_launched": False}

def verify(archive):
    archive = Path(archive).resolve()
    inspect(archive)
    m = read(archive / "manifest.json")
    require(m["schema_version"] == 1 and m["status"] == "completed_compacted" and m["path_base"] == "archive_root", "Unsupported archive schema")
    require(m["resolution"] == [1920, 1080] and m["quality_seed_offsets"] == SEEDS, "Unexpected capture settings")
    require(m["quality_frames"] == list(range(41, 57)) and m["timing_frames"] == list(range(41, 105)), "Unexpected schedules")
    indexed = inventory(archive, m)
    summary = rows(archive, "summary.csv")
    coverage(summary, rows(archive, "quality-seeds.csv"), rows(archive, "quality-frames.csv"))
    require(read(child(archive, "statistics/summary.json")) == [
        {k: (r[k] if k in ("view", "method") else None if r[k] == "" else float(r[k])) for k in r} for r in summary], "CSV/JSON summary mismatch")
    original = read(child(archive, m["original_manifest"]))
    original_index = {r["path"]: r for r in original["files"]}
    retired = read(child(archive, m["retired_hdr"]))
    require(len(retired["files"]) == 1542 and retired["files_count"] == 1542, "Retired HDR coverage mismatch")
    require(retired["bytes"] == sum(r["bytes"] for r in retired["files"]), "Retired byte count mismatch")
    require({r["path"] for r in retired["files"]} == {n for n in original_index if Path(n).suffix == ".exr"}, "Retired inventory mismatch")
    for r in retired["files"]:
        require(all(r[k] == original_index[r["path"]][k] for k in ("bytes", "sha256")), "Retired evidence changed")
    relocation = {r["source"]: r for r in read(child(archive, m["relocations"]))}
    for r in relocation.values():
        require(all(indexed[r["path"]][k] == r[k] for k in ("bytes", "sha256")), "Relocated bytes changed: " + r["path"])
    def relocated(relative):
        return child(archive, relocation["runs/pt-6-views-spatial-compare/" + relative]["path"])
    for view, info in m["views"].items():
        metric = read(child(archive, info["metrics"]))
        require(metric["view"] == view and set(metric["methods"]) == METHODS, "Metric coverage mismatch")
        reference = read(child(archive, info["reference"]))["final"]
        require(sha(child(ROOT, reference["path"])) == reference["sha256"], "Final reference changed: " + view)
        with np.load(child(archive, info["arrays"]), allow_pickle=False) as arrays:
            for method in METHODS:
                row = next(r for r in summary if (r["view"], r["method"]) == (view, method))
                for suffix, column in (("smape", "smape_percent"), ("temporal", "temporal_covariance"), ("spatial", "spatial_covariance")):
                    values = arrays[method + "_" + suffix]
                    require(values.shape == (1080, 1920) and np.isfinite(values).all(), "Invalid numeric map")
                    require(abs(float(values.mean(dtype=np.float64)) - float(row[column])) < 1e-5, "Map/summary mismatch")
                for q in original["views"][view]["methods"][method]["quality"]:
                    capture = read(relocated(q["directory"] + "/manifest.json"))
                    require(capture["status"] == "completed" and len(capture["artifacts"]) == 16, "Invalid capture evidence")
                timing = original["views"][view]["methods"][method]["timing"]
                require(timing["included"] == (view != "emerald-square"), "Timing exclusion changed")
                valid = read(relocated(timing["directory"] + "/timing-validation.json"))
                require(sha(relocated(timing["directory"] + "/timings.json")) == valid["sha256"], "Raw timing changed")
                require(valid["measured_gpu_frames"] == list(range(41, 105)), "Timing schedule changed")
        with np.load(child(archive, info["strips"]), allow_pickle=False) as strips:
            for method in METHODS - {"temporal-off"}:
                require(strips[method + "_strips"].shape == (4, 16, 2, 128, 3), "Invalid strip coverage")
        for name in ["reference.png"] + [x + "-frame48-seed0.png" for x in METHODS]:
            require(f"images/{view}/{name}" in indexed, "Missing selected PNG")
    return {"status": "verified", "kind": KIND, "hashed_archive_files": len(indexed),
            "quality_statistic_rows": 1536, "quality_seed_rows": 96, "summary_rows": 24,
            "retired_hdr_files": 1542, "retained_full_quality_hdr": 0, "selected_pngs": 30,
            "final_references": 6, "timing_captures": 24, "included_timing_captures": 20,
            "renderer_launched": False}
