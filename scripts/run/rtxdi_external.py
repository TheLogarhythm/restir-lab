"""Run the local external-scene RTXDI FullSample variant with a glTF scene."""

import argparse
from datetime import datetime, timezone
import json
import os
import math
import platform
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageStat


from rtxdi_common import ROOT, di_settings, sha, validate_bmp
EXE = ROOT / "renderers/rtxdi/build/bin/FullSampleExternal.exe"
sys.path.insert(0, str(ROOT))
from scripts.assets.gltf import resource_path


def scene_resource_hashes(scene):
    document = json.loads(scene.read_text(encoding="utf-8"))
    uris = {entry["uri"] for field in ("buffers", "images") for entry in document.get(field, [])}
    return {uri: sha(resource_path(scene.parent, uri)) for uri in sorted(uris)}


def gpu_description():
    try:
        return subprocess.check_output(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                                        "--format=csv,noheader"], text=True, stderr=subprocess.STDOUT).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, required=True, help="Converted .gltf in a directory with its textures and buffers")
    parser.add_argument("--camera-position", nargs=3, type=float, metavar=("X", "Y", "Z"), required=True)
    parser.add_argument("--camera-direction", nargs=3, type=float, metavar=("X", "Y", "Z"), required=True)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument("--frame", type=int, default=30)
    parser.add_argument("--exposure-bias", type=float, help="Optional display exposure in EV; recorded in the run manifest")
    parser.add_argument("--emissive-scale", type=float, help="Optional local-light intensity multiplier; not source-equivalent")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args()
    numeric = [*args.camera_position, *args.camera_direction]
    numeric += [x for x in (args.exposure_bias, args.emissive_scale) if x is not None]
    if not all(math.isfinite(x) for x in numeric):
        parser.error("Camera, exposure and emissive values must be finite")
    if not any(args.camera_direction):
        parser.error("--camera-direction must be nonzero")
    if min(args.width, args.height, args.timeout) <= 0 or args.frame < 0:
        parser.error("Dimensions and timeout must be positive; frame must be nonnegative")
    if args.emissive_scale is not None and args.emissive_scale <= 0:
        parser.error("--emissive-scale must be positive")
    scene = args.scene.resolve()
    if scene.suffix.lower() != ".gltf" or not scene.is_file():
        parser.error("--scene must name an existing .gltf file")
    if not EXE.is_file():
        parser.error("Build FullSampleExternal first with scripts/run/build_rtxdi_external.py")
    try:
        resources = scene_resource_hashes(scene)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(f"Invalid scene resources: {exc}")
    build_record = EXE.with_suffix(".build.json")
    if not build_record.is_file():
        parser.error("Rebuild FullSampleExternal to record its build provenance")
    provenance = json.loads(build_record.read_text(encoding="utf-8"))
    if sha(EXE) != provenance["executable_sha256"]:
        parser.error("FullSampleExternal differs from its build record; rebuild it")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-external"
    output = ROOT / "runs" / run_id
    output.mkdir(parents=True)
    image = output / "capture.bmp"
    settings = di_settings(args.width, args.height)
    settings.update({"scene.asset": "CornellBox", "scene.animation": 0,
                     "camera.position": " ".join(map(str, args.camera_position)),
                     "camera.direction": " ".join(map(str, args.camera_direction))})
    if not args.interactive:
        settings.update({"profiling.saveFrame": args.frame, "profiling.saveFile": str(image)})
    command = [str(EXE)]
    for key, value in settings.items():
        command.extend(["--" + key, str(value)])
    record = {
        "run_id": run_id, "started_utc": datetime.now(timezone.utc).isoformat(),
        "kind": "project_external_scene_capture",
        "status": "running",
        "scene": str(scene),
        "scene_sha256": sha(scene), "resource_sha256": resources,
        "os": platform.platform(), "gpu": gpu_description(),
        "executable_sha256": sha(EXE),
        "runner_sha256": sha(Path(__file__)),
        "renderer_commit": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                   cwd=ROOT / "renderers/rtxdi", text=True).strip(),
        "build_provenance": provenance,
        "command": command,
        "environment": {"RTXDI_EXTERNAL_SCENE": str(scene)},
    }
    manifest = output / "manifest.json"
    env = {key: value for key, value in os.environ.items()
           if key not in ("RTXDI_EXTERNAL_SCENE", "RTXDI_EXPOSURE_BIAS", "RTXDI_EMISSIVE_SCALE")}
    env["RTXDI_EXTERNAL_SCENE"] = str(scene)
    if args.exposure_bias is not None:
        env["RTXDI_EXPOSURE_BIAS"] = str(args.exposure_bias)
        record["environment"]["RTXDI_EXPOSURE_BIAS"] = str(args.exposure_bias)
    if args.emissive_scale is not None:
        env["RTXDI_EMISSIVE_SCALE"] = str(args.emissive_scale)
        record["environment"]["RTXDI_EMISSIVE_SCALE"] = str(args.emissive_scale)
    record["cwd"] = str(output)
    record["settings"] = settings
    manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"Run: {output}", flush=True)
    try:
        with (output / "renderer.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(command, cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=None if args.interactive else args.timeout)
        record["exit_code"] = result.returncode
        if result.returncode:
            raise RuntimeError(f"FullSampleExternal exited with {result.returncode}")
        if not args.interactive:
            record["image"] = validate_bmp(image, (args.width, args.height))
            if "Saved the screenshot" not in (output / "renderer.log").read_text(encoding="utf-8", errors="replace"):
                raise RuntimeError("Renderer did not confirm saving the capture")
            record["image_sha256"] = sha(image)
            with Image.open(image) as captured:
                rgb = captured.convert("RGB")
                record["mean_rgb"] = [round(value, 3) for value in ImageStat.Stat(rgb).mean]
                if all(high == 0 for _, high in rgb.getextrema()):
                    raise RuntimeError("Capture is entirely black; choose another camera")
        record["status"] = "interactive_closed" if args.interactive else "capture_passed"
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
        print(str(exc), file=sys.stderr)
    except KeyboardInterrupt:
        record["status"] = "interrupted"
        print("Run interrupted", file=sys.stderr)
    finally:
        record["ended_utc"] = datetime.now(timezone.utc).isoformat()
        manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"{record['status']}: {manifest}")
    return int(record["status"] not in ("capture_passed", "interactive_closed"))


if __name__ == "__main__":
    sys.exit(main())
