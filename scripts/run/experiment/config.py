"""Resolve one scene and one experiment into a deterministic frame sequence."""
import copy
import json
import math
from pathlib import Path

from rtxdi_common import ROOT, di_settings
from .scenes import scene_arguments, validate_scene

DEFAULT_CONFIG = ROOT / "experiments/configs/di-reuse.json"
MODES = {"initial": "NONE", "temporal": "TEMPORAL", "spatial": "SPATIAL", "combined": "TEMPORAL_SPATIAL"}
MODE_VALUES = {"initial": 0, "temporal": 1, "spatial": 2, "combined": 3}
LOCAL_SAMPLING_MODES = {"UNIFORM": 0, "POWER_RIS": 1}
NEE_SAMPLE_COUNTS = {"UNIFORM": "numLocalLightUniformSamples", "POWER_RIS": "numLocalLightPowerRISSamples"}
SCENARIOS = ("static", "motion", "reset")


def load_definition(path=DEFAULT_CONFIG):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_definition(definition, seed, resolution):
    if type(definition.get("pdf_similarity", False)) is not bool:
        raise ValueError("pdf_similarity must be a boolean")
    def integer(value, minimum, maximum, name):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{name} must be an integer in {minimum}..{maximum}")
    integer(seed, 0, 4095, "seed")
    if len(resolution) != 2:
        raise ValueError("Resolution must contain width and height")
    for value in resolution:
        integer(value, 1, 16384, "resolution")
    count = definition["frames"]
    integer(count, 2, 1048576, "frames")
    integer(definition["reset_frame"], 2, count, "reset_frame")
    motion = definition["motion"]
    integer(motion["start_frame"], 1, count - 1, "motion.start_frame")
    integer(motion["end_frame"], motion["start_frame"] + 1, count, "motion.end_frame")
    for scenario in SCENARIOS:
        captures = definition["captures"][scenario]
        if not captures or len(set(captures)) != len(captures):
            raise ValueError("Capture frames must be nonempty and unique")
        for frame in captures:
            integer(frame, 1, count, "capture frame")
    for key in ("initial_local_candidates", "initial_brdf_candidates",
                "initial_infinite_candidates", "initial_environment_candidates"):
        integer(definition[key], 0, 1024, key)
    if definition.get("initial_local_sampling_mode", "UNIFORM") not in LOCAL_SAMPLING_MODES:
        raise ValueError("initial_local_sampling_mode must be UNIFORM or POWER_RIS")
    if type(definition.get("analytic_sun", True)) is not bool:
        raise ValueError("analytic_sun must be a boolean")
    integer(definition["spatial_neighbors"], 1, 32, "spatial_neighbors")
    integer(definition["max_history_length"], 1, 16383, "max_history_length")
    if not math.isfinite(definition["spatial_radius"]) or definition["spatial_radius"] <= 0:
        raise ValueError("spatial_radius must be positive and finite")


def make_config(scene, definition, mode, scenario, seed=None, resolution=None, diagnostics=False, *, headless=True):
    scene, definition = copy.deepcopy(scene), copy.deepcopy(definition)
    seed = definition["seed"] if seed is None else seed
    width, height = resolution or definition["resolution"]
    validate_scene(scene)
    validate_definition(definition, seed, (width, height))
    if mode not in MODES or scenario not in SCENARIOS:
        raise ValueError("Unknown reuse mode or scenario")
    if definition.get("pdf_similarity", False) and mode not in ("spatial", "combined"):
        raise ValueError("pdf_similarity requires spatial or combined reuse")
    settings = di_settings(width, height)
    settings.update(scene_arguments(scene))
    local_mode = definition.get("initial_local_sampling_mode", "UNIFORM")
    settings.update({
        "device.headless": int(headless),
        "preset.dlssRR": 0, "postProcessing.bloom": 0,
        "postProcessing.toneMapping": 0, "postProcessing.textures": 1,
        "restirDI.diMode": MODES[mode],
        "restirDI.initialSampling.localLightSamplingMode": local_mode,
        "restirDI.initialSampling.numLocalLightSamples": definition["initial_local_candidates"],
        "restirDI.neeLocalLightSampling." + NEE_SAMPLE_COUNTS[local_mode]: definition["initial_local_candidates"],
        "restirDI.initialSampling.numBrdfSamples": definition["initial_brdf_candidates"],
        "restirDI.initialSampling.numInfiniteLightSamples": definition["initial_infinite_candidates"],
        "restirDI.initialSampling.numEnvironmentSamples": definition["initial_environment_candidates"],
        "restirDI.initialSampling.environmentMapImportanceSampling": 1,
        "restirDI.initialSampling.enableInitialVisibility": 1,
        "restirDI.temporalResampling.maxHistoryLength": definition["max_history_length"],
        "restirDI.temporalResampling.biasCorrectionMode": "RAYTRACED",
        "restirDI.temporalResampling.enableVisibilityShortcut": 0,
        "restirDI.temporalResampling.enablePermutationSampling": 0,
        "restirDI.spatialResampling.numSamples": definition["spatial_neighbors"],
        "restirDI.spatialResampling.numDisocclusionBoostSamples": definition["spatial_neighbors"],
        "restirDI.spatialResampling.samplingRadius": definition["spatial_radius"],
        "restirDI.spatialResampling.biasCorrectionMode": "RAYTRACED",
        "restirDI.spatialResampling.discountNaiveSamples": 0,
        "restirDI.boilingFilter.enableBoilingFilter": 0,
        "restirDI.shading.enableFinalVisibility": 1, "restirDI.shading.reuseFinalVisibility": 0,
    })
    frames = []
    motion, camera = definition["motion"], scene["camera"]
    for frame in range(1, definition["frames"] + 1):
        fraction = (min(1, max(0, (frame - motion["start_frame"]) /
                    (motion["end_frame"] - motion["start_frame"]))) if scenario == "motion" else 0)
        position = [float(a + fraction * (b - a))
                    for a, b in zip(camera["position"], scene["motion"]["end_position"])]
        frames.append({"frame": frame, "sampling_frame": seed * 1048576 + frame - 1,
                       "position": position, "direction": camera["direction"], "up": camera["up"],
                       "reset": frame == 1 or (scenario == "reset" and frame == definition["reset_frame"]),
                       "capture": frame in definition["captures"][scenario]})
    # Registry/provenance belongs in the manifest, not in the renderer interface.
    scene.pop("registry", None)
    return {"schema_version": 3, "scene_id": scene["scene_id"], "scene": scene,
            "mode": mode, "scenario": scenario, "seed": seed, "width": width, "height": height,
            "diagnostics": diagnostics, "arguments": settings, "frames": frames,
            "definition": definition, "preview": {**scene["preview"], "transform": "Reinhard + sRGB"}}
