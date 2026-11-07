"""Explicit schema 1/2 comparison readers. Never render or modify old records."""
import copy
import json
import math
from pathlib import Path, PureWindowsPath
import re
from rtxdi_common import ROOT, sha
from .config import MODES, MODE_VALUES, make_config
from .fixed_reference import validate_policy, read_json
from .saved_runs import load_run
from .reference import validate_lighting
from .comparison_config import METHOD_KEYS
from scripts.analysis.di_reuse import read_timings


def adapt_spec(spec):
    """Convert documented schema 1/2 fields; missing fields are errors, not defaults."""
    version = spec.get("schema_version")
    if version == 1:
        validate_di_spec(spec)
        groups = {"DI": {"original":spec["baseline"], "cgns":spec["comparison"], "reference":"direct"}}
        if set(spec["methods"]) != {spec["baseline"], spec["comparison"]}:
            raise ValueError("Historical comparison adapter requires the recorded original/CGNS pair")
        references = {"direct":{"policy":spec.get("reference_budget") or {"kind":"paired_precision", "schema_version":1}, "source":{"kind":"indices",
            "indices":{v:row["reference_index"] for v,row in spec["views"].items()}}}}
        methods = {k:{**copy.deepcopy(v), "algorithm":"DI", "source":{"kind":"render"}}
                   for k,v in spec["methods"].items()}
    elif version == 2:
        from .path_reference import policy
        expected_groups = {a:{"original":a.lower()+"-original", "cgns":a.lower()+"-cgns",
                              "reference":"direct" if a == "DI" else "full"} for a in ("DI","GI","PT")}
        if spec["groups"] != expected_groups or spec["references"] != {c:policy(c) for c in ("direct","full")}:
            raise ValueError("Unsupported historical six-method target/policy schema")
        groups = copy.deepcopy(spec["groups"])
        methods = {}
        for key, row in spec["methods"].items():
            algorithm, enabled = row["algorithm"], row["cgns"]
            source = ({"kind":"comparison", "index":spec["reused_di"], "method":"cgns" if enabled else "baseline"}
                      if algorithm == "DI" else {"kind":"render"})
            methods[key] = {"label":row["label"], "algorithm":algorithm,
                "settings":{"cgns":enabled, "cgns_candidates":32, "cgns_early_stopping":True}, "source":source}
        references = {c:{"policy":p, "source":{"kind":"render"}} for c,p in spec["references"].items()}
    else:
        raise ValueError("Unsupported historical comparison schema; expected 1 or 2")
    result = {k:copy.deepcopy(spec[k]) for k in ("definition_file", "resolution", "seeds", "preview_seed", "classification", "views")}
    result.update(schema_version=3, reuse_mode=spec["mode"], groups=groups, methods=methods,
                  references=references, acquisition={"protocol":"static", "warmup_frames":spec["warmup_frames"],
                      "capture_frames":[spec["warmup_frames"]+1]},
                  display={"delta_range_pp":spec["delta_range_pp"],
                           "exposure_ev":{v:0 for v in spec["views"]}})
    from .comparison_config import validate_spec
    validate_spec(result)
    return result

