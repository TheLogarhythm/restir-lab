"""Collect or read comparison runs through one algorithm-aware backend boundary."""
from pathlib import Path
import numpy as np

from rtxdi_common import ROOT, RENDERER, sha
from .artifacts import save_json, validate_runtime_outputs, cgns_stats, spatial_neighbor_stats
from .comparison_config import resolve_configs, validate_spec
from .fixed_reference import read_json
from .geometry_io import read_geometry
from .images import read_pfm
from .runner import relative_path, run_one, frozen_input_guard
from . import reference, transport

EXECUTABLES = {"DI":RENDERER / "build/bin/FullSampleCgns.exe",
               "GI":RENDERER / "build/bin/FullSampleTransport.exe",
               "PT":RENDERER / "build/bin/FullSampleTransport.exe"}


def run_inventory(directory):
    """Pin durable files before parsing them; do not traverse mounted asset directories."""
    return {str(p.resolve()):sha(p) for p in Path(directory).iterdir() if p.is_file()}


def validate_inventory(inventory):
    for name, digest in inventory.items():
        if sha(Path(name)) != digest:
            raise ValueError(f"Validated input changed during processing: {name}")


def merge_inventory(inventory, additions):
    """First observation owns the digest, including inputs shared across runs/views."""
    for name, digest in additions.items():
        if name in inventory and inventory[name] != digest:
            raise ValueError(f"Validated input changed between observations: {name}")
        inventory[name] = digest


def validate_reference_sources(spec, jobs, assets, expected_build=None):
    """Check reused reference ancestry before any rendering, without a reference executable."""
    from . import path_reference, fixed_reference
    build, inputs = expected_build, {}
    for component, settings in spec["references"].items():
        if settings["source"]["kind"] != "indices":
            continue
        for view, name in settings["source"]["indices"].items():
            index_path = (ROOT / name).resolve()
            digest = sha(index_path)
            index = read_json(index_path)
            if build is None:
                build = index["build"]
            if index["build"] != build:
                raise ValueError("Reused reference builds differ")
            job = next(j for j in jobs if j["view"] == view and j["component"] == component)
            base = job["config"]
            frame = base["frames"][-1]
            asset = assets[base["scene_id"]]
            if settings["policy"]["kind"] == "fixed_budget":
                value = reference.target(base,frame,asset["sha256"])
                sample = {"config":base, "frame":frame, "target":value, "key":reference.target_key(value),
                          "manifest":{"build":build}}
                fixed_reference.load_references(index_path,[sample],expected_policy=settings["policy"],expected_build=build)
            elif settings["policy"]["kind"] == "fixed_path_spp":
                if index.get("schema_version") == 2 and index.get("kind") == "grouped_path_references":
                    key = view + "/" + component
                elif index.get("schema_version") == 3 and index.get("kind") == "comparison_references":
                    key = f"{view}/frame-{frame['frame']}/{component}"
                else:
                    raise ValueError("Unsupported reused reference index schema")
                row = index["references"][key]
                if row["policy"] != settings["policy"]:
                    raise ValueError("Reused reference budget differs")
                path_reference.load_reference(index_path.parent,row,base,component,build,asset)
            else:
                raise ValueError("Paired precision references are historical analysis inputs only")
            if sha(index_path) != digest:
                raise ValueError("Reference index changed during validation")
            inputs[f"reference/{view}/{component}"] = {"path":str(index_path), "sha256":digest}
    return build, inputs


