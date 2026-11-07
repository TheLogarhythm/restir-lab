"""Explicit transport contracts; estimator provenance is deliberately separate.

These records describe intended integrands, not proof of renderer conformance.
The collector must additionally validate the observed renderer controls and the
build's transport conformance evidence before binding a reference to a method.
"""
import copy
import hashlib
import json
import math

from .reference import target as legacy_target


def profile(component):
    if component not in ("direct", "full"):
        raise ValueError("Transport component must be direct or full")
    return {
        "schema_version": 1,
        "component": component,
        "max_surface_scattering": 1 if component == "direct" else 2,
        "primary_visibility": "RTXDI-v3.1-ray-query-opaque-gbuffer",
        "primary_material": "native-packed-gbuffer-Lambert-GGX",
        "secondary_material": "authored-Lambert-GGX-no-override-no-roughness-floor",
        "pixel_filter": "pixel-center-no-jitter-no-AA-identity-resolution",
        "delta_paths": ("excluded-from-opaque-DI" if component == "direct" else
                        "mirror-reflection-emissive-and-environment-endpoints-within-depth"),
        "transmission": "native-alpha-and-colored-segment-transmittance-no-refraction",
        "glass": "legacy-DI-GlassPass-eight-layers-approximate-reflection",
        "emission": "primary-authored-once; indexed-continuous-endpoints-packed-light-radiance; delta-or-unindexed-authored-one-sided",
        "environment_transport": "continuous-packed-light-scale-and-rotation; delta-authored-scale-and-rotation",
        "background": "native-environment-pixel-center",
        "output": "linear-radiance-before-display",
    }


def validate_profile(value):
    if not isinstance(value, dict) or value != profile(value.get("component")):
        raise ValueError("Unsupported or incomplete transport profile")
    # bool compares equal to int in Python; contract numbers must remain numbers.
    for key in ("schema_version", "max_surface_scattering"):
        if type(value[key]) is not int:
            raise ValueError(f"Invalid transport {key}")
    return copy.deepcopy(value)


def target(config, frame, asset_hash, component):
    value = copy.deepcopy(legacy_target(config, frame, asset_hash))
    # A renderer revision identifies an estimator implementation, not its target.
    del value["renderer_commit"]
    del value["output"]
    value["schema_version"] = 1
    value["transport"] = profile(component)
    return value


def target_key(value):
    validate_profile(value["transport"])
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def path_sample_schedule(seed, spp, *, completed_spp=0):
    """Absolute path indices; light proposals and process restarts do not add spp."""
    for name, value, lower, upper in (("seed", seed, 0, 4095),
                                     ("spp", spp, 1, 1048576),
                                     ("completed_spp", completed_spp, 0, spp - 1)):
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError(f"Invalid path sample {name}")
    return [{"sample_index": i, "completed_spp": i + 1,
             "sampling_frame": seed * 1048576 + i}
            for i in range(completed_spp, spp)]


