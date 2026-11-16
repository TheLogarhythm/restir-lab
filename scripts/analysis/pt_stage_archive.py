"""Read-only integrity verification of the compact PT six-view reporting archive."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "runs/pt-6-views-spatial-compare"
VIEWS = {"bistro-interior", "bistro-exterior", "classroom", "emerald-square", "veach-ajar", "zero-day-measure-seven"}
METHODS = {"temporal-off", "temporal-on", "cgns", "pdf"}
SEEDS = [0, 100000, 200000, 300000]

def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def child(root, relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Expected a contained relative path: " + str(relative))
    resolved = (root / path).resolve(strict=True)
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Path escapes archive: " + str(relative))
    return resolved

def require(condition, message):
    if not condition:
        raise ValueError(message)

def verify(archive=DEFAULT):
    archive = Path(archive).resolve()
    manifest = read(archive / "manifest.json")
    require(manifest["kind"] == "falcor_pt_stage_archive", "Not a stage archive")
    require(set(manifest["views"]) == VIEWS, "Unexpected views")
    require(manifest["quality_seed_offsets"] == SEEDS, "Unexpected seed coverage")
    indexed = {}
    for record in manifest["files"]:
        name = record["path"]
        require(name not in indexed, "Duplicate file: " + name)
        path = child(archive, name)
        require(path.stat().st_size == record["bytes"] and sha(path) == record["sha256"], "File changed: " + name)
        indexed[name] = record
    permitted = {"manifest.json", "provenance/verification.json"}
    actual = {p.relative_to(archive).as_posix() for p in archive.rglob("*") if p.is_file()}
    extras = actual - set(indexed) - permitted
    # Before cleanup, explicitly listed source roots may still exist. Never silently accept new files.
    cleanup = read(archive / "provenance/cleanup-inventory.json")
    historical = {str(Path(r["path"]).relative_to("runs/pt-6-views-spatial-compare")).replace("\\", "/")
                  for r in cleanup["files"] if r["path"].startswith("runs/pt-6-views-spatial-compare/")}
    receipt_path = archive / "provenance/cleanup-receipt.json"
    if receipt_path.exists():
        receipt = read(receipt_path)
        require(receipt["status"] == "completed", "Cleanup incomplete")
        require(receipt["inventory_sha256"] == sha(archive / "provenance/cleanup-inventory.json"), "Cleanup inventory changed")
        require(set(receipt["removed"]) == set(cleanup["targets"]), "Cleanup targets differ")
        for retired in cleanup["targets"]:
            require(not (ROOT / retired).exists(), "Retired directory reappeared: " + retired)
        historical = set()
    require(not extras - historical, "Unindexed files: " + str(sorted(extras - historical)[:5]))
    captures = images = included = 0
    method_names = {"temporal-off": "baseline", "temporal-on": "baseline", "cgns": "cgns", "pdf": "pdf-similarity"}
    for view, entry in manifest["views"].items():
        view_record = read(child(archive, entry["view_config"]))
        ref = read(child(archive, entry["reference"]))
        final = ref["final"]
        require(sha(child(ROOT, final["path"])) == final["sha256"], "Final reference changed: " + view)
        prior = ref["previous_8192"]
        require(sha(child(archive, prior["path"])) == prior["sha256"], "8192 reference changed: " + view)
        require((final["scene_id"], final["view_id"]) == (view_record["scene_id"], view_record["view_id"]), "Reference view mismatch")
        require(set(entry["methods"]) == METHODS, "Unexpected methods")
        for label, method in entry["methods"].items():
            require([q["seed_offset"] for q in method["quality"]] == SEEDS, "Wrong seed set")
            first = None
            for q in method["quality"]:
                directory = child(archive, q["directory"])
                meta = read(directory / "manifest.json")
                require(meta["status"] == "completed" and meta["resolution"] == [1920, 1080], "Invalid capture")
                require(meta["requested_method"] == method_names[label], "Method mismatch")
                require(meta["temporal_reuse"] == (label != "temporal-off"), "Temporal mismatch")
                require(meta.get("seed_offset", 0) == q["seed_offset"], "Seed mismatch")
                require(meta["warmup_frames"] == 40, "Warmup mismatch")
                require([a["frame"] for a in meta["artifacts"]] == list(range(41, 57)), "Missing quality frames")
                require(len(list(directory.glob("*.exr"))) == 16, "Unexpected image count")
                for artifact in meta["artifacts"]:
                    require(artifact["seed"] == q["seed_offset"] + artifact["frame"] - 1, "Path seed mismatch")
                    image = child(directory, artifact["hdr"])
                    key = image.relative_to(archive).as_posix()
                    require(indexed[key]["sha256"] == artifact["sha256"], "Original image hash mismatch")
                    images += 1
                captures += 1
                if first is None:
                    first = meta
            timing = method["timing"]
            require(timing["included"] == (view != "emerald-square"), "Timing inclusion mismatch")
            require(timing["seed_offset"] == 0, "Timing seed mismatch")
            source = timing["source_run_id"]
            require(("timing-recheck-20261116-085341" in source) == (view == "veach-ajar"), "Timing source mismatch")
            directory = child(archive, timing["directory"])
            meta = read(directory / "manifest.json")
            for key in ["requested_method", "temporal_reuse", "requested_graph_options", "runtime_verification", "scene_config_sha256", "resolution"]:
                require(meta[key] == first[key], "Quality/timing identity differs: " + key)
            require(meta["warmup_frames"] == 40 and meta["save_hdr"] is False and meta["drain_last_frame"] is True, "Timing schedule mismatch")
            val = read(directory / "timing-validation.json")
            require(val["measured_gpu_frames"] == list(range(41, 105)), "Invalid timing frames")
            require(sha(directory / "timings.json") == val["sha256"], "Timing hash mismatch")
            rows = read(directory / "timings.json")
            measured = [r["gpu_measured_frame"] for r in rows if r.get("gpu_measured_frame") in range(41, 105)]
            require(measured == list(range(41, 105)), "Missing/duplicate GPU timestamps")
            included += int(timing["included"])
    require(images == 1536 and captures == 96 and included == 20, "Incomplete stage")
    return {"status": "verified", "quality_captures": captures, "quality_exrs": images,
            "final_references": 6, "reference_checkpoints": 6, "timing_captures": 24,
            "included_timing_captures": included, "hashed_archive_files": len(indexed),
            "renderer_launched": False}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT)
    parser.add_argument("--inspect", action="store_true",
                        help="List current quality/timing selections; does not hash/decode HDR or run the full verifier")
    args = parser.parse_args()
    if args.inspect:
        import sys
        sys.path.insert(0, str(ROOT / "src"))
        from backends.falcor.archive import read_archive
        archive = read_archive(args.root)
        quality = archive.quality_records()
        timing = archive.timing_records()
        result = {"kind": "falcor_pt_stage_archive_inspection",
                  "quality_captures": len(quality), "timing_captures": len(timing),
                  "included_timing_captures": sum(t["included"] for t in timing),
                  "quality_images_decoded": False, "renderer_launched": False,
                  "integrity_scope": "Selected metadata only; omit --inspect for complete archive verification",
                  "quality": [{k: q[k] for k in ("view", "method", "seed_offset", "directory", "source_run_id")}
                              for q in quality], "timing": timing}
        print(json.dumps(result, indent=2, default=str))
    else:
        print(json.dumps(verify(args.root), indent=2))

if __name__ == "__main__":
    main()
