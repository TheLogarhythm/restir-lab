"""Comparison configuration and explicit acquisition protocols (schema 3).

Algorithms, reuse modes, acquisition protocols and report display are independent
dimensions. Historical schema conversion belongs to legacy_comparison.
"""
import copy
import json
import math
from pathlib import Path, PureWindowsPath
import re

from rtxdi_common import ROOT
from .config import load_definition, make_config, MODES
from .scenes import load_scene
from .transport import method_config
from . import path_reference, fixed_reference

DEFAULT_SPEC = ROOT / "experiments/configs/cgns-di-gi-pt-static.json"
DI_SPEC = ROOT / "experiments/configs/di-comparison-static.json"
METHOD_KEYS = {"cgns", "cgns_candidates", "cgns_early_stopping"}
ALGORITHMS = {"DI": "direct", "GI": "full", "PT": "full"}


def load_spec(path=DEFAULT_SPEC):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    validate_spec(value)
    return value


def _names(values, kind):
    if not isinstance(values, dict) or not values:
        raise ValueError(f"{kind} must be a nonempty mapping")
    for name, item in values.items():
        if (not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name)
                or PureWindowsPath(name).is_reserved() or not isinstance(item, dict)
                or not isinstance(item.get("label"), str)):
            raise ValueError(f"Invalid {kind} name/label")


def validate_display(display, views):
    if not isinstance(display, dict) or set(display) != {"delta_range_pp", "exposure_ev"}:
        raise ValueError("Display requires delta_range_pp and explicit per-view exposure_ev")
    scale = display["delta_range_pp"]
    if type(scale) not in (int, float) or not math.isfinite(scale) or not .1 <= scale <= 100:
        raise ValueError("delta_range_pp must be in 0.1..100")
    ev = display["exposure_ev"]
    if not isinstance(ev, dict) or set(ev) != set(views):
        raise ValueError("Exposure coverage must match views")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in ev.values()):
        raise ValueError("Display exposure must be finite EV")


def validate_spec(spec):
    if spec.get("schema_version") != 3 or spec.get("reuse_mode") not in MODES:
        raise ValueError("Require comparison schema 3 and a supported reuse_mode")
    acquisition = spec.get("acquisition", {})
    if acquisition.get("protocol") != "static":
        raise ValueError("Sequence acquisition is not implemented; no static fallback")
    warmup = acquisition.get("warmup_frames")
    if type(warmup) is not int or not 0 <= warmup < 1048576:
        raise ValueError("Invalid static warmup_frames")
    if acquisition.get("capture_frames") != [warmup + 1] or any(type(f) is not int for f in acquisition["capture_frames"]):
        raise ValueError("Static acquisition captures exactly warmup_frames + 1")
    seeds = spec.get("seeds")
    if (not isinstance(seeds, list) or not seeds or len(set(seeds)) != len(seeds)
            or any(type(s) is not int or not 0 <= s <= 4095 for s in seeds)):
        raise ValueError("seeds must be unique integers in 0..4095")
    if type(spec.get("preview_seed")) is not int or spec["preview_seed"] not in seeds:
        raise ValueError("preview_seed must be one of the independent seeds")
    resolution = spec.get("resolution")
    if not isinstance(resolution, list) or len(resolution) != 2 or any(type(n) is not int or n < 1 for n in resolution):
        raise ValueError("resolution must contain positive integer width and height")
    for kind in ("views", "methods"):
        _names(spec.get(kind), kind)
    for view in spec["views"].values():
        if not isinstance(view.get("camera_status"), str) or not view["camera_status"]:
            raise ValueError("Each view requires an explicit camera verification status")
    groups = spec.get("groups")
    if not isinstance(groups, dict) or not groups or not set(groups) <= set(ALGORITHMS):
        raise ValueError("Select one or more DI/GI/PT algorithm groups")
    used = []
    for algorithm, group in groups.items():
        if set(group) != {"original", "cgns", "reference"} or group["reference"] != ALGORITHMS[algorithm]:
            raise ValueError("Algorithm/reference target pairing differs")
        pair = []
        for enabled, role in ((False, "original"), (True, "cgns")):
            name = group[role]
            if name not in spec["methods"] or name in used:
                raise ValueError("Group methods must be distinct configured methods")
            item = spec["methods"][name]
            settings = item.get("settings", {})
            if (item.get("algorithm") != algorithm or set(settings) != METHOD_KEYS
                    or settings.get("cgns") is not enabled
                    or type(settings.get("cgns_candidates")) is not int
                    or not 1 <= settings["cgns_candidates"] <= 32
                    or type(settings.get("cgns_early_stopping")) is not bool):
                raise ValueError("Method algorithm/CGNS settings differ from its group")
            source = item.get("source", {})
            if source != {"kind": "render"} and not (
                    set(source) == {"kind", "index", "method"} and source["kind"] == "comparison"
                    and all(isinstance(source[k], str) and source[k] for k in ("index", "method"))):
                raise ValueError("Explicit render or comparison-index method source required")
            used.append(name)
            pair.append({k:v for k,v in settings.items() if k != "cgns"})
        if pair[0] != pair[1]:
            raise ValueError("Original/CGNS candidate and early-stopping controls must match")
    if set(used) != set(spec["methods"]):
        raise ValueError("Methods not assigned to an algorithm group")
    components = {g["reference"] for g in groups.values()}
    if set(spec.get("references", {})) != components:
        raise ValueError("Reference coverage differs from selected groups")
    for component, reference in spec["references"].items():
        policy = reference.get("policy", {})
        if policy.get("kind") == "fixed_path_spp":
            if path_reference.validate_policy(policy)["component"] != component:
                raise ValueError("Path reference component differs")
        elif component == "direct" and policy.get("kind") == "fixed_budget":
            fixed_reference.validate_policy(policy)
        elif component == "direct" and policy == {"kind":"paired_precision", "schema_version":1}:
            if reference.get("source", {}).get("kind") != "indices":
                raise ValueError("Historical paired references are read-only indices")
        else:
            raise ValueError("Unsupported reference policy/target")
        source = reference.get("source", {})
        if source != {"kind": "render"} and not (set(source) == {"kind", "indices"}
                and source["kind"] == "indices" and set(source["indices"]) == set(spec["views"])
                and all(isinstance(v, str) and v for v in source["indices"].values())):
            raise ValueError("Reference source must be render or explicit per-view indices")
        if policy.get("seed") in seeds:
            raise ValueError("Reference seed must be independent of method seeds")
    classification = spec.get("classification", {})
    radius, percent = classification.get("radius"), classification.get("hard_percent")
    regions = classification.get("regions")
    if type(radius) is not int or radius < 0:
        raise ValueError("Classification radius must be a nonnegative integer")
    if type(percent) not in (int, float) or not math.isfinite(percent) or not 0 <= percent <= 100:
        raise ValueError("hard_percent must be in 0..100")
    if (not isinstance(regions, list) or "all" not in regions or len(set(regions)) != len(regions)
            or not set(regions) <= {"all", "hard", "easy"}):
        raise ValueError("Regions must include all, optionally hard/easy")
    validate_display(spec.get("display"), spec["views"])


