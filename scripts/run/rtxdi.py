"""Run the pinned official FullSample on Cornell Box; capture or inspect a frame."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

from rtxdi_common import ROOT, RENDERER, di_settings, sha, validate_bmp

DEFAULT_CONFIG = {
    "renderer_commit": "a6efab966b7c3b272da0461578eb56ac61c7cbff",
    "scene_config": "scenes/configs/rtxdi/cornell-box.json",
    "capture_frame": 120,
    "arguments": di_settings(1280, 720),
    "inherited_settings": {
        "source": "Pinned UIData defaults and UNBIASED preset",
        "seed": "Upstream CLI has no global seed option",
        "output": "Upstream LDR BMP with tone mapping and default bloom; no HDR reference",
    },
}


def query(args, cwd=ROOT):
    return subprocess.check_output(args, cwd=cwd, text=True, encoding="utf-8", errors="replace").strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Optional complete JSON configuration replacing the built-in Cornell settings.")
    parser.add_argument("--interactive", action="store_true", help="Open the same settings; close the window to finish (no capture).")
    args = parser.parse_args()
    config_path = (ROOT / args.config).resolve() if args.config else None
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path else DEFAULT_CONFIG
    scene_config = json.loads((ROOT / config["scene_config"]).read_text(encoding="utf-8"))
    scene = next(s for s in json.loads((ROOT / "scenes/manifest.yaml").read_text(encoding="utf-8"))["scenes"] if s["id"] == scene_config["scene_id"])
    exe = RENDERER / "build/bin/FullSample.exe"
    if not exe.is_file():
        raise RuntimeError("Build FullSample first; see docs/setup.md.")
    commit = query(["git", "rev-parse", "HEAD"], RENDERER)
    if commit != config["renderer_commit"]:
        raise RuntimeError("RTXDI revision differs from the selected configuration.")
    for name, digest in scene["file_sha256"].items():
        if sha(ROOT / scene["local_path"] / name) != digest:
            raise RuntimeError(f"Scene file mismatch (or unresolved LFS pointer): {name}")
    asset_commit = query(["git", "rev-parse", "HEAD"], RENDERER / "Assets/Media")
    if asset_commit != scene["source_revision"]:
        raise RuntimeError("Asset revision differs from the registered scene.")
    upstream_status = query(["git", "status", "--porcelain", "--untracked-files=no"], RENDERER)
    if upstream_status:
        raise RuntimeError("This runner requires unchanged upstream source and submodule revisions.")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-cornell-" + ("interactive" if args.interactive else "capture")
    output = ROOT / "runs" / run_id
    output.mkdir(parents=True)
    settings = {**config["arguments"], **scene_config["arguments"]}
    image = output / "cornell.bmp"
    if not args.interactive:
        settings.update({"profiling.saveFrame": config["capture_frame"], "profiling.saveFile": str(image)})
    command = [str(exe)]
    for key, value in settings.items():
        command.extend(["--" + key, str(value)])
    resolved = {"launcher": config, "scene": scene_config, "arguments": settings}
    (output / "config.json").write_text(json.dumps(resolved, indent=2) + "\n", encoding="utf-8")
    (output / "command.txt").write_text(subprocess.list2cmdline(command) + "\n", encoding="utf-8")
    cache = RENDERER / "build/CMakeCache.txt"
    dependencies = query(["git", "submodule", "status", "--recursive"], RENDERER)
    record = {
        "run_id": run_id, "started_utc": datetime.now(timezone.utc).isoformat(),
        "kind": "interactive" if args.interactive else "official_code_capture",
        "status": "running", "command": command, "cwd": str(output),
        "project_commit": query(["git", "rev-parse", "HEAD"]),
        "project_status": query(["git", "status", "--porcelain", "--ignore-submodules=all"]),
        "renderer_commit": commit, "renderer_status": upstream_status,
        "dependencies": dependencies.splitlines(), "asset_commit": asset_commit,
        "dlss_commit": query(["git", "rev-parse", "HEAD"], RENDERER / "External/donut/thirdparty/DLSS"),
        "dxc": query([str(RENDERER / "External/dxc/bin/x64/dxc.exe"), "--version"]),
        "mathlib_source": "https://github.com/NVIDIA-RTX/MathLib/archive/refs/tags/v11.zip",
        "scene_sha256": scene["sha256"], "executable_sha256": sha(exe),
        "config_source": str(config_path) if config_path else "scripts/run/rtxdi.py defaults",
        "config_sha256": sha(config_path) if config_path else None, "runner_sha256": sha(Path(__file__)),
        "os": platform.platform(), "python": platform.python_version(),
        "gpu": query(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"]),
        "cmake": query(["cmake", "--version"]).splitlines()[0],
        "limitations": config["inherited_settings"],
        "artifacts": {"log": "renderer.log", "config": "config.json", "command": "command.txt"},
    }
    if cache.exists():
        (output / "CMakeCache.txt").write_bytes(cache.read_bytes())
        record["artifacts"]["build_cache"] = "CMakeCache.txt"
    manifest = output / "manifest.json"
    def save():
        manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    save()
    print(f"Run: {output}", flush=True)
    started = time.monotonic()
    try:
        with (output / "renderer.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(command, cwd=output, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=None if args.interactive else 120)
        record["exit_code"] = result.returncode
        if result.returncode:
            raise RuntimeError(f"Renderer exited with {result.returncode}; inspect renderer.log.")
        if not args.interactive:
            record["image"] = validate_bmp(image, (settings["rendering.width"], settings["rendering.height"]))
            if "Saved the screenshot" not in (output / "renderer.log").read_text(encoding="utf-8", errors="replace"):
                raise RuntimeError("Renderer did not confirm saving a screenshot.")
            record["artifacts"]["image"] = image.name
        record["status"] = "interactive_closed" if args.interactive else "capture_passed"
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
        print(str(exc), file=sys.stderr)
    finally:
        record["wall_seconds_including_startup"] = round(time.monotonic() - started, 3)
        record["ended_utc"] = datetime.now(timezone.utc).isoformat()
        save()
    print(f"{record['status']}: {manifest}")
    return int(record["status"] == "failed")


if __name__ == "__main__":
    sys.exit(main())
