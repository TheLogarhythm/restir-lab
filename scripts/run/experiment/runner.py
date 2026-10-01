"""Execute one resolved RTXDI experiment and preserve provenance, including failures."""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PureWindowsPath
import re
import platform
import subprocess
import time
from rtxdi_common import ROOT, RENDERER, sha
from .artifacts import save_json, finalize_outputs

EXE = RENDERER / "build/bin/FullSampleExperiments.exe"

def output_directory(name, root=ROOT):
    if name is None:
        name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-di-reuse"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name) or PureWindowsPath(name).is_reserved():
        raise ValueError("Output name must be 1–64 letters, digits, hyphens or underscores; no reserved device names")
    path = root / "runs" / name
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"Output already exists: runs/{name}; choose another name")
    return path


def query(*args, cwd=ROOT):
    return subprocess.check_output(args, cwd=cwd, text=True, encoding="utf-8", errors="replace").strip()


def relative_path(path, base):
    return Path(os.path.relpath(path, base)).as_posix()


def portable_message(text, output):
    # Third-party log/error messages may print resolved host paths.
    for path, replacement in ((output, "."), (ROOT, relative_path(ROOT, output))):
        text = text.replace(str(path), replacement).replace(path.as_posix(), replacement)
    return text

def preflight(definition, executable=None):
    executable = executable or EXE
    running = query("powershell", "-NoProfile", "-Command",
                    "Get-Process FullSample* -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id")
    if running.strip():
        raise RuntimeError("Close other FullSample runs before starting a controlled experiment")
    if not executable.is_file():
        raise RuntimeError("Run python scripts/run/build_rtxdi_experiments.py first")
    build = json.loads(executable.with_suffix(".build.json").read_text())
    if build.get("renderer_commit") != definition["renderer_commit"]:
        raise RuntimeError("Build renderer revision differs from the experiment; rebuild first")
    if sha(executable) != build["executable_sha256"]:
        raise RuntimeError("Experiment executable differs from its build record")
    for name, digest in build["integration_sha256"].items():
        if sha(ROOT / name) != digest:
            raise RuntimeError("Integration changed; rebuild the experiment executable")
    shader_dir = executable.parent / build.get("shader_directory", "shaders/full-sample")
    for name, digest in build["shader_sha256"].items():
        if sha(shader_dir / name) != digest:
            raise RuntimeError("Compiled shaders differ from the experiment build")
    if query("git", "rev-parse", "HEAD", cwd=RENDERER) != definition["renderer_commit"]:
        raise RuntimeError("Unexpected renderer revision")
    if query("git", "status", "--porcelain", "--untracked-files=no", cwd=RENDERER):
        raise RuntimeError("Renderer or dependencies have local changes")
    return build


def run_one(config, output, build, scene, timeout=600, *, executable=None, resume_rgb=None):
    executable = executable or EXE
    output.mkdir(parents=True, exist_ok=False)
    config = copy.deepcopy(config)
    manifest = output / "manifest.json"
    started = time.monotonic()
    record = {"status": "running", "stage": "preparing",
              "started_utc": datetime.now(timezone.utc).isoformat()}
    save_json(manifest, record)
    resume = None
    try:
        config["output"] = "."
        config["repository_root"] = relative_path(ROOT, output)
        resume = config.get("reference", {}).get("resume_image")
        if resume:
            from .images import read_pfm
            import numpy as np
            source = Path(resume).resolve()
            if sha(source) != config["reference"]["resume_image_sha256"]:
                raise ValueError("Reference resume image was modified")
            rgb = read_pfm(source) if resume_rgb is None else resume_rgb
            if rgb.shape != (config["height"], config["width"], 3):
                raise ValueError("Resume image dimensions differ")
            rgba = np.zeros((config["height"], config["width"], 4), dtype="<f4")
            rgba[..., :3] = rgb
            rgba.tofile(output / "resume.rgba32f")
            config["reference"]["resume_image"] = relative_path(source, output)
        save_json(output / "config.json", config)
        command = [relative_path(executable, output)]
        for key, value in config["arguments"].items():
            # cxxopts bool flags need '=0'; a separate '0' can leave the flag true.
            command.append(f"--{key}={value}")
        record.update({"status": "running", "kind": "conventional_reference_on_author_renderer" if config.get("reference") else "adapted_author_code", "command": command,
                  "project_commit": query("git", "rev-parse", "HEAD"),
                  "project_status": query("git", "status", "--porcelain", "--ignore-submodules=all"),
                  "build": build, "scene": scene, "cwd": ".",
                  "repository_root": config["repository_root"],
                  "path_bases": {"command": "run directory", "scene_source_and_code_paths": "repository root",
                                 "scene.file_sha256": "config.scene.source.root",
                                 "build.shader_sha256": (executable.parent / build.get("shader_directory", "shaders/full-sample")).relative_to(ROOT).as_posix()},
                  "environment": {"RTXDI_EXPERIMENT_CONFIG": "config.json"},
                  "run_id": output.relative_to(ROOT / "runs").as_posix() if output.is_relative_to(ROOT / "runs") else output.name,
                  "python_source_sha256": {p.relative_to(ROOT).as_posix(): sha(p)
                      for p in [ROOT / "scripts/run/rtxdi_reuse.py", ROOT / "scripts/run/rtxdi_common.py",
                                ROOT / "scripts/assets/gltf.py", *Path(__file__).parent.glob("*.py")]},
                  "config_sha256": sha(output / "config.json"),
                  "dependencies": query("git", "submodule", "status", "--recursive", cwd=RENDERER).splitlines(),
                  "os": platform.platform(), "python": platform.python_version(),
                  "gpu": query("nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"),
                  "timing": "Synchronous GPU frames; excludes capture/readback, PNG conversion, present and UI. Not real-time FPS."})
        record["stage"] = "rendering"
        save_json(manifest, record)
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("RTXDI_")}
        env["RTXDI_EXPERIMENT_CONFIG"] = "config.json"
        print(output, flush=True)
        with (output / "renderer.log").open("w", encoding="utf-8") as log:
            # Windows resolves the executable before applying cwd; only the launch
            # override is absolute. The saved command stays relative to the run.
            result = subprocess.run(command, executable=str(executable), cwd=output, env=env,
                                    stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        record["exit_code"] = result.returncode
        if result.returncode:
            raise RuntimeError(f"Renderer exited {result.returncode}; inspect renderer.log")
        record["stage"] = "finalizing"
        save_json(manifest, record)
        record["captures"] = finalize_outputs(output, config)
        record["status"] = "completed"
    except KeyboardInterrupt:
        record["status"] = "interrupted"
        raise
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = portable_message(str(exc), output)
        raise
    finally:
        log_path = output / "renderer.log"
        try:
            if log_path.exists():
                log_path.write_text(portable_message(log_path.read_text(encoding="utf-8", errors="replace"), output), encoding="utf-8")
        except OSError as exc:
            record["log_processing_error"] = portable_message(str(exc), output)
        record["ended_utc"] = datetime.now(timezone.utc).isoformat()
        record["wall_seconds_including_startup_and_export"] = time.monotonic() - started
        save_json(manifest, record)
        if resume and record["status"] == "completed":
            (output / "resume.rgba32f").unlink(missing_ok=True)
