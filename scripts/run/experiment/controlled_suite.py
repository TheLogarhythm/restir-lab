"""Predeclared PDF comparison conditions and verified completed-run reuse."""
import copy
import json
import math
from pathlib import Path

from rtxdi_common import sha
from .config import load_definition, make_config
from .scenes import load_scene


PINK_MATERIAL = "LMBR_000019a_Paris_StringLights_01_Pink_Color"


def conditions():
    """Return independent, editable pilot conditions before the suite is frozen."""
    scenes = {name: load_scene(name) for name in ("cornell-box", "arcade", "bistro")}
    interior = copy.deepcopy(scenes["bistro"])
    exterior = copy.deepcopy(interior)
    exterior["camera"].update(position=[-20., 1.8, 12.], direction=[1., 0., 0.],
                              up=[0., 1., 0.], vertical_fov=60.)
    exterior["motion"]["end_position"] = [-19., 1.8, 12.5]
    for scene in (interior, exterior):
        x, y, z = scene["camera"]["direction"]
        angle = math.radians(10)
        scene["motion"].update(end_direction=[math.cos(angle)*x + math.sin(angle)*z,
                                               y, -math.sin(angle)*x + math.cos(angle)*z],
                                end_up=copy.deepcopy(scene["camera"]["up"]))
    base = load_definition()
    base.update(resolution=[1920, 1080], pdf_similarity=False, pdf_history_mode=0,
                initial_local_sampling_mode="POWER_RIS", initial_local_candidates=24,
                initial_environment_candidates=8, initial_infinite_candidates=1,
                initial_brdf_candidates=0, max_history_length=20, spatial_neighbors=4,
                spatial_radius=32, reset_frame=65, motion={"start_frame": 32, "end_frame": 64})
    matrix = [
        ("cornell-static", scenes["cornell-box"], "static"),
        ("arcade-static", scenes["arcade"], "static"),
        ("bistro-interior-static", interior, "static"),
        ("bistro-exterior-static", exterior, "static"),
        ("arcade-motion", scenes["arcade"], "motion"),
        ("bistro-interior-motion", interior, "motion"),
        ("bistro-exterior-motion", exterior, "motion"),
        ("bistro-lighting", exterior, "lighting"),
    ]
    result = []
    for name, scene, scenario in matrix:
        definition = copy.deepcopy(base)
        definition["frames"] = 128 if scenario == "static" else 96
        captures = [1, 20, 40, 128] if scenario == "static" else list(range(1, 97))
        definition["captures"] = {key: list(captures) for key in ("static", "motion", "reset")}
        if scenario != "static":
            definition["logical_fps"] = 30
        if scenario == "lighting":
            definition["lighting"] = {"material": PINK_MATERIAL, "start_frame": 32,
                                      "end_frame": 64, "peak_multiplier": 2.}
            definition["captures"]["lighting"] = list(captures)
        result.append({"id": name, "scene": copy.deepcopy(scene), "definition": definition,
                       "scenario": scenario,
                       "rois": [{"name": "region-1", "x": 700, "y": 450, "width": 256, "height": 256},
                                {"name": "region-2", "x": 1100, "y": 500, "width": 256, "height": 256}]})
    return result


def build_config(condition, seed, pdf_enabled, mode="combined", neighbors=4):
    """Resolve one method/seed without changing its frozen condition."""
    definition = copy.deepcopy(condition["definition"])
    definition.update(pdf_similarity=pdf_enabled, pdf_history_mode=0, spatial_neighbors=neighbors)
    config = make_config(condition["scene"], definition, mode, condition["scenario"], seed,
                         resolution=(1920, 1080))
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
