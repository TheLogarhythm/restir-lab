"""Prepare or locate a private Falcor 9.0 live-demo runtime; original renderer files are read-only."""
import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .live_demo.native import display as display_overlay
from .live_demo.native import render_passes as overlay
from . import prepare_adapted_plugins as compiler
from .process_utils import exclusive_operation, publish_directory
from .runtime_common import is_transient_runtime_file, safe_name, sha256_file as sha

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build"
UPSTREAM = ROOT / "renderers/falcor/upstream"
RELEASE = UPSTREAM / "build/lab-vs2022/bin/Release"
CONFIG = ROOT / "experiments/configs/falcor-pt-spatial-comparison/restir-pt-spatial-comparison.json"
PLUGIN = "plugins/PathTracer.dll"
NRD_PLUGIN = "plugins/NRDPass.dll"
CORE_DLL = "Falcor.dll"
MOGWAI_EXE = "Mogwai.exe"
NRD_OVERLAY_REVISION = 2
PATH_TRACER_OUTPUT_REVISION = 1
NATIVE_PANEL_OVERLAY_REVISION = 4
LIVE_DISPLAY_OVERLAY_REVISION = 2
SLANG_DISK_CACHE_REVISION = 4
DISPLAY_PLUGINS = tuple(f"plugins/{name}.dll" for name in display_overlay.DISPLAY_PASSES)
ADDONS = ("GltfFactorMaterial", "LabGltfTransformImporter")
POINTER = BUILD / "falcor-live-demo.json"
LOCK = BUILD / ".falcor-live-demo.lock"


