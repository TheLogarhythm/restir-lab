"""Warm and verify the Slang cache using the normal live render graph."""

import json
from itertools import groupby
import os
from operator import itemgetter
from pathlib import Path
import re
import shutil
import tempfile

from ..process_utils import exclusive_operation
from ..runtime_common import sha256_file
from .controller import Session, write_json
from .evidence import check_capture_image, read_rendered_sequence
from .scenes import SCENE_NAMES


# Switch a single control at a time, and restore CGNS Raw before changing scenes.
WARMUP_STATES = (
    ("CGNS", "Raw"), ("PDF Similarity", "Raw"), ("Original", "Raw"),
    ("Original", "Accumulation"), ("PDF Similarity", "Accumulation"),
    ("PDF Similarity", "NRD"), ("Original", "NRD"), ("CGNS", "NRD"),
    ("CGNS", "Accumulation"), ("CGNS", "Raw"),
)
PACK_EVENT = re.compile(rb"Live Slang cache: (hit|write) [1-9][0-9]* modules ([0-9a-f]{64})(?:\s|$)")
PACK_NAME = re.compile(r"[0-9a-f]{64}\.irpack")


def precompile_steps(scene=None, *, scenes=SCENE_NAMES):
    if scene:
        scenes = (scene,)
    return [
        {"Scene": name, "Method": method, "Display": mode,
         "label": f"{name.lower().replace(' ', '-')}-{index:02d}-{method.lower().replace(' ', '-')}-{mode.lower()}",
         "frames": 2, "verify_image": index in (1, 4, 6)}
        for name in scenes for index, (method, mode) in enumerate(WARMUP_STATES, start=1)
    ]


def cache_directory(runtime):
    override = os.environ.get("RESTIR_LIVE_SLANG_CACHE_DIR")
    if not override:
        return runtime / ".slangcache"
    cache = Path(override)
    if not cache.is_absolute():
        raise ValueError("RESTIR_LIVE_SLANG_CACHE_DIR must be an absolute path")
    return cache


class PrecompileSession(Session):
    def uses_raw_comparison(self, scene):
        return False

    def cache_log_position(self):
        # Falcor flushes each log message, so the file size is a byte boundary.
        try:
            return (self.output / "mogwai.log").stat().st_size
        except FileNotFoundError:
            return 0

    def transition(self, group, label, requested_at=None):
        if group == "Scene" and self.state["Scene"] != label:
            self.scene_cache_log_start = self.cache_log_position()
        super().transition(group, label, requested_at=requested_at)

    def record_step(self, step):
        texture = self.graph.get_output("ToneMapper.dst")
        texture.device.wait()
        end = self.cache_log_position()
        record = self.capture(step["label"], save_image=step["verify_image"])
        return {**record, "scene_cache_log_start": self.scene_cache_log_start, "cache_log_end": end}


def verify_cache(output, records, cache, mode):
    log_path = output / "mogwai.log"
    log = log_path.read_bytes()
    failure = b"Live Slang cache: write failed "
    if failure in log:
        raise ValueError(f"Slang cache write failed in {cache}. See {log_path}.")
    events = PACK_EVENT.findall(log)
    keys = {kind: sorted({key.decode("ascii") for event, key in events if event == kind.encode("ascii")})
            for kind in ("hit", "write")}
    if mode == "read" and keys["write"]:
        raise ValueError(f"Slang cache wrote to a read-only replay. See {log_path}.")

    scene_counts = {}
    previous_end = 0
    for scene, frames in groupby(records, key=itemgetter("Scene")):
        start = None
        for rec in frames:
            if start is None:
                start = rec["scene_cache_log_start"]
                if start < previous_end:
                    raise ValueError(f"Overlapping cache log evidence for {scene}. See {log_path}.")
                previous_end = start
            end = rec["cache_log_end"]
            if rec["scene_cache_log_start"] != start or not previous_end <= end <= len(log):
                raise ValueError(f"Invalid cache log evidence for {scene}. See {log_path}.")
            previous_end = end
        scene_log = log[start:previous_end]
        events = PACK_EVENT.findall(scene_log)
        counts = {"hits": sum(event == b"hit" for event, _ in events),
                  "writes": sum(event == b"write" for event, _ in events),
                  "misses": scene_log.count(b"Live Slang cache: miss ")}
        if not cache.is_dir() or not (counts["hits"] or counts["writes"]):
            evidence = "hits" if mode == "read" else "writes or hits"
            raise ValueError(f"Slang cache has no verified {evidence} for {scene} in {cache}. See {log_path}.")
        scene_counts[scene] = counts

    totals = {key: sum(counts[key] for counts in scene_counts.values()) for key in ("hits", "writes", "misses")}
    return {"directory": str(cache), **totals, "scenes": scene_counts,
            "hit_keys": keys["hit"], "write_keys": keys["write"]}


