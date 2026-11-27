"""Prepare the Bistro adapter DLLs and material shader overlay for a live runtime."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

from . import prepare_adapted_plugins as adapter
from .gltf_factor_shader_patch_v3 import patch_sources
from .process_utils import publish_directory
from .prepare_gltf_composite_runtime_v3 import FILES

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "renderers/falcor/upstream/build/lab-vs2022/bin/Release"
PLUGIN_OUTPUT = ROOT / "build/live-adapted-plugins"


def _inputs(release):
    cuda = Path(os.environ.get("CUDA_PATH", "C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.6"))
    dependencies = [release / "Falcor.dll", ROOT / "scripts/falcor/gltf-transform-importer/TransformDescriptor.h"]
    for name, path in adapter.PLUGINS:
        source = ROOT / path
        _, libs = adapter.response_text(name, source, PLUGIN_OUTPUT, ROOT, cuda)
        dependencies.extend([source, *libs])
    paths = sorted(set(dependencies))
    return {item.relative_to(ROOT).as_posix(): adapter.sha(item) for item in paths}


def build_plugins():
    """Build against the retained stock Release Falcor.lib and its matching headers."""
    if os.name != "nt":
        raise OSError("Building Falcor plugins requires the Windows x64 toolchain")
    inputs = _inputs(RELEASE)
    if PLUGIN_OUTPUT.is_dir():
        _validated_plugins(RELEASE)
        return PLUGIN_OUTPUT
    arch = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
    vswhere = arch / "Microsoft Visual Studio/Installer/vswhere.exe"
    studio = subprocess.check_output(
        [str(vswhere), "-latest", "-version", "[17.0,18.0)", "-products", "*",
         "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
         "-property", "installationPath"], text=True,
    ).strip()
    dev = Path(studio) / "Common7/Tools/VsDevCmd.bat"
    if not dev.is_file():
        raise FileNotFoundError("Visual Studio 2022 C++ tools are required")
    cuda = Path(os.environ.get("CUDA_PATH", "C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.6"))
    plugins = {}
    PLUGIN_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=PLUGIN_OUTPUT.parent, prefix="live-adapter-stage-") as tmp:
        stage = Path(tmp) / "plugins"
        for name, path in adapter.PLUGINS:
            source = ROOT / path
            folder = stage / name
            folder.mkdir(parents=True)
            flags, _ = adapter.response_text(name, source, folder, ROOT, cuda)
            (folder / "compile.rsp").write_text(flags, encoding="utf-8")
            (folder / "compile.bat").write_text(
                "@echo off\ncall " + adapter.quoted(dev) + " -arch=x64 -host_arch=x64 >nul\n"
                "if errorlevel 1 exit /b %errorlevel%\ncl /Bv @compile.rsp\nexit /b %errorlevel%\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["cmd.exe", "/d", "/c", "compile.bat"], cwd=folder, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            (folder / "compile.log").write_bytes(result.stdout)
            if result.returncode:
                raise RuntimeError(name + " compilation failed:\n" + result.stdout.decode(errors="replace")[-8000:])
            dll = folder / (name + ".dll")
            plugins[name] = adapter.sha(dll)
        receipt = {"inputs": inputs, "plugins": plugins, "falcor_dll": adapter.sha(RELEASE / "Falcor.dll")}
        (stage / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        publish_directory(stage, PLUGIN_OUTPUT)
    return PLUGIN_OUTPUT


def _validated_plugins(stock_release):
    receipt = json.loads((PLUGIN_OUTPUT / "receipt.json").read_text(encoding="utf-8"))
    if receipt["falcor_dll"] != adapter.sha(Path(stock_release) / "Falcor.dll"):
        raise ValueError("Bistro adapters were built against a different Falcor.dll")
    if receipt["inputs"] != _inputs(RELEASE):
        raise ValueError("Bistro plugin sources or link inputs differ from their build receipt")
    result = {}
    for name, _ in adapter.PLUGINS:
        dll = PLUGIN_OUTPUT / name / (name + ".dll")
        if adapter.sha(dll) != receipt["plugins"][name]:
            raise ValueError("Bistro adapter DLL changed: " + name)
        result["plugins/" + name + ".dll"] = dll
    return result


def bistro_overlay(stock_release, output):
    """Map stock runtime-relative destinations to verified DLLs and marked shader sources."""
    stock_release, output = Path(stock_release), Path(output)
    result = _validated_plugins(stock_release)
    src = {key: (stock_release / path).read_text(encoding="utf-8") for key, path in FILES.items()}
    patched = patch_sources(src)
    for key, path in FILES.items():
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(patched[key], encoding="utf-8", newline="\n")
        result[path] = target
    return result


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(build_plugins())
