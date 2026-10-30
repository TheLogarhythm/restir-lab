"""One-frame CGNS config, resolved controls and timing record for runtime checks."""

from experiment.config import load_definition, make_config
from experiment.scenes import load_scene


def cgns_runtime_record(enabled=True):
    definition = load_definition()
    definition.update(cgns=enabled, cgns_candidates=8, cgns_early_stopping=False)
    config = make_config(load_scene("cornell-box"), definition, "combined", "static")
    config["frames"] = config["frames"][:1]
    frame, scene = config["frames"][0], config["scene"]
    definition = config["definition"]
    resolved = {
        "cgns": enabled, "cgns_candidates": 8, "cgns_early_stopping": False,
        "mode": 3, "width": config["width"], "height": config["height"],
        "scene_id": config["scene_id"], "loaded_scene": "Assets/Media/" + scene["source"]["entry"],
        "headless": True, "vertical_fov_degrees": scene["camera"]["vertical_fov"],
        "denoiser": 0, "aa": 0, "checkerboard": 0, "pixel_jitter": 0,
        "initialSamplingParams": {
            "numLocalLightSamples": definition["initial_local_candidates"],
            "numBrdfSamples": definition["initial_brdf_candidates"],
            "numInfiniteLightSamples": definition["initial_infinite_candidates"],
            "numEnvironmentSamples": definition["initial_environment_candidates"],
            "localLightSamplingMode": int(definition.get("initial_local_sampling_mode", "UNIFORM") == "POWER_RIS"),
            "environmentMapImportanceSampling": 1},
        "environment_present": True,
        "spatialResamplingParams": {"numSamples": definition["spatial_neighbors"]},
        "temporalResamplingParams": {"maxHistoryLength": definition["max_history_length"]},
        **scene["lighting"],
    }
    row = {"frame": 1, "sampling_frame": frame["sampling_frame"], "capture": int(frame["capture"]),
           "history_reset": 1, "gpu_ms": 4, "temporal_ms": 1, "spatial_ms": 1,
           "neighbor_selection_ms": .25 if enabled else 0}
    return config, resolved, row