def verify(output, config, pid, cache, *, mode="write"):
    resolution = [config["width"], config["height"]]
    result = read_rendered_sequence(output, config["sequence"], pid, require_native_display=True,
                                    exact_resolution=resolution)
    records = result["captures"]
    for rec, row in zip(records, config["sequence"]):
        if row["verify_image"]:
            rec.update(check_capture_image(output / rec["file"], resolution, hash_pixels=True))

    counts = verify_cache(output, records, cache, mode)
    report = {
        "status": "passed", "pid": pid, "hwnd": result["hwnd"], "total_frames": result["total_frames"],
        "scenes": list(counts["scenes"]), "resolution": resolution, "cache": counts, "cache_mode": mode,
        "frames": records,
    }
    write_json(output / "precompile.json", report)
    return report


def pack_info(path):
    return {"size": path.stat().st_size, "sha256": sha256_file(path)}


def link_pack(source, target):
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)


def seed_packs(cache, trusted):
    try:
        manifest = json.loads((cache / "qualified.json").read_text(encoding="utf8"))
    except (FileNotFoundError, ValueError):
        return {}
    if not isinstance(manifest, dict) or manifest.get("schema") != 1 or not isinstance(manifest.get("files"), dict):
        return {}
    seeded = {}
    for name, expected in manifest["files"].items():
        if not PACK_NAME.fullmatch(name):
            continue
        pack = cache / name
        if pack.is_symlink() or not pack.is_file() or pack_info(pack) != expected:
            continue
        link_pack(pack, trusted / name)
        seeded[name] = expected
    return seeded


def warm(output, config, cache, run_session):
    output.mkdir(parents=True, exist_ok=False)
    lock = cache.parent / (cache.name + ".precompile.lock")
    with exclusive_operation(lock), tempfile.TemporaryDirectory(dir=cache.parent, prefix=cache.name + "-stage-") as stage:
        candidate, trusted = Path(stage) / "candidate", Path(stage) / "trusted"
        candidate.mkdir()
        trusted.mkdir()
        seeded = seed_packs(cache, trusted)
        environment = {**os.environ, "RESTIR_LIVE_SLANG_CACHE_DIR": str(candidate),
                       "RESTIR_LIVE_SLANG_CACHE_MODE": "write", "RESTIR_LIVE_SLANG_CACHE_TRUSTED_DIR": str(trusted)}
        environment.pop("RESTIR_LIVE_SLANG_CACHE_QUALIFY", None)
        write_output = output / "write"
        write_pid = run_session(write_output, {**config, "slang_cache_directory": str(candidate),
                                              "slang_cache_mode": "write"}, environment)
        collected = verify(write_output, config, write_pid, candidate)
        passes = {"write": "write/precompile.json"}
        written = collected["cache"]["write_keys"]
        published = {}
        unaccepted = []
        if written:
            # Keep the write destination empty so stale trusted packs can be rebuilt.
            # Replay needs both the newly written packs and the untouched trusted ones.
            for name in seeded:
                if not (candidate / name).exists():
                    link_pack(trusted / name, candidate / name)
            print(f"Checking {len(written)} staged shader packs in a fresh Mogwai process.", flush=True)
            environment = {**environment, "RESTIR_LIVE_SLANG_CACHE_MODE": "read",
                           "RESTIR_LIVE_SLANG_CACHE_QUALIFY": "1"}
            del environment["RESTIR_LIVE_SLANG_CACHE_TRUSTED_DIR"]
            read_output = output / "read"
            read_pid = run_session(read_output, {**config, "slang_cache_directory": str(candidate),
                                                "slang_cache_mode": "read"}, environment)
            replayed = verify(read_output, config, read_pid, candidate, mode="read")
            passes["read"] = "read/precompile.json"
            for before, after in zip(collected["frames"], replayed["frames"]):
                if before.get("rgb_sha256") != after.get("rgb_sha256"):
                    raise ValueError(f"Slang cache replay rendered pixels differ for {before['Scene']} ({before['Display']}).")
            accepted = set(replayed["cache"]["hit_keys"])
            unaccepted = sorted(set(written) - accepted)
            # Resolve and hash every candidate before changing any published file.
            for key in sorted(set(written) & accepted):
                name = key + ".irpack"
                info = pack_info(candidate / name)
                if seeded.get(name) != info:
                    published[name] = info
            if published:
                cache.mkdir(parents=True, exist_ok=True)
                for name in published:
                    os.replace(candidate / name, cache / name)
                write_json(cache / "qualified.json", {"schema": 1, "files": {**seeded, **published}})
        if not seeded and not published:
            raise ValueError(f"No Slang cache packs qualified for publication. See {output}.")

        report = {
            "status": "passed", "scenes": collected["scenes"], "resolution": collected["resolution"],
            "runtime": config.get("runtime"), "passes": passes,
            "cache": {**collected["cache"], "directory": str(cache), "published": published,
                      "unaccepted_keys": unaccepted},
        }
        if report["runtime"]:
            receipt = Path(report["runtime"]).parent / "receipt.json"
            if receipt.is_file():
                report["runtime_receipt_sha256"] = sha256_file(receipt)
        write_json(output / "precompile.json", report)
    print(f"Verified {len(collected['frames'])} render states. Slang cache packs published: {len(published)}. "
          f"See {output / 'precompile.json'}.", flush=True)