def observed_run(directory, job, build, assets):
    """Validate durable outputs and exact resolved controls, without regenerating raw buffers."""
    directory = Path(directory).resolve()
    inventory = run_inventory(directory)
    config, manifest = read_json(directory / "config.json"), read_json(directory / "manifest.json")
    expected = dict(job["config"], output=".", repository_root=relative_path(ROOT, directory))
    if (config != expected or manifest.get("status") != "completed" or manifest.get("build") != build
            or manifest.get("scene") != assets or manifest.get("config_sha256") != sha(directory / "config.json")):
        raise ValueError("Saved method inputs differ from the frozen job")
    resolved, timings = validate_runtime_outputs(directory, config)
    if resolved.get("source_format") != "RGBA16_FLOAT; export decoded losslessly to float32 PFM":
        raise ValueError("Method HDR reconstruction differs")
    frame = config["frames"][-1]["frame"]
    captures = manifest.get("captures", [])
    if len(captures) != 1 or captures[0].get("frame") != frame:
        raise ValueError("Wrong static method capture coverage")
    record = captures[0]
    if job["algorithm"] != "DI":
        invalid = directory / f"frame-{frame:04d}.transport-invalid"
        if (resolved.get("cgns") is not False or record.get("transport_invalid_contributions") != 0
                or invalid.stat().st_size != 4 or sha(invalid) != record.get("transport_invalid_sha256")
                or np.fromfile(invalid, dtype="<u4")[0] != 0):
            raise ValueError("Indirect numerical diagnostics are missing or nonzero")
    image = directory / f"frame-{frame:04d}.pfm.gz"
    if sha(image) != record["image_sha256"] or sha(directory / record["geometry"]) != record["geometry_sha256"]:
        raise ValueError("Method image or geometry hash changed")
    rgb, geometry = read_pfm(image), read_geometry(directory / record["geometry"])
    if rgb.shape != (config["height"], config["width"], 3) or not np.isfinite(rgb).all() or geometry["valid"].shape != rgb.shape[:2]:
        raise ValueError("Invalid method HDR/geometry")
    if config["mode"] in ("spatial", "combined"):
        count = spatial_neighbor_stats(directory / record["spatial_neighbors"], config["width"], config["height"],
                                       config["definition"]["spatial_neighbors"])
        if any(record.get(k) != v for k,v in count.items()):
            raise ValueError("Method merged-neighbor counts differ")
        enabled = config.get("transport_method", {}).get("cgns", config["definition"]["cgns"])
        if enabled:
            count = cgns_stats(directory / f"frame-{frame:04d}.cgns", config["width"], config["height"],
                               config["definition"]["cgns_candidates"], config["definition"]["spatial_neighbors"])
            if any(record.get(k) != v for k,v in count.items()):
                raise ValueError("Method CGNS counts differ")
    value = transport.target(config, config["frames"][-1], assets["sha256"], job["component"])
    # Geometry and old DI reference validators retain their original target schema.
    legacy_target = reference.target(config, config["frames"][-1], assets["sha256"])
    capture = {"directory":directory, "config":config, "manifest":manifest, "frame":config["frames"][-1],
               "image":image, "target":legacy_target, "key":reference.target_key(legacy_target)}
    if isinstance(timings, list):
        timings = {int(row["frame"]):row for row in timings}
    validate_inventory(inventory)
    return {"directory":directory, "config":config, "manifest":manifest, "record":record, "input_hashes":inventory,
            "records":{frame:record}, "captures":{frame:capture}, "image":image,
            "resolved":resolved, "timings":timings, "target":value, "key":transport.target_key(value)}


def reused_runs(spec, jobs, assets):
    """Resolve explicit saved comparisons, preserving seed identity and pair build provenance."""
    loaded, origins, cache = {}, {}, {}
    for job in jobs:
        source = spec["methods"][job["method"]]["source"]
        if source["kind"] == "render":
            continue
        path = (ROOT / source["index"]).resolve()
        if path not in cache:
            old_spec, old, builds = load_methods(path)
            cache[path] = old_spec, old, builds
            origins[str(path)] = {"path":str(path), "sha256":sha(path)}
        old_spec, old, builds = cache[path]
        key = job["view"], source["method"], job["seed"]
        if old_spec["methods"][source["method"]]["algorithm"] != job["algorithm"]:
            raise ValueError("Reused method algorithm differs")
        old_item = old[key]
        item = observed_run(old_item["directory"], job, builds[job["algorithm"]], assets[job["config"]["scene_id"]])
        loaded[(job["view"],job["method"],job["seed"])] = item
    return loaded, origins


