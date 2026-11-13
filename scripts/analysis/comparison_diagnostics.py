"""Shared saved-capture timing and merged-neighbor evidence."""
import numpy as np
from rtxdi_common import sha
from experiment.artifacts import spatial_neighbor_stats
from experiment.runner import relative_path
from experiment.saved_runs import source_record, resolve_source

def file_record(path, output):
    return {"path":relative_path(path,output), "sha256":sha(path)}

def neighbor_counts(item, frame, masks):
    record, directory = item["records"][frame], item["directory"]
    if not record.get("spatial_neighbors"):
        if item["resolved"].get("spatial_neighbor_counts") and item["config"]["mode"] in ("spatial","combined"):
            raise ValueError("Missing required spatial-neighbor capture")
        return {"available":False, "reason":"legacy run or mode without spatial reuse"}
    path = directory/record["spatial_neighbors"]
    if sha(path) != record["spatial_neighbors_sha256"]:
        raise ValueError("Spatial-neighbor capture was modified")
    config = item["config"]
    spatial_neighbor_stats(path,config["width"],config["height"],config["definition"]["spatial_neighbors"])
    values = np.fromfile(path,dtype="<u4").reshape(config["height"],config["width"])
    source = source_record(path)
    return {"available":True, "definition":record["spatial_neighbors_definition"],
            "mean_including_background":{name:float((values[mask]&127).mean()) for name,mask in masks.items()},
            "mean_surface":{name:float((values[mask & (values>=128)]&127).mean())
                            if (mask & (values>=128)).any() else None for name,mask in masks.items()},
            "source":source["path"], "source_path_base":source["path_base"], "sha256":sha(path),
            "cgns_preselected_mean_active":record.get("cgns_selected_mean_active")}


def capture_evidence(item, frame, masks, output):
    """Derive the per-seed measurement and source bindings from a validated run."""
    capture = item["captures"][frame]
    return {
        "frame":frame, "sampling_frame":capture["frame"]["sampling_frame"],
        "timing_ms":{k:v for k,v in item["timings"][frame].items() if k.endswith("_ms")},
        "timing_scope":item["manifest"].get("timing", "GPU frame scope unavailable"),
        "neighbors":neighbor_counts(item, frame, masks),
        "source":{name:file_record(item["directory"]/name, output)
                  for name in ("config.json", "manifest.json", "resolved.json", "timings.csv")},
        "hdr":file_record(capture["image"], output)}


def timing_summary(item, frame, algorithm):
    rows = list(item["timings"].values())
    measured = item["timings"][frame]
    selection = {"DI":"neighbor_selection_ms", "GI":"gi_neighbor_ms", "PT":"pt_neighbor_ms"}[algorithm]
    spatial = {"DI":"spatial_ms", "GI":"gi_spatial_ms", "PT":"pt_spatial_ms"}[algorithm]
    return {"gpu_ms_capture":float(measured["gpu_ms"]),
            "gpu_ms_mean_run":float(np.mean([float(row["gpu_ms"]) for row in rows])),
            "run_frames":len(rows), "selection_ms_capture":float(measured.get(selection, 0)),
            "spatial_ms_capture":float(measured.get(spatial, 0))}


def comparison_summary(original, cgns):
    if set(original) != set(cgns):
        raise ValueError("Comparison regions differ")
    return {region:{"original":original[region], "cgns":cgns[region],
                    "improvement_pp":original[region]-cgns[region],
                    "relative_improvement_percent":100*(original[region]-cgns[region])/original[region]
                    if original[region] else None} for region in original}




def check_records(value, base):
    if isinstance(value, dict):
        if set(value) == {"path", "path_base", "sha256"}:
            if sha(resolve_source(value["path"], value["path_base"])) != value["sha256"]:
                raise ValueError("Analysis input or artifact hash changed")
        if set(value) == {"path", "sha256"}:
            if sha((base / value["path"]).resolve()) != value["sha256"]:
                raise ValueError("Analysis input or artifact hash changed")
        for child in value.values():
            check_records(child, base)
    elif isinstance(value, list):
        for child in value:
            check_records(child, base)


