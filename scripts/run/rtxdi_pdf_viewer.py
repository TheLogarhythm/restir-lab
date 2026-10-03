"""RTXDI FullSample viewer with PDF similarity in the Direct Lighting GUI."""
import argparse
from datetime import datetime, timezone
import json
import os
import subprocess
from experiment.config import load_definition, make_config
from experiment.scenes import load_scene, validate_assets
from experiment.runner import preflight, relative_path
from rtxdi_common import ROOT, RENDERER


def viewer_config(scene, mode, resolution, enabled=True, frames=0):
    definition = load_definition()
    definition["pdf_similarity"] = enabled
    config = make_config(scene, definition, mode, "static", resolution=resolution, headless=False)
    config.update(interactive=True, viewer_frames=frames, purpose="interactive_visual_inspection")
    config["frames"] = config["frames"][:1]
    config["frames"][0]["capture"] = False
    config["arguments"]["postProcessing.toneMapping"] = 1
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", default="cornell-box")
    parser.add_argument("--mode", choices=["spatial", "combined"], default="combined")
    parser.add_argument("--resolution", type=int, nargs=2, default=[1280, 720])
    parser.add_argument("--off", action="store_true", help="Start with PDF similarity disabled")
    parser.add_argument("--frames", type=int, default=0, help="Close after N frames; 0 keeps the viewer open")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.frames < 0:
        parser.error("frames must be nonnegative")
    scene = load_scene(args.scene)
    config = viewer_config(scene, args.mode, args.resolution, not args.off, args.frames)
    validate_assets(scene)
    exe = RENDERER / "build/bin/FullSamplePdf.exe"
    build = preflight({**config["definition"], "pdf_similarity": True}, executable=exe)
    if args.check:
        print("PDF viewer configuration, assets and build verified")
        return
    output = ROOT / "build/pdf-viewer" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output.mkdir(parents=True, exist_ok=False)
    config["output"] = "."
    config["repository_root"] = relative_path(ROOT, output)
    (output / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    command = [str(exe), *(f"--{key}={value}" for key, value in config["arguments"].items())]
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("RTXDI_")}
    environment["RTXDI_EXPERIMENT_CONFIG"] = "config.json"
    print(f"Direct Lighting > ReSTIR: PDF Similarity checkbox. Full RTXDI settings are available. Logs: {output}", flush=True)
    record = {"purpose": config["purpose"], "build": build, "command": command}
    with (output / "renderer.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=output, env=environment, stdout=log, stderr=subprocess.STDOUT)
    record["exit_code"] = result.returncode
    (output / "viewer.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Viewer exited with {result.returncode}; see {output / 'renderer.log'}")


if __name__ == "__main__":
    main()
