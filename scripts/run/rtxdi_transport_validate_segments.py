"""Bounded GPU regression: a pane behind an opaque endpoint cannot tint it."""
import argparse
import copy
import json
import math
from pathlib import Path

import numpy as np

from rtxdi_transport_validate import ROOT, capture, plane_scene
from rtxdi_common import sha
from experiment.artifacts import save_json
from experiment.config import make_config
from experiment.comparison import EXECUTABLES
TRANSPORT = EXECUTABLES["GI"]
from experiment.images import read_pfm
from experiment.path_reference import make_config as reference_config, EXE as REFERENCE
from experiment.scenes import asset_files, bundle_digest, validate_assets
from experiment.comparison_config import load_spec, resolve_configs, DI_SPEC
from experiment.transport import method_config


def segment_scene(folder, front, back, reverse):
    scene = plane_scene(folder, "segment-fixture", metal=1, roughness=0,
                        color=(1, 1, 1), secondary_glass=True)
    path = folder / "fixture.gltf"
    document = json.loads(path.read_text())
    # The camera sees the mirror at z=2; its reflection reaches an emitter at z=-2.
    nodes = [document["nodes"][0], document["nodes"][2]]
    if front:
        nodes.append(document["nodes"][1])  # z=-1, between mirror and emitter.
    if back:
        angle = math.pi + .1
        # A large tilted pane has an overlapping AABB, but every central ray hits
        # its surface behind the emitter. This discourages relying on BVH order.
        nodes.append({"mesh": 1, "scale": [10, 10, 1],
                      "rotation": [0, math.sin(angle / 2), 0, math.cos(angle / 2)],
                      "translation": [-2 * math.sin(angle), 0, -3 - 2 * math.cos(angle)]})
    document["nodes"] = nodes
    order = list(range(len(nodes)))
    document["scenes"][0]["nodes"] = order[::-1] if reverse else order
    save_json(path, document)
    files = asset_files(folder / "fixture.scene.json", folder)
    scene["registry"]["runtime_assets"] = {"sha256": bundle_digest(files), "file_count": len(files)}
    scene.pop("config_sha256", None)
    save_json(folder / "scene-config.json", scene)
    scene["config_sha256"] = sha(folder / "scene-config.json")
    return scene


def validate(root, *, ray_query=True):
    root.mkdir(parents=True, exist_ok=False)
    base = resolve_configs(load_spec(DI_SPEC))[0]["config"]
    definition = copy.deepcopy(base["definition"])
    definition.update(frames=3, resolution=[32, 32], reset_frame=2,
                      motion={"start_frame": 1, "end_frame": 3},
                      captures={k: [3] for k in ("static", "motion", "reset")}, cgns=False)
    result = {"status": "running", "ray_query": ray_query, "resolution": [32, 32], "reference_spp": 8,
              "method_frames": 3, "fixtures": {}, "comparisons": {}}
    images = {}
    for reverse in (False, True):
        for name, front, back in (("none", False, False), ("front", True, False),
                                  ("back", False, True), ("both", True, True)):
            label = name + ("-reversed" if reverse else "")
            scene = segment_scene(root / "assets" / label, front, back, reverse)
            assets = validate_assets(scene)
            config = make_config(scene, definition, "combined", "static", seed=1, diagnostics=True)
            config["arguments"]["rendering.rayQuery"] = int(ray_query)
            jobs = {component: (reference_config(config, config["frames"][-1], component, 8), REFERENCE)
                    for component in ("direct", "full")}
            jobs.update({a.lower() + ("-cgns" if c else "-original"): (method_config(config, a, c), TRANSPORT)
                         for a in ("GI", "PT") for c in (False, True)})
            paths = {method: capture(settings, root / label / method, exe, assets)
                     for method, (settings, exe) in jobs.items()}
            images[label] = {method: read_pfm(path) for method, path in paths.items()}
            values = images[label]
            if not all(np.isfinite(image).all() for image in values.values()):
                raise ValueError(f"Nonfinite segment fixture: {label}")
            if np.max(np.abs(values["direct"])) > 1e-6:
                raise ValueError(f"Direct-only target unexpectedly includes reflection: {label}")
            errors = {method: float(np.max(np.abs(image - values["full"])))
                      for method, image in values.items() if method != "direct"}
            if max(errors.values()) > .006:
                raise ValueError(f"GI/PT segment target mismatch: {label}: {errors}")
            result["fixtures"][label] = {"images": {method: {"path": path.relative_to(root).as_posix(),
                "sha256": sha(path)} for method, path in paths.items()}, "error_vs_full": errors}
            save_json(root / "checks.json", result)
    for reverse in (False, True):
        suffix = "-reversed" if reverse else ""
        for left, right in (("none", "back"), ("front", "both")):
            errors = {method: float(np.max(np.abs(image - images[right + suffix][method])))
                      for method, image in images[left + suffix].items()}
            result["comparisons"][left + "-vs-" + right + suffix] = errors
            if max(errors.values()) > .006:
                raise ValueError(f"Occluded pane attenuates the foreground endpoint: {errors}")
    for name in ("none", "front", "back", "both"):
        errors = {method: float(np.max(np.abs(image - images[name + "-reversed"][method])))
                  for method, image in images[name].items()}
        result["comparisons"][name + "-node-order"] = errors
        if max(errors.values()) > .006:
            raise ValueError(f"Node ordering changes segment transport: {errors}")
    if np.max(np.abs(images["none"]["full"] - np.array([.25, .5, 1]))) > .006:
        raise ValueError("Unoccluded reflection must preserve emitter radiance")
    expected_front = np.array([.25, .5, 1]) * np.array([.3, .6, .9])
    if np.max(np.abs(images["front"]["full"] - expected_front)) > .006:
        raise ValueError("The front pane must apply its known colored transmission exactly once")
    result["status"] = "passed"
    save_json(root / "checks.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--ray-query", type=int, choices=(0, 1), default=1)
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_relative_to(ROOT / "runs/validation"):
        raise ValueError("Segment regression output must be under runs/validation")
    validate(root, ray_query=bool(args.ray_query))


if __name__ == "__main__":
    main()