def validate_di_spec(spec):
    if spec.get("schema_version") != 1 or spec.get("mode") not in MODES:
        raise ValueError("Unsupported comparison schema/mode")
    seeds = spec.get("seeds")
    if (not isinstance(seeds, list) or not seeds or
            any(type(s) is not int or not 0 <= s <= 4095 for s in seeds) or len(set(seeds)) != len(seeds)):
        raise ValueError("seeds must be unique integers in 0..4095")
    if type(spec.get("preview_seed")) is not int or spec["preview_seed"] not in seeds:
        raise ValueError("preview_seed must be selected before rendering")
    if type(spec.get("warmup_frames")) is not int or not 0 <= spec["warmup_frames"] < 1048576:
        raise ValueError("warmup_frames must be a nonnegative integer below 1048576")
    for key in ("views", "methods"):
        values = spec.get(key)
        if not isinstance(values, dict) or not values:
            raise ValueError(f"{key} must be a nonempty mapping")
        for name, item in values.items():
            if (not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name) or PureWindowsPath(name).is_reserved() or
                    not isinstance(item, dict) or not isinstance(item.get("label"), str)):
                raise ValueError(f"Invalid {key} name/label")
            if key == "methods" and (not isinstance(item.get("settings"), dict)
                                      or set(item["settings"]) != METHOD_KEYS):
                raise ValueError("Methods must explicitly set CGNS enabled, candidates and early stopping only")
    if (spec.get("baseline") not in spec["methods"] or spec.get("comparison") not in spec["methods"]
            or spec["baseline"] == spec["comparison"]):
        raise ValueError("Select two distinct configured methods")
    classification = spec.get("classification", {})
    radius, percent = classification.get("radius"), classification.get("hard_percent")
    if type(radius) is not int or radius < 0:
        raise ValueError("Classification radius must be a nonnegative integer")
    if type(percent) not in (int, float) or not math.isfinite(percent) or not 0 <= percent <= 100:
        raise ValueError("hard_percent must be in 0..100")
    regions = classification.get("regions")
    if (not isinstance(regions, list) or "all" not in regions or len(set(regions)) != len(regions)
            or not set(regions) <= {"all", "hard", "easy"}):
        raise ValueError("Regions must include all, optionally hard/easy")
    scale = spec.get("delta_range_pp")
    if type(scale) not in (float, int) or not math.isfinite(scale) or not .1 <= scale <= 100:
        raise ValueError("delta_range_pp must be in 0.1..100")
    if spec.get("reference_budget") is not None:
        validate_policy(spec["reference_budget"])
    for view in spec["views"].values():
        if not isinstance(view.get("camera_status"), str) or not view["camera_status"]:
            raise ValueError("Each view requires an explicit camera verification status")


def validate_reference_inputs(inputs):
    for entry in inputs.values():
        if sha(Path(entry["path"])) != entry["sha256"]:
            raise ValueError("Frozen reference index changed")


def validate_frozen_references(record, overrides=None):
    if "reference_inputs" not in record:
        return
    inputs = record["reference_inputs"]
    if set(inputs) != set(record["spec"]["views"]):
        raise ValueError("Frozen reference coverage differs from the comparison")
    validate_reference_inputs(inputs)
    for view, entry in inputs.items():
        expected = Path(entry["path"]).resolve()
        configured = record["spec"]["views"][view].get("reference_index")
        override = (overrides or {}).get(view)
        if (not configured or (ROOT/configured).resolve() != expected
                or (override is not None and (ROOT/override).resolve() != expected)):
            raise ValueError("Cannot substitute a frozen reference index")


