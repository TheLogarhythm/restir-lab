"""Run bounded Falcor captures with separate linear HDR and display artifacts."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
from importlib.metadata import version
from pathlib import Path
import subprocess
import sys
import time

if __package__:
    from .process_utils import check_renderer_idle, exclusive_operation, stop_process
else:
    from process_utils import check_renderer_idle, exclusive_operation, stop_process
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from image_io.exr import read_exr
from records.provenance import shared_source_hashes


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def validate_config(config):
    if config.get("mode") not in ("path-tracer", "restir-pt"):
        raise ValueError("Invalid mode")
    for key in ("width", "height", "frames"):
        if type(config.get(key)) is not int or not 1 <= config[key] <= 16384:
            raise ValueError("Invalid " + key)
    frames = config.get("captures")
    if (
        not isinstance(frames, list)
        or not frames
        or any(type(f) is not int or not 1 <= f <= config["frames"] for f in frames)
        or frames != sorted(set(frames))
    ):
        raise ValueError("Invalid capture schedule")
    if (
        type(config.get("timeout")) not in (int, float)
        or not math.isfinite(config["timeout"])
        or config["timeout"] <= 0
    ):
        raise ValueError("Invalid timeout")
    return dict(config)


def execute(
    command, output, timeout, *, prepare=None, verify=None, metadata=None, visible=False
):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    record = {
        "schema_version": 1,
        "backend": "falcor",
        "status": "running",
        "command": command,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        **(metadata or {}),
    }
    save(output / "manifest.json", record)
    started = time.monotonic()
    proc = None
    try:
        if prepare:
            prepare(output)
        with (output / "renderer.log").open("w", encoding="utf-8") as log:
            flags = 0 if visible else getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(
                command,
                cwd=output,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=flags,
                start_new_session=os.name != "nt",
            )
            record["pid"] = proc.pid
            save(output / "manifest.json", record)
            try:
                code = proc.wait(timeout)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError("Owned renderer exceeded timeout") from exc
        record["exit_code"] = code
        if code:
            raise RuntimeError(f"Renderer failed with exit code {code}")
        if verify:
            record["artifacts"] = verify(output)
        record["status"] = "completed"
    except BaseException as exc:
        record.update(status="failed", error=str(exc))
        if proc is not None and proc.poll() is None:
            cleanup_error = stop_process(proc)
            if cleanup_error:
                record["cleanup_error"] = cleanup_error
        raise
    finally:
        record["wall_seconds_including_startup_export"] = time.monotonic() - started
        record["ended_utc"] = datetime.now(timezone.utc).isoformat()
        save(output / "manifest.json", record)
    return output / "manifest.json"


def inspect_hdr(path, width, height):
    import numpy as np

    rgb = read_exr(path, require_float32=True)
    if (
        rgb.shape != (height, width, 3)
        or not np.isfinite(rgb).all()
        or not np.any(rgb > 0)
    ):
        raise ValueError("Malformed, nonfinite or black HDR")
    return rgb


def capture_frames(paths, expected):
    frames = []
    for path in paths:
        match = re.fullmatch(
            r"capture\.PathTracer\.color\.(\d+)(?:\.RGBA)?\.exr", path.name
        )
        if not match:
            raise ValueError("Unexpected capture filename: " + path.name)
        frames.append(int(match[1]))
    if sorted(frames) != expected:
        raise ValueError("Missing or unexpected HDR capture frames")
    return frames


def renderer_script(config, out, scene, *, interactive=False):
    """Generate a finite script for Falcor's embedded Python, including resolved camera evidence."""
    lines = [
        "import sys, json, contextlib",
        "from pathlib import Path",
        "from falcor import float3",
        "sys.path.insert(0," + repr(str(out)) + ")",
        "from graphs import build_graph",
        "g=build_graph(" + repr(config["mode"]) + ")",
        "m.addGraph(g)",
        "print('LAB graph ready',flush=True)",
        "m.loadScene(" + repr(str(scene)) + ")",
        "print('LAB scene loaded',flush=True)",
        "m.scene.animated=False",
        "camera=m.scene.camera",
        "camera.position=float3(0,5,-15)",
        "camera.target=float3(0,5,0)",
        "camera.up=float3(0,1,0)",
        "camera.frameHeight=24",
        "camera.focalLength=20.784609690826528",
        "camera.apertureRadius=0",
        "camera.nearPlane=0.1",
        "camera.farPlane=100",
        "print('LAB camera configured',flush=True)",
        "m.clock.pause()",
        "m.clock.time=0",
        "m.frameCapture.outputDir=" + repr(str(out)),
        "m.frameCapture.baseFilename='capture'",
        "print('LAB saving resolved configuration',flush=True)",
        "with Path("
        + repr(str(out / "resolved.py"))
        + ").open('w',encoding='utf-8') as graph_file, contextlib.redirect_stdout(graph_file):",
        "    g.print()",
        "print('LAB graph exported',flush=True)",
        "camera_record={'position':[camera.position.x,camera.position.y,camera.position.z],'target':[camera.target.x,camera.target.y,camera.target.z],'up':[camera.up.x,camera.up.y,camera.up.z],'frameHeight':camera.frameHeight,'focalLength':camera.focalLength,'apertureRadius':camera.apertureRadius,'nearPlane':camera.nearPlane,'farPlane':camera.farPlane}",
        "Path("
        + repr(str(out / "resolved-camera.json"))
        + ").write_text(json.dumps(camera_record,indent=2))",
        "for frame in range(1," + str(config["frames"] + 1) + "):",
        "    m.clock.frame=frame",
        "    m.renderFrame()",
        "    if frame in " + repr(config["captures"]) + ": m.frameCapture.capture()",
    ]
    if interactive:
        lines += [
            "import time",
            "time.sleep(30)",
        ]  # Hold the last presented frame; no additional rendering.
    lines.append("exit()")
    return "\n".join(lines) + "\n"


