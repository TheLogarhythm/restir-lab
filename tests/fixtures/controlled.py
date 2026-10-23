"""Controlled capture records with real resolved physical states."""
from pathlib import Path
from experiment.controlled_suite import build_config
from experiment.reference import target, target_key


def captures_for(condition, seed=1, enabled=False, mode="combined", neighbors=4):
    config = build_config(condition, seed, enabled, mode, neighbors)
    records = []
    for frame in config["frames"]:
        if frame["capture"]:
            value = target(config, frame, "fixture-assets-" + config["scene_id"])
            records.append({"directory": Path(condition["id"]) / mode / str(neighbors) / str(seed) / str(enabled),
                            "condition_id": condition["id"], "config": config, "frame": frame,
                            "image": Path(condition["id"]) / f"{frame['frame']}.pfm.gz",
                            "target": value, "key": target_key(value)})
    return records
