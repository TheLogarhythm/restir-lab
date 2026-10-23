"""Predeclared PDF comparison conditions and verified completed-run reuse."""
import copy
import json
import math
from pathlib import Path

from rtxdi_common import ROOT, sha
from .config import load_definition, make_config
from .scenes import load_scene


CAMPAIGN_PATH = ROOT / "experiments/configs/pdf-controlled.json"


def load_campaign(path=CAMPAIGN_PATH):
    """Read the declared campaign; reject ambiguous scheduling before any writes."""
    try:
        campaign = json.loads(Path(path).read_text(encoding="utf-8"))
        if type(campaign["schema_version"]) is not int or campaign["schema_version"] != 1:
            raise ValueError("Unsupported campaign schema")
        ids = [row["id"] for row in campaign["conditions"]]
        execution = campaign["execution"]
        if (not ids or len(set(ids)) != len(ids)
                or len(execution["order"]) != len(ids) or set(execution["order"]) != set(ids)):
            raise ValueError("Campaign condition IDs and execution order must match exactly once")
        for row in campaign["conditions"]:
            if row["view"] not in campaign["views"] or row["scenario"] not in campaign["scenarios"]:
                raise ValueError("Campaign condition refers to an unknown view or scenario")
        if execution["seeds"] != [1, 2, 3] or any(type(seed) is not int for seed in execution["seeds"]):
            raise ValueError("Controlled comparisons require method seeds 1, 2, 3")
        budgets = execution["equal_time_neighbors"]
        primary = execution["primary_neighbors"]
        if (not budgets or any(type(n) is not int or not 1 <= n <= 32 for n in budgets)
                or len(set(budgets)) != len(budgets) or type(primary) is not int or primary not in budgets
                or primary != campaign["definition_overrides"]["spatial_neighbors"]):
            raise ValueError("Invalid primary or equal-time sampling budgets")
        equal = execution["equal_time_conditions"]
        if (execution["spatial_ablation"] not in ids or len(set(equal)) != len(equal)
                or not set(equal) <= set(ids)):
            raise ValueError("Unknown or repeated ablation/equal-time conditions")
        return campaign
    except (KeyError, TypeError) as error:
        raise ValueError(f"Invalid controlled campaign: {path}") from error


def method_run_count(execution):
    groups = (len(execution["order"]) + 1
              + len(execution["equal_time_conditions"]) * (len(execution["equal_time_neighbors"]) - 1))
    return groups * len(execution["seeds"]) * 2


def conditions(campaign=None):
    """Resolve independent conditions from the declared camera and sampling matrix."""
    campaign = load_campaign() if campaign is None else campaign
    scenes = {}
    for name, view in campaign["views"].items():
        scene = load_scene(view["scene"])
        scene["camera"].update(copy.deepcopy(view.get("camera", {})))
        scene["motion"].update(copy.deepcopy(view.get("motion", {})))
        if "motion_yaw_degrees" in view:
            x, y, z = scene["camera"]["direction"]
            angle = math.radians(view["motion_yaw_degrees"])
            scene["motion"].update(end_direction=[math.cos(angle)*x + math.sin(angle)*z,
                                                  y, -math.sin(angle)*x + math.cos(angle)*z],
                                   end_up=copy.deepcopy(scene["camera"]["up"]))
        scenes[name] = scene
    base = load_definition()
    base.update(copy.deepcopy(campaign["definition_overrides"]))
    result = []
    for row in campaign["conditions"]:
        scenario = row["scenario"]
        settings = campaign["scenarios"][scenario]
        definition = copy.deepcopy(base)
        definition["frames"] = settings["frames"]
        captures = list(range(1, settings["frames"] + 1)) if settings["captures"] == "all" else settings["captures"]
        definition["captures"] = {key: list(captures) for key in ("static", "motion", "reset")}
        if "logical_fps" in settings:
            definition["logical_fps"] = settings["logical_fps"]
        if "lighting" in settings:
            definition["lighting"] = copy.deepcopy(settings["lighting"])
            definition["captures"]["lighting"] = list(captures)
        result.append({"id": row["id"], "scene": copy.deepcopy(scenes[row["view"]]),
                       "definition": definition, "scenario": scenario, "rois": copy.deepcopy(campaign["rois"])})
    return result


def build_config(condition, seed, pdf_enabled, mode="combined", neighbors=None):
    """Resolve one method/seed without changing its frozen condition."""
    definition = copy.deepcopy(condition["definition"])
    neighbors = definition["spatial_neighbors"] if neighbors is None else neighbors
    definition.update(pdf_similarity=pdf_enabled, pdf_history_mode=0, spatial_neighbors=neighbors)
    config = make_config(condition["scene"], definition, mode, condition["scenario"], seed,
                         resolution=tuple(definition["resolution"]))
    if config["scenario"] == "motion":
        for frame in config["frames"]:
            if frame["frame"] <= definition["motion"]["start_frame"]:
                for key in ("direction", "up"):
                    frame[key] = copy.deepcopy(config["scene"]["camera"][key])
    return config


def completed_run(directory, expected_config):
    """Reuse only a completed attempt whose config and every HDR capture still agree.

    Missing and unfinished attempts return False so callers can preserve them and
    create a new attempt. A claimed completion with inconsistent evidence raises.
    """
    directory = Path(directory)
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        return False

    def read_json(path, label):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError(f"Invalid or missing completed-run {label}: {path}") from error

    manifest = read_json(manifest_path, "manifest")
    if not isinstance(manifest, dict):
        raise ValueError("Invalid completed-run manifest")
    if manifest.get("status") != "completed":
        return False
    config_path = directory / "config.json"
    saved = read_json(config_path, "config")
    if not isinstance(saved, dict) or sha(config_path) != manifest.get("config_sha256"):
        raise ValueError("Completed-run config hash differs from its manifest")

    def canonical_config(config):
        return json.dumps({key: value for key, value in config.items()
                           if key not in ("output", "repository_root")}, sort_keys=True, allow_nan=False)

    if canonical_config(saved) != canonical_config(expected_config):
        raise ValueError("Completed-run config differs from the requested config")
    captures = manifest.get("captures")
    if not isinstance(captures, list) or captures != read_json(directory / "captures.json", "capture index"):
        raise ValueError("Completed-run capture index differs from its manifest")
    wanted = [frame["frame"] for frame in expected_config["frames"] if frame["capture"]]
    if (any(not isinstance(record, dict) or type(record.get("frame")) is not int for record in captures)
            or [record["frame"] for record in captures] != wanted):
        raise ValueError("Completed-run capture schedule differs from the requested config")
    for record in captures:
        image = directory / f"frame-{record['frame']:04d}.pfm.gz"
        if not image.is_file() or sha(image) != record.get("image_sha256"):
            raise ValueError(f"Completed-run image is missing or modified: {image}")
    return True
