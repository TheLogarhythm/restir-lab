"""Build Bistro adapter plugins in a fresh directory; never replace frozen binaries.

This reproduces the C++17 Release compile/link recipe of the retained v3 runtime.
New DLL hashes require a new qualified runtime/profile; they do not update locks.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PLUGINS = (
    ("GltfFactorMaterial", "scripts/falcor/gltf_factor_material.cpp"),
    (
        "LabGltfTransformImporter",
        "scripts/falcor/gltf-transform-importer/LabGltfTransformImporter.cpp",
    ),
)
DEFINES = (
    "WIN32",
    "_WINDOWS",
    "NDEBUG",
    "NOMINMAX",
    "UNICODE",
    "_USE_MATH_DEFINES",
    "_CRT_SECURE_NO_WARNINGS",
    "_SILENCE_ALL_MS_EXT_DEPRECATION_WARNINGS",
    "FALCOR_ENABLE_ASSERTS=0",
    "FALCOR_ENABLE_PROFILER=1",
    "FALCOR_HAS_D3D12=1",
    "FALCOR_HAS_VULKAN=1",
    "FALCOR_HAS_AFTERMATH=0",
    "FALCOR_HAS_NVAPI=1",
    "FALCOR_HAS_CUDA=1",
    "FALCOR_HAS_D3D12_AGILITY_SDK=1",
    "FALCOR_HAS_RTXDI=1",
)
INCLUDES = (
    "Source/Falcor",
    "external/fmt/include",
    "external/vulkan-headers/include",
    "external/imgui",
    "external/imgui_addons",
    "external/packman/nanovdb/include",
    "external/include",
    "external/packman/rtxdi/rtxdi-sdk/include",
    "external/pybind11/include",
    "external/packman/python/include",
    "external/packman/slang/include",
    "external/packman/deps/include",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quoted(path):
    value = str(Path(path).resolve())
    if any(c in value for c in ('"', "%", "\r", "\n")):
        raise ValueError("Unsupported toolchain path")
    return '"' + value + '"'


def response_text(name, source, output, root, cuda):
    upstream = root / "renderers/falcor/upstream"
    libraries = [
        upstream / "build/lab-vs2022/Source/Falcor/Release/Falcor.lib",
        upstream / "build/lab-vs2022/external/fmt/Release/fmt.lib",
        upstream / "external/packman/python/libs/python310.lib",
    ]
    if name == "GltfFactorMaterial":
        libraries.append(upstream / "external/packman/deps/lib/assimp-vc143-mt.lib")
    flags = ["/nologo", "/std:c++17", "/EHsc", "/MD", "/O2", "/LD"]
    flags += ["/D" + x for x in DEFINES]
    flags += ["/I" + quoted(upstream / x) for x in INCLUDES] + [
        "/I" + quoted(cuda / "include")
    ]
    flags += [
        "/Fo" + quoted(output / (name + ".obj")),
        quoted(source),
        "/link",
        "/OUT:" + quoted(output / (name + ".dll")),
        "/IMPLIB:" + quoted(output / (name + ".lib")),
    ]
    flags += [quoted(x) for x in libraries]
    return " ".join(flags) + "\n", libraries


def prepare(output, *, root=ROOT, cuda=None):
    root = Path(root).resolve(strict=True)
    output = Path(output).resolve()
    if not output.is_relative_to(root / "build") or output == root / "build":
        raise ValueError("Plugin output must be a fresh directory under build/")
    if output.exists():
        raise FileExistsError("Use a new plugin output directory: " + str(output))
    if os.name != "nt":
        raise RuntimeError("This recipe requires Windows and Visual Studio 2022")
    from . import build

    record = build.verify_build()
    vs = Path(record["visual_studio"]) / "Common7/Tools/VsDevCmd.bat"
    cuda = Path(
        cuda
        or os.environ.get(
            "CUDA_PATH", r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.6"
        )
    )
    required = [
        vs,
        cuda / "include/cuda.h",
        root / "scripts/falcor/gltf-transform-importer/TransformDescriptor.h",
    ]
    recipes = []
    for name, relative in PLUGINS:
        source = root / relative
        folder = output / name
        text, libraries = response_text(name, source, folder, root, cuda)
        required += [source, *libraries]
        recipes.append((name, source, folder, text))
    missing = [str(x) for x in required if not x.is_file()]
    if missing:
        raise FileNotFoundError("Missing plugin inputs: " + ", ".join(missing))
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema_version": 1,
        "kind": "falcor_adapted_plugin_build",
        "status": "building",
        "falcor_build_sha256": sha(root / "build/falcor/build.json"),
        "falcor_commit": record["commit"],
        "visual_studio": str(vs),
        "cuda": str(cuda),
        "input_sha256": {
            str(x.relative_to(root)) if x.is_relative_to(root) else str(x): sha(x)
            for x in sorted(set(required))
        },
        "plugins": {},
    }

    def save():
        (output / "receipt.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf8"
        )

    save()
    try:
        for name, source, folder, text in recipes:
            folder.mkdir()
            rsp = folder / "compile.rsp"
            rsp.write_text(text, encoding="utf8")
            batch = folder / "compile.bat"
            batch.write_text(
                "@echo off\ncall "
                + quoted(vs)
                + " -arch=x64 -host_arch=x64 >nul\n"
                + "if errorlevel 1 exit /b %errorlevel%\ncl /Bv @"
                + quoted(rsp)
                + "\nexit /b %errorlevel%\n",
                encoding="utf8",
            )
            log = folder / "compile.log"
            with log.open("w", encoding="utf8") as stream:
                subprocess.run(
                    ["cmd.exe", "/d", "/c", str(batch)],
                    cwd=folder,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            dll = folder / (name + ".dll")
            if not dll.is_file():
                raise RuntimeError("Compiler did not produce " + str(dll))
            receipt["plugins"][name] = {
                "path": dll.relative_to(root).as_posix(),
                "sha256": sha(dll),
                "response_sha256": sha(rsp),
                "log_sha256": sha(log),
            }
            save()
        if build.verify_build() != record:
            raise RuntimeError("Falcor build changed during plugin compilation")
        receipt["status"] = "completed"
        save()
    except BaseException as exc:
        receipt.update(status="failed", error=str(exc))
        save()
        raise
    return output / "receipt.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cuda", type=Path)
    args = parser.parse_args()
    print(prepare(args.output, cuda=args.cuda))


if __name__ == "__main__":
    main()