def method_config(base, algorithm, cgns):
    """Use native CLI controls where available; explicit JSON controls otherwise."""
    if algorithm not in ("DI", "GI", "PT") or type(cgns) is not bool:
        raise ValueError("Method requires DI/GI/PT and an explicit boolean CGNS toggle")
    config = copy.deepcopy(base)
    if algorithm == "DI":
        config["definition"]["cgns"] = cgns
        return config
    if base["mode"] not in ("spatial", "combined") or base.get("reference"):
        raise ValueError("Indirect comparison requires a spatial method configuration")
    config["definition"]["cgns"] = False  # Shared original DI direct component.
    config["definition"]["transport_schema"] = 1
    config["transport"] = profile("full")
    config["transport_method"] = {
        "schema_version": 1, "algorithm": algorithm, "cgns": cgns,
        "initial_paths_per_pixel": 1,
        "secondary_nee": {"local": 2, "environment": 1, "infinite": 1, "sampling": "UNIFORM"},
        "secondary_roughness_floor": 0.0, "secondary_reuse": False,
        "radiance_clamp": False, "russian_roulette": False,
        "minimum_path_throughput": 0.0, "extra_mirror_bounces": 0,
        "denoiser_psr": False, "decorrelation": False,
        "glass": "legacy-DI", "common_gi_fixes": ["final-reservoir-index", "delta-output", "terminal-secondary-delta", "one-sided-emission",
            "fixed-lobe-mixture", "visible-GGX-pdf", "joint-delta-diffuse-pdf", "null-M-normalization", "independent-final-MIS-terms"],
        "pt_endpoint_mis": "fixed-sample-count-partition; analytic/delta/unindexed-weight-one",
        "environment_proposal_floor": 1.0 / 1024,
    }
    args, definition = config["arguments"], config["definition"]
    if config["scene"]["lighting"]["environment"] == "none":
        config["transport_method"]["secondary_nee"]["environment"] = 0
    args["lighting.indirectMode"] = "RESTIR" + algorithm
    if algorithm == "GI":
        args.update({
            "restirGI.mode": "TEMPORAL_SPATIAL" if config["mode"] == "combined" else "SPATIAL",
            "restirGI.temporalResampling.maxHistoryLength": definition["max_history_length"],
            "restirGI.temporalResampling.maxReservoirAge": definition["max_history_length"],
            "restirGI.temporalResampling.enableFallbackSampling": 0,
            "restirGI.temporalResampling.enablePermutationSampling": 0,
            "restirGI.temporalResampling.biasCorrectionMode": "RAYTRACED",
            "restirGI.spatialResampling.numSamples": definition["spatial_neighbors"],
            "restirGI.spatialResampling.samplingRadius": definition["spatial_radius"],
            "restirGI.spatialResampling.biasCorrectionMode": "RAYTRACED",
            "restirGI.boilingFilter.enableBoilingFilter": 0,
            "restirGI.finalShading.enableFinalVisibility": 1,
            "restirGI.finalShading.enableFinalMIS": 1,
        })
    else:
        args.update({
            "pt.lightSamplingMode": "MIS",
            "restirPT.resamplingMode": "TEMPORAL_SPATIAL" if config["mode"] == "combined" else "SPATIAL",
            "restirPT.initialSampling.numInitialSamples": 1,
            # Native PT includes the light endpoint in its path-length bound.
            "restirPT.initialSampling.maxBounceDepth": 3,
            "restirPT.initialSampling.maxRcVertexLength": 4,
            "restirPT.hybridShift.maxBounceDepth": 3,
            "restirPT.hybridShift.maxRcVertexLength": 4,
            "restirPT.temporalResampling.maxHistoryLength": definition["max_history_length"],
            "restirPT.temporalResampling.maxReservoirAge": definition["max_history_length"],
            "restirPT.temporalResampling.enablePermutationSampling": 0,
            "restirPT.temporalResampling.duplicationBasedHistoryReduction": 0,
            "restirPT.temporalResampling.enableFallbackSampling": 0,
            "restirPT.temporalResampling.enableAgeBasedRejection": 0,
            "restirPT.temporalResampling.enableVisibilityBeforeCombine": 1,
            "restirPT.boilingFilter.enableBoilingFilter": 0,
            "restirPT.spatialResampling.numSpatialSamples": definition["spatial_neighbors"],
            "restirPT.spatialResampling.numDisocclusionBoostSamples": definition["spatial_neighbors"],
            "restirPT.spatialResampling.samplingRadius": definition["spatial_radius"],
        })
    return config


