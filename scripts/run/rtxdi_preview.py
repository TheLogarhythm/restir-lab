"""Capture one registered scene for visual import checks; no comparison suite."""
import argparse
from datetime import datetime, timezone
import json
import numpy as np
from PIL import Image
from experiment.images import read_pfm, write_pfm, preview_rgb
from rtxdi_common import sha
from experiment.config import load_definition, make_config
from experiment.runner import output_directory, preflight, run_one
from experiment.scenes import load_scene, validate_assets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--resolution", nargs=2, type=int, default=[1280, 720])
    parser.add_argument("--output-name")
    parser.add_argument("--average-frames", type=int, default=1, help="Average the last N static HDR frames for the viewing image")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    scene = load_scene(args.scene)
    assets = validate_assets(scene)
    definition = load_definition()
    if not 1 <= args.average_frames <= definition["frames"]:
        parser.error("average-frames must be between 1 and the configured frame count")
    frames = list(range(definition["frames"] - args.average_frames + 1, definition["frames"] + 1))
    definition["captures"]["static"] = frames
    config = make_config(scene, definition, "combined", "static", resolution=args.resolution)
    config["purpose"] = "scene_import_preview"
    if args.check:
        print(f"Validated {args.scene}: {len(assets['file_sha256'])} resources")
        return
    name = args.output_name or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-preview-" + args.scene
    build = preflight(definition)
    output = output_directory(name)
    run_one(config, output, build, assets)
    mean = np.zeros((config["height"], config["width"], 3), dtype=np.float64)
    inputs = {}
    for frame in frames:
        path = output / f"frame-{frame:04d}.pfm.gz"
        mean += read_pfm(path) / len(frames)
        inputs[path.name] = sha(path)
    write_pfm(output / "preview.pfm.gz", mean)
    Image.fromarray(preview_rgb(mean, scene["preview"]["exposure_ev"])).save(output / "preview.png")
    (output / "preview.json").write_text(json.dumps({"purpose": "scene_import_preview", "frames": frames,
        "operation": "static scene-linear arithmetic mean; viewing output, not a reference",
        "exposure_ev": scene["preview"]["exposure_ev"], "input_sha256": inputs,
        "image_sha256": sha(output / "preview.png")}, indent=2) + "\n", encoding="utf-8")
    print(output / "preview.png")


if __name__ == "__main__":
    main()