class OutdatedRuntimeError(ValueError):
    """The deployed runtime predates the current native overlays."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(values):
    return digest(json.dumps(values, sort_keys=True, separators=(",", ":")).encode())


def build_record():
    records = (
        BUILD / "falcor/build.json",
        ROOT / "runs/provenance/render-environment-records-20261120/falcor/build.json",
    )
    path = next((p for p in records if p.is_file()), None)
    if path is None:
        raise FileNotFoundError("Falcor Release build record missing; run the Falcor setup first.")
    record = json.loads(path.read_text(encoding="utf8"))
    pin = json.loads((ROOT / "renderers/falcor/integration.json").read_text(encoding="utf8"))
    if record["commit"] != pin["commit"] or record["configuration"] != "Release":
        raise ValueError("Falcor build record does not match the pinned Release")
    for name in ("Mogwai.exe", "Falcor.dll"):
        binary = RELEASE / name
        if record["files"].get(binary.relative_to(ROOT).as_posix()) != sha(binary):
            raise ValueError("Falcor Release binary differs from its build receipt: " + name)
    return record


def compile_plugin(folder, hosts, record):
    module = folder / "ReSTIRPathTracing"
    module.mkdir()
    for name, source in hosts.items():
        target = folder / name if name == "PathTracer.cpp" else module / name
        target.write_text(source, encoding="utf8")
    base = UPSTREAM / "build/lab-vs2022"
    cuda = Path(os.environ.get("CUDA_PATH", "C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.6"))
    vs = Path(record["visual_studio"]) / "Common7/Tools/VsDevCmd.bat"
    includes = [folder, UPSTREAM / "Source/RenderPasses/PathTracer", UPSTREAM / "Source/Modules/ReSTIRPathTracing",
                UPSTREAM / "Source/Modules", *(UPSTREAM / p for p in compiler.INCLUDES), cuda / "include"]
    libraries = [base / "Source/Falcor/Release/Falcor.lib", base / "external/fmt/Release/fmt.lib",
                 base / "Source/Modules/LightTileResampling/Release/LightTileResampling.lib",
                 UPSTREAM / "external/packman/python/libs/python310.lib",
                 *(UPSTREAM / "external/packman/slang/lib" / p for p in ("slang.lib", "gfx.lib")),
                 *(cuda / "lib/x64" / p for p in ("cuda.lib", "cudart_static.lib"))]
    for path in (vs, *libraries):
        if not path.is_file():
            raise FileNotFoundError("Install the pinned Falcor SDK/Packman development inputs: " + str(path))
    flags = ["/nologo", "/std:c++17", "/EHsc", "/MD", "/O2", "/LD", "/fp:precise",
             "/D_SCL_SECURE_NO_WARNINGS", "/D_SILENCE_CXX17_CODECVT_HEADER_DEPRECATION_WARNING",
             *("/D" + key for key in compiler.DEFINES), *("/I" + compiler.quoted(p) for p in includes),
             "PathTracer.cpp", "ReSTIRPathTracing/ReSTIRPathTracing.cpp", "/link", "/OUT:PathTracer.dll",
             "/INCREMENTAL:NO", "/Brepro", *(compiler.quoted(p) for p in libraries)]
    (folder / "compile.rsp").write_text(" ".join(flags) + "\n", encoding="utf8")
    (folder / "compile.bat").write_text(
        "@echo off\ncall " + compiler.quoted(vs) + " -arch=x64 -host_arch=x64 >nul\nif errorlevel 1 exit /b %errorlevel%\n"
        "cl @compile.rsp\nexit /b %errorlevel%\n", encoding="utf8")
    with (folder / "compile.log").open("w") as log:
        result = subprocess.run(["cmd.exe", "/d", "/c", "compile.bat"], cwd=folder, stdout=log,
                                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError((folder / "compile.log").read_text(errors="replace")[-6500:])
    return {p.name: sha(p) for p in libraries}


def compile_nrd_plugin(folder, hosts, record):
    for name, source in hosts.items():
        (folder / name).write_text(source, encoding="utf8")
    base = UPSTREAM / "build/lab-vs2022"
    sdk = UPSTREAM / "external/packman/nrd"
    cuda = Path(os.environ.get("CUDA_PATH", "C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.6"))
    vs = Path(record["visual_studio"]) / "Common7/Tools/VsDevCmd.bat"
    includes = [*(UPSTREAM / p for p in compiler.INCLUDES), sdk / "Include", cuda / "include"]
    libraries = [base / "Source/Falcor/Release/Falcor.lib", base / "external/fmt/Release/fmt.lib",
                 sdk / "Lib/Release/NRD.lib", UPSTREAM / "external/packman/python/libs/python310.lib",
                 *(UPSTREAM / "external/packman/slang/lib" / p for p in ("slang.lib", "gfx.lib")),
                 *(cuda / "lib/x64" / p for p in ("cuda.lib", "cudart_static.lib"))]
    for path in (vs, *libraries):
        if not path.is_file():
            raise FileNotFoundError("Install the pinned Falcor SDK/Packman development inputs: " + str(path))
    flags = ["/nologo", "/std:c++17", "/EHsc", "/MD", "/O2", "/LD", "/fp:precise",
             "/D_SCL_SECURE_NO_WARNINGS", "/D_SILENCE_CXX17_CODECVT_HEADER_DEPRECATION_WARNING",
             *("/D" + key for key in compiler.DEFINES), *("/I" + compiler.quoted(p) for p in includes),
             "NRDPass.cpp", "/link", "/OUT:NRDPass.dll", "/INCREMENTAL:NO", "/Brepro",
             *(compiler.quoted(p) for p in libraries)]
    (folder / "compile.rsp").write_text(" ".join(flags) + "\n", encoding="utf8")
    (folder / "compile.bat").write_text(
        "@echo off\ncall " + compiler.quoted(vs) + " -arch=x64 -host_arch=x64 >nul\nif errorlevel 1 exit /b %errorlevel%\n"
        "cl @compile.rsp\nexit /b %errorlevel%\n", encoding="utf8")
    with (folder / "compile.log").open("w") as log:
        result = subprocess.run(["cmd.exe", "/d", "/c", "compile.bat"], cwd=folder, stdout=log,
                                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError((folder / "compile.log").read_text(errors="replace")[-6500:])
    return {p.name: sha(p) for p in libraries}


def display_build_recipe(pass_name):
    source = UPSTREAM / "Source/RenderPasses" / pass_name / (pass_name + ".cpp")
    project = UPSTREAM / "build/lab-vs2022/Source/RenderPasses" / pass_name
    tlog = project / f"{pass_name}.dir/Release/{pass_name}.tlog"
    return source, project, tlog


def compile_display_plugin(folder, hosts, record):
    from .live_core_runtime import compile_command, link_command, quoted

    for name, source in hosts.items():
        (folder / name).write_text(source, encoding="utf8")
    pass_name = next(Path(name).stem for name in hosts if name.endswith(".cpp"))
    source, project, tlog = display_build_recipe(pass_name)
    cl = folder / "compile.rsp"
    cl.write_text(compile_command(folder, source, tlog, precompiled=False) + "\n", encoding="utf8")
    link = folder / "link.rsp"
    link.write_text(link_command(folder, pass_name + ".dll", tlog, (pass_name + ".obj",)) + "\n", encoding="utf8")
    vs = Path(record["visual_studio"]) / "Common7/Tools/VsDevCmd.bat"
    batch = folder / "compile.bat"
    batch.write_text("\n".join((
        "@echo off",
        f"call {quoted(vs)} -arch=x64 -host_arch=x64 >nul",
        "if errorlevel 1 exit /b %errorlevel%",
        f"cd /d {quoted(project)}",
        f"cl @{quoted(cl)}",
        "if errorlevel 1 exit /b %errorlevel%",
        f"link @{quoted(link)}",
        "exit /b %errorlevel%",
        "",
    )), encoding="utf8")
    log = folder / "compile.log"
    with log.open("w") as handle:
        result = subprocess.run(["cmd.exe", "/d", "/c", batch.name], cwd=folder, stdout=handle,
                                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(log.read_text(encoding="utf8", errors="replace")[-6500:])
    return {"Falcor.lib": sha(project.parents[1] / "Falcor/Release/Falcor.lib")}


def native_display_plugins(record):
    from . import live_core_runtime

    replacements = {}
    for pass_name, plugin in zip(display_overlay.DISPLAY_PASSES, DISPLAY_PLUGINS):
        _, project, tlog = display_build_recipe(pass_name)
        recipe_hashes = {
            "compile": sha(tlog / "CL.command.1.tlog"),
            "link": sha(tlog / "link.command.1.tlog"),
            "build_helpers": sha(Path(live_core_runtime.__file__)),
            "Falcor.lib": sha(project.parents[1] / "Falcor/Release/Falcor.lib"),
        }
        replacements[plugin] = cached_native_plugin(
            Path(plugin).name, display_overlay.display_sources(UPSTREAM, pass_name),
            compile_display_plugin, record, recipe_hashes,
        )
    return replacements


def cached_native_plugin(filename, hosts, build, record, sdk_hashes=None):
    identity = {"hosts": {n: digest(v.encode()) for n, v in hosts.items()}, "falcor": record["commit"],
                "compiler_recipe": digest(inspect.getsource(build).encode()), "compiler_flags": sha(Path(compiler.__file__))}
    if sdk_hashes is not None:
        identity["sdk_hashes"] = sdk_hashes
    dest = BUILD / ("falcor-live-native-" + fingerprint(identity)[:16])
    if not dest.exists():
        with tempfile.TemporaryDirectory(dir=BUILD, prefix="live-native-") as tmp:
            stage = Path(tmp) / "host"
            stage.mkdir()
            libs = build(stage, hosts, record)
            receipt = {"inputs": identity, "libraries": libs, "dll": sha(stage / filename)}
            (stage / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf8")
            publish_directory(stage, dest)
    receipt = json.loads((dest / "receipt.json").read_text(encoding="utf8"))
    binary = dest / filename
    if receipt["inputs"] != identity or sha(binary) != receipt["dll"]:
        raise ValueError("Private live plugin failed integrity verification: " + filename)
    return binary


def native_plugin(record=None):
    return cached_native_plugin("PathTracer.dll", overlay.host_sources(UPSTREAM), compile_plugin, record or build_record())


def native_nrd_plugin(record):
    sdk = UPSTREAM / "external/packman/nrd"
    sdk_inputs = ("Include/NRD.h", "Include/NRDDescs.h", "Include/NRDSettings.h", "Lib/Release/NRD.lib")
    return cached_native_plugin("NRDPass.dll", overlay.nrd_host_sources(UPSTREAM), compile_nrd_plugin, record,
                                {name: sha(sdk / name) for name in sdk_inputs})


def verify(package, *, full=True):
    if package.parent != BUILD or not package.name.startswith("falcor-live-demo-"):
        raise ValueError("Invalid live package path")
    receipt = json.loads((package / "receipt.json").read_text(encoding="utf8"))
    if receipt["kind"] != "falcor-live-pt-v1" or fingerprint(receipt["inputs"])[:16] != package.name.rsplit("-", 1)[1]:
        raise ValueError("Live package receipt differs from its directory")
    inputs = receipt["inputs"]
    replacements = inputs["replacement_hashes"]
    if inputs.get("nrd_overlay_revision") != NRD_OVERLAY_REVISION or NRD_PLUGIN not in replacements:
        raise OutdatedRuntimeError("The deployed live runtime needs the current native NRD history reset and resource reuse")
    if CORE_DLL not in replacements:
        raise OutdatedRuntimeError("The deployed live runtime needs the private Falcor core overlay")
    if MOGWAI_EXE not in replacements:
        raise OutdatedRuntimeError("The deployed live runtime needs the private Mogwai device rotation")
    if inputs.get("native_panel_overlay_revision") != NATIVE_PANEL_OVERLAY_REVISION:
        raise OutdatedRuntimeError("The deployed live runtime needs the native Mogwai Graphs panel")
    if (inputs.get("live_display_overlay_revision") != LIVE_DISPLAY_OVERLAY_REVISION
            or any(name not in replacements for name in DISPLAY_PLUGINS)):
        raise OutdatedRuntimeError("The deployed live runtime needs the live Raw and Accumulation display passes")
    if inputs.get("path_tracer_output_revision") != PATH_TRACER_OUTPUT_REVISION or PLUGIN not in replacements:
        raise OutdatedRuntimeError("The deployed live runtime needs the shared PathTracer output wiring")
    if inputs.get("slang_disk_cache_revision") != SLANG_DISK_CACHE_REVISION:
        raise OutdatedRuntimeError("The deployed live runtime needs persistent Slang module support")
    runtime = package / "runtime"
    if full:
        names = receipt["files"]
    else:
        # On each interactive launch check the method/scene files and essential binaries.
        # Preparation and --verify check every shipped dependency, including all 4k+ stock files.
        names = set(inputs["shader_hashes"]) | set(replacements)
    for name in names:
        if sha(runtime / safe_name(name)) != receipt["files"][name]:
            raise ValueError("Live runtime file changed: " + name)
    return runtime


def locate(*, full=False):
    if not POINTER.is_file():
        raise FileNotFoundError("No deployed demo yet. Run python -B -m scripts.falcor.live_runtime --prepare.")
    active = json.loads(POINTER.read_text(encoding="utf8"))
    package = BUILD / safe_name(active["package"])
    if sha(package / "receipt.json") != active["receipt_sha256"]:
        raise ValueError("Active live runtime receipt changed")
    return verify(package, full=full)


def is_generated_runtime_file(name):
    return (is_transient_runtime_file(name) or name.startswith((".slangcache/", ".slangcache-stage-"))
            or name == ".slangcache.precompile.lock" or "__pycache__" in Path(name).parts or name.endswith(".pyc"))


def prepare():
    from .live_core_runtime import build_core
    from .live_scenes_runtime import bistro_overlay, build_plugins

    with exclusive_operation(LOCK):
        build_plugins()
        record = build_record()
        native = native_plugin(record)
        nrd = native_nrd_plugin(record)
        display = native_display_plugins(record)
        core = build_core(record)
        settings = json.loads(CONFIG.read_text(encoding="utf8"))["methods"]
        shaders = overlay.shader_sources(RELEASE, settings)
        with tempfile.TemporaryDirectory(dir=BUILD, prefix="live-package-") as temp:
            stage = Path(temp)
            addons = bistro_overlay(RELEASE, stage / "materials")
            manifest = "plugins/plugins.json"
            plugin_names = json.loads((RELEASE / manifest).read_text(encoding="utf8"))
            if any(n in plugin_names for n in ADDONS):
                raise ValueError("Expected the original Falcor plugin manifest")
            shaders[manifest] = json.dumps([*plugin_names, *ADDONS], indent=2) + "\n"
            replacements = {**addons, **display, PLUGIN: native, NRD_PLUGIN: nrd,
                            CORE_DLL: core, MOGWAI_EXE: core.with_name(MOGWAI_EXE)}
            if shaders.keys() & replacements.keys():
                raise ValueError("Live runtime overlays overlap")
            inputs = {"configuration": sha(CONFIG), "falcor": record["commit"],
                      "nrd_overlay_revision": NRD_OVERLAY_REVISION,
                      "path_tracer_output_revision": PATH_TRACER_OUTPUT_REVISION,
                      "native_panel_overlay_revision": NATIVE_PANEL_OVERLAY_REVISION,
                      "live_display_overlay_revision": LIVE_DISPLAY_OVERLAY_REVISION,
                      "slang_disk_cache_revision": SLANG_DISK_CACHE_REVISION,
                      "replacement_hashes": {n: sha(p) for n, p in replacements.items()},
                      "shader_hashes": {n: digest(s.encode()) for n, s in shaders.items()}}
            source_files = {}
            for path in RELEASE.rglob("*"):
                if not path.is_file():
                    continue
                name = path.relative_to(RELEASE).as_posix()
                if is_generated_runtime_file(name) or name in replacements or name in shaders:
                    continue
                source_files[name] = path
            base_hashes = {n: sha(p) for n, p in source_files.items()}
            inputs["base_inventory"] = fingerprint(base_hashes)
            dest = BUILD / ("falcor-live-demo-" + fingerprint(inputs)[:16])
            if not (dest / "receipt.json").is_file():
                # Windows AV may hold an open handle on a newly copied DLL and deny
                # renaming a populated directory. Publish the receipt atomically last;
                # a retry of this immutable fingerprint can finish interrupted copies.
                runtime = dest / "runtime"
                for name, source in {**source_files, **replacements}.items():
                    target = runtime / safe_name(name)
                    target.parent.mkdir(exist_ok=True, parents=True)
                    shutil.copyfile(source, target)
                for name, data in shaders.items():
                    target = runtime / safe_name(name)
                    target.parent.mkdir(exist_ok=True, parents=True)
                    target.write_bytes(data.encode())
                (runtime / ".shadercache").mkdir(exist_ok=True)
                hashes = {**base_hashes, **inputs["replacement_hashes"], **inputs["shader_hashes"]}
                staged_receipt = stage / "receipt.json"
                staged_receipt.write_text(json.dumps(
                    {"kind": "falcor-live-pt-v1", "inputs": inputs, "files": hashes}, indent=2), encoding="utf8")
                os.replace(staged_receipt, dest / "receipt.json")
            runtime = verify(dest)
            pointer = stage / "active.json"
            pointer.write_text(json.dumps({"package": dest.name, "receipt_sha256": sha(dest / "receipt.json")}), encoding="utf8")
            os.replace(pointer, POINTER)
    return runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument("--prepare", action="store_true", help="Compile and deploy the three-method private runtime.")
    options.add_argument("--locate", action="store_true", help="Verify essential binaries and overlays, then print the deployed runtime.")
    options.add_argument("--verify", action="store_true", help="Hash every file in the deployed runtime receipt.")
    options.add_argument("--compile-plugin", action="store_true", help="Build the private PathTracer plugin only.")
    args = parser.parse_args()
    if args.prepare:
        print(prepare())
    elif args.locate:
        try:
            runtime = locate()
        except OutdatedRuntimeError as error:
            print(f"{error}. Preparing the updated live runtime.", file=sys.stderr)
            runtime = prepare()
        print(runtime)
    elif args.verify:
        print(locate(full=True))
    else:
        with exclusive_operation(LOCK):
            print(native_plugin())


if __name__ == "__main__":
    main()