def expected_controls(config):
    t = config["transport_method"]
    canonical = method_config(config, t["algorithm"], t["cgns"])
    if t != canonical["transport_method"] or config["transport"] != profile("full"):
        raise ValueError("Unsupported transport controls/target")
    d = config["definition"]
    count, radius, history = d["spatial_neighbors"], float(d["spatial_radius"]), d["max_history_length"]
    mode = {"spatial": 2, "combined": 3}[config["mode"]]
    result = {"schema_version": 1, "direct_mode": 2,
        "indirect_mode": 2 if t["algorithm"] == "GI" else 3,
        "gs": {"numSamples": count, "samplingRadius": radius, "pad1": int(t["cgns"]),
               "pad2": d.get("cgns_candidates", 32), "pad3": int(d.get("cgns_early_stopping", True))},
        "nee": {"numLocalLightSamples": t["secondary_nee"]["local"],
                "numEnvironmentSamples": t["secondary_nee"]["environment"],
                "numInfiniteLightSamples": t["secondary_nee"]["infinite"],
                "numBrdfSamples": 0, "localLightSamplingMode": 0, "enableInitialVisibility": 1},
        "path": {"enableSecondaryDISpatialResampling": 0, "enableRussianRoulette": 0,
                 "minimumPathThroughput": 0.0, "extraMirrorBounceBudget": 0,
                 "sampleEmissivesOnSecondaryHit": 0, "sampleEnvMapOnSecondaryMiss": 0,
                 "lightSamplingMode": 2},
        "secondary_roughness_floor": 0.0, "secondary_reuse": False,
        "primary_roughness_override": False, "primary_metalness_override": False,
        "denoiser_psr": False, "gi_common_fixes": "final-reservoir-index+delta-output+no-radiance-clamp+terminal-delta+joint-mixture-null-M+final-MIS",
        "transport_revision": 2,
        "glass": "legacy-DI"}
    if t["algorithm"] == "GI":
        result.update(gi_mode=mode, gi_final_reservoir=1,
            gt={"maxHistoryLength": history, "maxReservoirAge": history, "enableFallbackSampling": 0,
                "enablePermutationSampling": 0, "biasCorrectionMode": 3},
            gf={"enableFinalVisibility": 1, "enableFinalMIS": 1}, gb={"enableBoilingFilter": 0})
        result["gs"].update(biasCorrectionMode=3, normalThreshold=0.6, depthThreshold=0.1)
    else:
        result.update(pt_mode=mode,
            ps={"numSpatialSamples": count, "numDisocclusionBoostSamples": count,
                "samplingRadius": radius, "enableSpatialHeuristicMode": int(t["cgns"]),
                "duplicationBasedHistoryReduction": 0, "maxTemporalHistory": history,
                "normalThreshold": 0.6, "depthThreshold": 0.1},
            pi={"numInitialSamples": 1, "maxBounceDepth": 3, "maxRcVertexLength": 4},
            ph={"maxBounceDepth": 3, "maxRcVertexLength": 4},
            ptp={"maxHistoryLength": history, "maxReservoirAge": history,
                 "enableFallbackSampling": 0, "enablePermutationSampling": 0,
                 "enableVisibilityBeforeCombine": 1, "enableAgeBasedRejection": 0,
                 "duplicationBasedHistoryReduction": 0},
            pd={"decorrelationMode": 0, "fireflyReplacementFilterEnable": 0},
            pb={"enableBoilingFilter": 0})
    return result


def validate_controls(config, actual):
    """Validate observed renderer values, never just an echoed request."""
    def check(expected, value, path):
        if isinstance(expected, dict):
            if not isinstance(value, dict) or not set(expected) <= set(value):
                raise RuntimeError(f"Missing resolved transport controls: {path}")
            for key, item in expected.items():
                check(item, value[key], path + "." + key)
        elif type(expected) is float:
            if type(value) not in (int, float) or not math.isfinite(value) or not math.isclose(value, expected, rel_tol=1e-6, abs_tol=1e-7):
                raise RuntimeError(f"Resolved transport differs: {path}")
        elif type(value) is not type(expected) or value != expected:
            raise RuntimeError(f"Resolved transport differs: {path}")
    check(expected_controls(config), actual, "transport_controls")


def validate_timings(config, rows):
    t = config["transport_method"]
    active = {"gi_neighbor": t["algorithm"] == "GI" and t["cgns"],
              "pt_neighbor": t["algorithm"] == "PT" and t["cgns"],
              "gi_temporal": t["algorithm"] == "GI" and config["mode"] == "combined",
              "gi_spatial": t["algorithm"] == "GI", "gi_shading": t["algorithm"] == "GI",
              "pt_initial": t["algorithm"] == "PT", "pt_spatial": t["algorithm"] == "PT",
              "pt_temporal": t["algorithm"] == "PT" and config["mode"] == "combined"}
    for row in rows:
        for name, enabled in active.items():
            if name + "_ms" not in row or (float(row[name + "_ms"]) > 0) != enabled:
                raise RuntimeError(f"Unexpected transport pass execution: {name}")