def resolve_configs(spec):
    """Resolve static acquisition directly, without a legacy DI intermediate spec."""
    validate_spec(spec)
    count = spec["acquisition"]["warmup_frames"] + 1
    base = load_definition(ROOT / spec["definition_file"])
    base.update(frames=count, resolution=spec["resolution"], pdf_similarity=False,
                pdf_history_mode=0, geometry_export=True, reset_frame=min(2, count),
                motion={"start_frame":1, "end_frame":count},
                captures={name:[count] for name in ("static", "motion", "reset")})
    jobs = []
    for view_id, view in spec["views"].items():
        scene = load_scene(view["scene"])
        if "camera" in view:
            scene["camera"] = copy.deepcopy(view["camera"])
        for name, item in spec["methods"].items():
            for seed in spec["seeds"]:
                # Run the native configuration validator with selection enabled
                # before the indirect adapter disables DI's own selection pass.
                definition = {**base, **item["settings"]}
                config = make_config(scene, definition, spec["reuse_mode"], "static", seed=seed, diagnostics=True)
                config = method_config(config, item["algorithm"], item["settings"]["cgns"])
                jobs.append({"view":view_id, "method":name, "seed":seed, "algorithm":item["algorithm"],
                             "component":ALGORITHMS[item["algorithm"]], "config":config})
    return jobs


def validate_approved_budget(spec):
    """Formal rendering gate, separate from general comparison configuration."""
    expected = load_spec()
    validate_spec(spec)
    for key in ("resolution", "seeds", "preview_seed", "acquisition", "reuse_mode", "classification"):
        if spec[key] != expected[key]:
            raise ValueError(f"Unapproved formal experiment setting: {key}")
    if set(spec["views"]) != set(expected["views"]):
        raise ValueError("Formal budget requires the five approved fixed views")
    canonical_jobs = resolve_configs(expected)
    for job in resolve_configs(spec):
        d = job["config"]["definition"]
        enabled = spec["methods"][job["method"]]["settings"]["cgns"]
        canonical = next(j for j in canonical_jobs if j["view"] == job["view"]
                         and j["algorithm"] == job["algorithm"]
                         and expected["methods"][j["method"]]["settings"]["cgns"] == enabled)
        # Compare the resolved rendering controls, excluding only report/reuse metadata.
        if job["config"] != canonical["config"]:
            raise ValueError("Formal scene/camera/sampling controls differ from approved configuration")
    for component, reference in spec["references"].items():
        if reference["policy"] != expected["references"][component]["policy"]:
            raise ValueError("Unapproved formal reference budget")
