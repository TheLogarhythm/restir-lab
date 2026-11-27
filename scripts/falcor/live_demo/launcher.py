"""Launch the same-window Falcor ReSTIR PT demo or exercise its actual menus."""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess

from .acceptance import acceptance_steps, validate_sequence, verify
from .graph import METHODS, MODES
from .scenes import ROOT, SCENE_NAMES, prepare_sky


def run_session(executable, output, config, environment=None):
    output.mkdir(parents=True, exist_ok=False)
    settings = output / "settings.json"
    settings.write_text(json.dumps(config, indent=2) + "\n", encoding="utf8")
    entry = output / "start.py"
    entry.write_text(
        "import faulthandler\n"
        "import sys\n"
        "faulthandler.enable()\n"
        "sys.dont_write_bytecode = True\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from scripts.falcor.live_demo.controller import start\n"
        f"live_session = start(m, {str(settings)!r})\n",
        encoding="utf8",
    )
    command = [str(executable), "--device-type", "d3d12", "--width", str(config["width"]),
               "--height", str(config["height"]), "--logfile", str(output / "mogwai.log"), "--script", str(entry)]
    with (output / "console.log").open("w", encoding="utf8") as console:
        process = subprocess.Popen(command, cwd=output, stdout=console, stderr=subprocess.STDOUT, env=environment)
        try:
            (output / "process.json").write_text(json.dumps({"pid": process.pid, "command": command}, indent=2), encoding="utf8")
            print(f"Mogwai PID {process.pid}, output {output}", flush=True)
            code = process.wait()
        except BaseException:
            if process.poll() is None:
                process.terminate()
                process.wait()
            raise
    exit_record = {"pid": process.pid, "return_code": code, "win32_code": f"0x{code & 0xffffffff:08x}"}
    (output / "process-exit.json").write_text(json.dumps(exit_record, indent=2) + "\n", encoding="utf8")
    error_path = output / "error.json"
    if code or error_path.exists():
        detail = error_path.read_text(encoding="utf8") if error_path.exists() else str(output / "mogwai.log")
        raise RuntimeError(f"Mogwai exit code {code}: {detail}")
    return process.pid


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m scripts.falcor.live_demo", description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True, help="Private live runtime containing Mogwai.exe")
    parser.add_argument("--output", type=Path, help="Fresh output directory (default under runs/)")
    parser.add_argument("--scene", choices=SCENE_NAMES, help="Optional startup scene; otherwise show the scene selector")
    parser.add_argument("--method", choices=METHODS, help="Startup spatial method (default CGNS)")
    parser.add_argument("--mode", choices=MODES, help="Startup display mode (default Raw)")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--acceptance", choices=("classroom", "all"))
    group.add_argument("--sequence", type=Path, help="Custom JSON array of Scene/Method/Display/label/frames steps")
    group.add_argument("--precompile-shaders", action="store_true", help="Warm the live renderer's Slang cache")
    args = parser.parse_args(argv)
    if min(args.width, args.height) < 64:
        parser.error("Resolution must be at least 64 pixels on each axis")
    if os.environ.get("FALCOR_DEVMODE"):
        parser.error("Unset FALCOR_DEVMODE so the private runtime loads its own shaders")
    if args.precompile_shaders and (args.method or args.mode):
        parser.error("Shader precompilation exercises all methods and display modes")
    executable = (args.runtime / "Mogwai.exe").resolve(strict=True)
    rows = acceptance_steps(args.acceptance) if args.acceptance else None
    if args.sequence:
        rows = json.loads(args.sequence.read_text(encoding="utf8"))
    if args.precompile_shaders:
        from . import precompile

        rows = precompile.precompile_steps(args.scene)
        cache_directory = precompile.cache_directory(executable.parent)
    if rows is not None:
        validate_sequence(rows)
        import PIL  # Fail before launching Mogwai if image validation is unavailable.
    # Interactive users can select San Miguel later from the native panel.
    if rows is None or args.scene == "San Miguel" or any(row["Scene"] == "San Miguel" for row in rows):
        prepare_sky()
    output = (args.output or ROOT / "runs" / ("live-session-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))).resolve()
    config = {"root": str(ROOT), "runtime": str(executable.parent), "width": args.width, "height": args.height,
              "scene": args.scene or (rows[0]["Scene"] if rows else None),
              "method": args.method or (rows[0]["Method"] if rows else "CGNS"),
              "mode": args.mode or (rows[0]["Display"] if rows else "Raw"),
              "suite": args.acceptance, "sequence": rows, "precompile_shaders": args.precompile_shaders}
    if args.precompile_shaders:
        from functools import partial

        scenes = ", ".join(dict.fromkeys(row["Scene"] for row in rows))
        print(f"Precompiling shaders for {scenes} at {args.width}x{args.height}", flush=True)
        print(f"Slang cache directory: {cache_directory}", flush=True)
        precompile.warm(output, config, cache_directory, partial(run_session, executable))
    else:
        pid = run_session(executable, output, config)
        if rows is not None:
            verify(output, config, pid)
    return 0