def launch(config, output, executable, *, interactive=False):
    # Lock before preflight: no renderer process exists yet while inputs are checked.
    with exclusive_operation(ROOT / "build/falcor/.operation.lock"):
        return _launch_locked(config, output, executable, interactive=interactive)


def _launch_locked(config, output, executable, *, interactive=False):
    config = validate_config(config)
    output = Path(output).resolve()
    executable = Path(executable).resolve()
    if output.exists():
        raise FileExistsError(output)
    check_renderer_idle()
    if __package__:
        from .build import verify_build
    else:
        from build import verify_build
    build = verify_build()
    if executable != (ROOT / build["executable"]).resolve():
        raise ValueError("Executable differs from build record")
    build_bytes = (ROOT / "build/falcor/build.json").read_bytes()
    if json.loads(build_bytes) != build:
        raise RuntimeError("Build record changed while preparing run")
    graph_bytes = Path(__file__).with_name("graphs.py").read_bytes()
    scene = ROOT / "scenes/configs/falcor/cornell-box.pyscene"
    asset = ROOT / "renderers/rtxdi/Assets/Media/CornellBox/CornellBox.gltf"
    gltf = json.loads(asset.read_text())
    resources = [asset]
    from urllib.parse import unquote

    for entry in gltf.get("buffers", []) + gltf.get("images", []):
        uri = entry.get("uri", "")
        if uri and not uri.startswith("data:"):
            resources.append((asset.parent / unquote(uri)).resolve())
    sources = [scene, Path(__file__), Path(__file__).with_name("graphs.py")]
    metadata = {
        "config": config,
        "build_manifest": "build.json",
        "build_manifest_sha256": hashlib.sha256(build_bytes).hexdigest(),
        "commit": build["commit"],
        "kind": "interactive_smoke" if interactive else "bounded_setup_smoke",
        "source_sha256": {**{p.relative_to(ROOT).as_posix(): sha(p) for p in sources},
                          **shared_source_hashes(ROOT)},
        "asset_sha256": {p.relative_to(ROOT).as_posix(): sha(p) for p in resources},
        "gpu": subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            text=True,
        ).strip(),
        "gpu_time_ms": None,
        "ui_hold_seconds": 30 if interactive else 0,
        "verifier_python": sys.version,
        "verifier_packages": {
            name: version(name) for name in ("numpy", "Pillow", "OpenEXR")
        },
        "rng_policy": "native PathTracer frameCount seed, fresh process, fixedSeed unset",
    }
    command = [
        str(executable),
        "--device-type",
        "d3d12",
        "--width",
        str(config["width"]),
        "--height",
        str(config["height"]),
        "--script",
        str(output / "render.py"),
    ]
    if not interactive:
        command.append("--headless")

    def prepare(out):
        save(out / "config.json", config)
        (out / "build.json").write_bytes(build_bytes)
        (out / "graphs.py").write_bytes(graph_bytes)
        (out / "render.py").write_text(
            renderer_script(config, out, scene, interactive=interactive),
            encoding="utf-8",
        )

    def verify(out):
        import numpy as np
        from PIL import Image

        files = sorted(out.glob("*.exr"))
        frames = capture_frames(files, config["captures"])
        rows = []
        for path, frame in zip(files, frames):
            rgb = inspect_hdr(path, config["width"], config["height"])
            # Fixed EV=0, Reinhard, sRGB; display transform never modifies HDR.
            linear = np.maximum(rgb, 0)
            mapped = linear / (1 + linear)
            display = np.where(
                mapped <= 0.0031308, 12.92 * mapped, 1.055 * mapped ** (1 / 2.4) - 0.055
            )
            preview = path.with_suffix(".png")
            Image.fromarray(np.uint8(np.clip(display, 0, 1) * 255 + 0.5)).save(preview)
            rows.append(
                {
                    "frame": frame,
                    "hdr": path.name,
                    "hdr_sha256": sha(path),
                    "encoding": "scene-linear RGB FLOAT32 EXR",
                    "min": float(rgb.min()),
                    "max": float(rgb.max()),
                    "preview": preview.name,
                    "preview_sha256": sha(preview),
                    "preview_transform": "EV0 Reinhard sRGB",
                }
            )
        if not all(
            (out / name).is_file() for name in ("resolved.py", "resolved-camera.json")
        ):
            raise ValueError("Resolved graph/camera configuration missing")
        return rows

    return execute(
        command,
        output,
        config["timeout"],
        prepare=prepare,
        verify=verify,
        metadata=metadata,
        visible=interactive,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--config", type=Path, default=ROOT / "experiments/configs/falcor-sanity-check.json"
    )
    p.add_argument("--mode", choices=("path-tracer", "restir-pt"), required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--interactive", action="store_true")
    args = p.parse_args()
    config = json.loads(args.config.read_text())
    config["mode"] = args.mode
    build = json.loads((ROOT / "build/falcor/build.json").read_text())
    print(
        launch(
            config,
            args.output,
            ROOT / build["executable"],
            interactive=args.interactive,
        )
    )


if __name__ == "__main__":
    main()
