"""Resolve one scene and one experiment into a deterministic frame sequence."""
import copy
import json
import math
from pathlib import Path

from rtxdi_common import ROOT, di_settings
from .scenes import camera_basis, scene_arguments, validate_scene

DEFAULT_CONFIG = ROOT / "experiments/configs/di-reuse.json"
MODES = {"initial": "NONE", "temporal": "TEMPORAL", "spatial": "SPATIAL", "combined": "TEMPORAL_SPATIAL"}
MODE_VALUES = {"initial": 0, "temporal": 1, "spatial": 2, "combined": 3}
LOCAL_SAMPLING_MODES = {"UNIFORM": 0, "POWER_RIS": 1}
NEE_SAMPLE_COUNTS = {"UNIFORM": "numLocalLightUniformSamples", "POWER_RIS": "numLocalLightPowerRISSamples"}
SCENARIOS = ("static", "motion", "reset")


def _orientation(direction, up):
    """Unit quaternion (w,x,y,z) from an orthonormal camera basis."""
    basis = camera_basis(direction, up)
    matrix = [[basis[column][row] for column in range(3)] for row in range(3)]
    trace = sum(matrix[i][i] for i in range(3))
    if trace > 0:
        scale = math.sqrt(trace + 1.) * 2
        q = [scale / 4, (matrix[2][1] - matrix[1][2]) / scale,
             (matrix[0][2] - matrix[2][0]) / scale, (matrix[1][0] - matrix[0][1]) / scale]
    else:
        i = max(range(3), key=lambda k: matrix[k][k])
        j, k = (i + 1) % 3, (i + 2) % 3
        scale = math.sqrt(1 + matrix[i][i] - matrix[j][j] - matrix[k][k]) * 2
        q = [(matrix[k][j] - matrix[j][k]) / scale, 0., 0., 0.]
        q[i + 1] = scale / 4
        q[j + 1] = (matrix[j][i] + matrix[i][j]) / scale
        q[k + 1] = (matrix[k][i] + matrix[i][k]) / scale
    length = math.hypot(*q)
    return [v / length for v in q]


def _interpolate_orientation(start, end, fraction):
    dot = sum(a*b for a, b in zip(start, end))
    if dot < 0:
        end, dot = [-v for v in end], -dot
    angle = math.acos(min(1., dot))
    if angle < 1e-8:
        q = [(1-fraction)*a + fraction*b for a, b in zip(start, end)]
    else:
        q = [(math.sin((1-fraction)*angle)*a + math.sin(fraction*angle)*b) / math.sin(angle)
             for a, b in zip(start, end)]
    length = math.hypot(*q)
    w, x, y, z = [v / length for v in q]
    direction = [2*(x*z + w*y), 2*(y*z - w*x), 1-2*(x*x + y*y)]
    up = [2*(x*y - w*z), 1-2*(x*x + z*z), 2*(y*z + w*x)]
    _, up, direction = camera_basis(direction, up)
    return direction, up


def load_definition(path=DEFAULT_CONFIG):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_definition(definition, seed, resolution):
    if type(definition.get("pdf_similarity", False)) is not bool:
        raise ValueError("pdf_similarity must be a boolean")
    def integer(value, minimum, maximum, name):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{name} must be an integer in {minimum}..{maximum}")
    integer(definition.get("pdf_history_mode", 0), 0, 2, "pdf_history_mode")
    if definition.get("pdf_history_mode", 0) and not definition.get("pdf_similarity", False):
        raise ValueError("pdf_history_mode requires pdf_similarity")
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
    if "logical_fps" in definition:
        fps = definition["logical_fps"]
        if type(fps) not in (int, float) or not math.isfinite(fps) or fps <= 0:
            raise ValueError("logical_fps must be positive and finite")
    if "lighting" in definition:
        light = definition["lighting"]
        if not isinstance(light, dict) or set(light) != {"material", "start_frame", "end_frame", "peak_multiplier"}:
            raise ValueError("lighting requires material, start_frame, end_frame and peak_multiplier")
        if not isinstance(light["material"], str) or not light["material"].strip() or "\0" in light["material"]:
            raise ValueError("lighting.material must name one existing emissive material")
        integer(light["start_frame"], 1, count - 2, "lighting.start_frame")
        integer(light["end_frame"], light["start_frame"] + 2, count, "lighting.end_frame")
        if (light["end_frame"] - light["start_frame"]) % 2:
            raise ValueError("lighting requires an even number of ramp increments")
        peak = light["peak_multiplier"]
        if type(peak) not in (int, float) or not math.isfinite(peak) or peak <= 0:
            raise ValueError("lighting.peak_multiplier must be positive and finite")
    for scenario in (*SCENARIOS, *(("lighting",) if "lighting" in definition else ())):
        if scenario not in definition["captures"]:
            raise ValueError(f"Missing {scenario} capture list")
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
    if scene["lighting"]["environment"] == "none":
        # There is no environment sampling domain; record the effective budget.
        definition["initial_environment_candidates"] = 0
    validate_definition(definition, seed, (width, height))
    if mode not in MODES or scenario not in (*SCENARIOS, "lighting"):
        raise ValueError("Unknown reuse mode or scenario")
    if scenario == "lighting" and "lighting" not in definition:
        raise ValueError("lighting scenario requires an explicit lighting schedule")
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
    orientation = None
    if scenario == "motion" and any(key in scene["motion"] for key in ("end_direction", "end_up")):
        orientation = (_orientation(camera["direction"], camera["up"]),
                       _orientation(scene["motion"].get("end_direction", camera["direction"]),
                                    scene["motion"].get("end_up", camera["up"])))
    if scenario == "lighting":
        light = definition["lighting"]
        half = (light["end_frame"] - light["start_frame"]) // 2
        # Reuse stored values on the return path: identical states have identical reference keys.
        ramp = [1. + (light["peak_multiplier"] - 1.) * (1. - math.cos(math.pi * i / half)) / 2.
                for i in range(half + 1)]
    for frame in range(1, definition["frames"] + 1):
        fraction = (min(1, max(0, (frame - motion["start_frame"]) /
                    (motion["end_frame"] - motion["start_frame"]))) if scenario == "motion" else 0)
        position = [float(a + fraction * (b - a))
                    for a, b in zip(camera["position"], scene["motion"]["end_position"])]
        direction, up = _interpolate_orientation(*orientation, fraction) if orientation else (camera["direction"], camera["up"])
        state = {"frame": frame, "sampling_frame": seed * 1048576 + frame - 1,
                       "position": position, "direction": direction, "up": up,
                       "reset": frame == 1 or (scenario == "reset" and frame == definition["reset_frame"]),
                       "capture": frame in definition["captures"][scenario]}
        if "logical_fps" in definition:
            state["logical_time_seconds"] = (frame - 1) / definition["logical_fps"]
        if scenario == "lighting":
            step = min(2 * half, max(0, frame - light["start_frame"]))
            state["lighting"] = {"material": light["material"],
                                 "emissive_intensity_multiplier": ramp[min(step, 2 * half - step)]}
        frames.append(state)
    # Registry/provenance belongs in the manifest, not in the renderer interface.
    scene.pop("registry", None)
    return {"schema_version": 3, "scene_id": scene["scene_id"], "scene": scene,
            "mode": mode, "scenario": scenario, "seed": seed, "width": width, "height": height,
            "diagnostics": diagnostics, "arguments": settings, "frames": frames,
            "definition": definition, "preview": {**scene["preview"], "transform": "Reinhard + sRGB"}}
