"""Launch Blender from ordinary Python without importing bpy."""
from pathlib import Path
import re
import shutil
import subprocess


def find_blender(explicit):
    if explicit:
        path = Path(explicit).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Blender executable not found: {path}")
        return path
    found = shutil.which("blender")
    if found:
        return Path(found)
    versions = list(Path("C:/Program Files/Blender Foundation").glob("Blender */blender.exe"))
    if versions:
        return max(versions, key=lambda p: tuple(map(int, re.findall(r"\d+", p.parent.name))))
    raise FileNotFoundError("Blender not found; pass --blender PATH")


def export_scene(source, output, profile, *, blender=None, texture_size=512):
    executable = find_blender(blender)
    script = Path(__file__).with_name("blender_export.py")
    log_path = output.with_suffix(".blender.log")
    command = [str(executable), "--background", "--factory-startup", "--disable-autoexec",
               "--threads", "4", "--python-exit-code", "1", "--python", str(script),
               "--", profile, str(source), str(output), "--texture-size", str(texture_size)]
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode or not output.is_file():
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"Blender export failed (exit {result.returncode}):\n{tail}")
    return subprocess.check_output([str(executable), "--version"], text=True).splitlines()[0]