def load_di_inputs(source, record):
    spec = record["spec"]
    validate_di_spec(spec)
    if record.get("schema_version") != 1 or record.get("status") != "completed":
        raise ValueError("Require a completed comparison manifest")
    validate_frozen_references(record)
    expected = {(v,m,s) for v in spec["views"] for m in spec["methods"] for s in spec["seeds"]}
    loaded, paths, identities = {}, set(), set()
    frame = spec["warmup_frames"]+1
    for entry in record["runs"]:
        if type(entry.get("seed")) is not int:
            raise ValueError("Saved run seed must be an integer")
        key = (entry["view"],entry["method"],entry["seed"])
        if key not in expected or key in loaded:
            raise ValueError("Duplicate/unexpected view, method or seed")
        directory = (source.parent/entry["path"]).resolve()
        if directory in paths or sha(directory/"manifest.json") != entry["manifest_sha256"]:
            raise ValueError("Duplicate run path or modified manifest")
        paths.add(directory)
        item = load_run(directory,[frame])
        config, manifest = item["config"], item["manifest"]
        view, method, seed = key
        if (config["seed"] != seed or config["scene_id"] != spec["views"][view]["scene"] or
                config["scenario"] != "static" or config["mode"] != spec["mode"] or
                [config["width"],config["height"]] != spec["resolution"]):
            raise ValueError("Saved run differs from requested view/seed/mode/resolution")
        if config["definition"].get("pdf_similarity",False):
            raise ValueError("Static comparison requires PDF similarity off")
        for name, value in spec["methods"][method]["settings"].items():
            if type(config["definition"].get(name)) is not type(value) or config["definition"].get(name) != value:
                raise ValueError(f"Saved method settings differ: {name}")
        schedule = config["frames"]
        if (len(schedule) != frame or [f["frame"] for f in schedule] != list(range(1,frame+1))
                or [f["frame"] for f in schedule if f["capture"]] != [frame]
                or [f["frame"] for f in schedule if f["reset"]] != [1]
                or any(f["sampling_frame"] != seed*1048576+f["frame"]-1 for f in schedule)):
            raise ValueError("Wrong capture frame, reset, warm-up or RNG schedule")
        reconstructed = make_config(config["scene"],config["definition"],config["mode"],"static",
                                    seed=seed,diagnostics=config["diagnostics"],
                                    headless=bool(config["arguments"]["device.headless"]))
        if any(reconstructed[name] != config[name] for name in ("frames","arguments")):
            raise ValueError("Saved control/configuration is inconsistent")
        if "camera" in spec["views"][view] and config["scene"]["camera"] != spec["views"][view]["camera"]:
            raise ValueError("Saved camera differs from the preselected view")
        build = manifest["build"]
        if build.get("cgns") is not True or build != record["build"]:
            raise ValueError("Methods must use the same CGNS executable/build")
        identities.add(build["executable_sha256"])
        resolved = read_json(directory/"resolved.json")
        if (resolved.get("cgns") != config["definition"]["cgns"] or resolved.get("pdf_similarity",False)
                or any(resolved.get(k) != config["definition"][k] for k in METHOD_KEYS-{"cgns"})):
            raise ValueError("Resolved renderer method differs from saved configuration")
        if (resolved.get("estimator") != "restir_di"
                or resolved.get("source_format") != "RGBA16_FLOAT; export decoded losslessly to float32 PFM"
                or not resolved.get("display_passes","").startswith("bypassed;")
                or any(resolved.get(k) != 0 for k in ("aa","denoiser","checkerboard","pixel_jitter"))
                or resolved.get("mode") != MODE_VALUES[config["mode"]]
                or resolved.get("width") != config["width"] or resolved.get("height") != config["height"]):
            raise ValueError("Resolved capture is not the expected unprocessed linear HDR output")
        item["resolved"] = resolved
        item["timings"] = read_timings(directory,config)[0]
        for f in config["frames"]:
            timing = item["timings"][f["frame"]]
            for column, key_name in (("sampling_frame","sampling_frame"),("capture","capture"),("history_reset","reset")):
                if column in timing and int(timing[column]) != int(f[key_name]):
                    raise ValueError("Timing frame labels disagree with the capture/reset schedule")
        loaded[key] = item
    if set(loaded) != expected or len(identities) != 1:
        raise ValueError("Missing method/seed coverage or executable mismatch")
    for view in spec["views"]:
        group = [item for (v,m,s),item in loaded.items() if v==view]
        targets = {item["captures"][frame]["key"] for item in group}
        if len(targets) != 1:
            raise ValueError("Methods/seeds have different reference targets")
        common = None
        for item in group:
            config = item["config"]
            current = {"definition":{k:v for k,v in config["definition"].items()
                                     if k not in METHOD_KEYS|{"seed","geometry_export"}},
                       "arguments":config["arguments"], "preview":config["preview"]}
            if common is not None and common != current:
                raise ValueError("Methods/seeds have different common rendering settings")
            common = current
    validate_lighting([i["captures"][frame] for i in loaded.values()], record["build"])
    return loaded