def load_methods(source, *, _seen=None):
    """Read schema 1/2/3 indices, enforcing declared coverage and source identities."""
    source = Path(source).resolve()
    seen = set() if _seen is None else set(_seen)
    if source in seen:
        raise ValueError("Cyclic comparison reuse")
    seen.add(source)
    source_hash = sha(source)
    record = read_json(source)
    if record.get("status") != "completed":
        raise ValueError("Require a completed comparison index")
    version = record.get("schema_version")
    if version == 1:
        from .legacy_comparison import adapt_spec, load_di_inputs
        spec = adapt_spec(record["spec"])
        inventories = {str((source.parent / e["path"]).resolve()):run_inventory(source.parent / e["path"])
                       for e in record["runs"]}
        loaded = load_di_inputs(source, record)
        frame = spec["acquisition"]["capture_frames"][0]
        for item in loaded.values():
            capture = item["captures"][frame]
            value = transport.target(item["config"], capture["frame"], item["manifest"]["scene"]["sha256"], "direct")
            item.update(image=capture["image"], record=item["records"][frame], target=value, key=transport.target_key(value))
            item["input_hashes"] = {**inventories[str(item["directory"])],str(source):source_hash}
            validate_inventory(item["input_hashes"])
        return spec, loaded, {"DI":record["build"]}
    if version == 2:
        from .legacy_comparison import adapt_spec
        spec = adapt_spec(record["spec"])
    elif version == 3:
        spec = record["spec"]
        validate_spec(spec)
    else:
        raise ValueError("Unsupported comparison index schema")
    jobs = resolve_configs(spec)
    entries = {(e["view"],e["method"],e["seed"]):e for e in record["runs"]}
    if len(entries) != len(record["runs"]) or set(entries) != {(j["view"],j["method"],j["seed"]) for j in jobs}:
        raise ValueError("Comparison method/seed coverage differs")
    if set(record["builds"]) != set(spec["groups"]):
        raise ValueError("Comparison pair build coverage differs")
    cache, loaded = {}, {}
    for job in jobs:
        key = job["view"],job["method"],job["seed"]
        entry = entries[key]
        directory = (source.parent / entry["path"]).resolve()
        if type(entry["seed"]) is not int or sha(directory / "manifest.json") != entry["manifest_sha256"]:
            raise ValueError("Method record/manifest changed")
        declared = spec["methods"][job["method"]]["source"]
        if entry.get("reused") is not (declared["kind"] == "comparison"):
            raise ValueError("Method reuse marker differs")
        if declared["kind"] == "comparison":
            path = (ROOT / declared["index"]).resolve()
            if path not in cache:
                cache[path] = load_methods(path, _seen=seen)
            origin = cache[path][1][(job["view"],declared["method"],job["seed"])]
            if origin["directory"] != directory or origin["manifest"]["build"] != record["builds"][job["algorithm"]]:
                raise ValueError("Reused method origin/build differs")
            if version == 2 and record["reused_di"] != {"path":str(path), "sha256":sha(path), "build":record["builds"]["DI"]}:
                raise ValueError("Historical DI provenance changed")
        manifest = read_json(directory / "manifest.json")
        item = observed_run(directory, job, record["builds"][job["algorithm"]], manifest["scene"])
        item["input_hashes"][str(source)] = source_hash
        if declared["kind"] == "comparison":
            merge_inventory(item["input_hashes"],origin["input_hashes"])
        if item["target"] != entry["target"] or item["key"] != entry["target_key"]:
            raise ValueError("Method target binding changed")
        loaded[key] = item
    for item in loaded.values(): validate_inventory(item["input_hashes"])
    return spec, loaded, record["builds"]


def collect(spec, root, builds, assets, *, input_guard, progress=None):
    root = Path(root)
    jobs = resolve_configs(spec)
    reference_build, reference_inputs = validate_reference_sources(spec,jobs,assets)
    reused, origins = reused_runs(spec, jobs, assets)
    initial = {"schema_version":3, "spec":spec, "builds":builds, "reuse_sources":origins,
               "reference_build":reference_build, "reference_inputs":reference_inputs}
    record_path = root / "comparison.json"
    if record_path.exists():
        record = read_json(record_path)
        if any(record.get(k) != v for k,v in initial.items()):
            raise ValueError("Frozen comparison inputs changed")
    else:
        root.mkdir(parents=True, exist_ok=False)
        record = dict(initial, status="running", runs=[])
        save_json(record_path, record)
    saved = {(r["view"],r["method"],r["seed"]):r for r in record["runs"]}
    if len(saved) != len(record["runs"]) or not set(saved) <= {(j["view"],j["method"],j["seed"]) for j in jobs}:
        raise ValueError("Duplicate or unexpected comparison method records")
    try:
        for job in jobs:
            input_guard()
            key = job["view"],job["method"],job["seed"]
            asset, build = assets[job["config"]["scene_id"]], builds[job["algorithm"]]
            if progress:
                progress({"view":key[0], "method":key[1], "seed":key[2], "completed_runs":len(saved)})
            if key in reused:
                item = reused[key]
                if item["manifest"]["build"] != build:
                    raise ValueError("Reused method differs from frozen pair build")
                directory = item["directory"]
            else:
                directory = root / key[0] / key[1] / f"seed-{key[2]}"
                if not directory.exists():
                    if key in saved:
                        raise ValueError("Completed method removed; refusing to render again")
                    executable = EXECUTABLES[job["algorithm"]]
                    guard = frozen_input_guard(job["config"], executable, build, asset, input_guard)
                    run_one(job["config"], directory, build, asset, executable=executable, input_guard=guard)
                item = observed_run(directory, job, build, asset)
            entry = {"view":key[0], "method":key[1], "seed":key[2], "path":relative_path(directory,root),
                     "manifest_sha256":sha(directory / "manifest.json"), "target":item["target"],
                     "target_key":item["key"], "reused":key in reused}
            if key in saved and saved[key] != entry:
                raise ValueError("Completed comparison method record changed")
            saved[key] = entry
            record["runs"] = list(saved.values())
            save_json(record_path, record)
        input_guard()
        record["status"] = "completed"
    except BaseException:
        record["status"] = "incomplete"
        raise
    finally:
        save_json(record_path, record)
    return record
