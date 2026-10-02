"""Build the external-scene viewer and restore official sources, binary and shaders."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from rtxdi_common import ROOT, RENDERER, sha
from rtxdi_emission import emission_support, SUPPORT_FILE, IMPORTER
from rtxdi_build import (SUPPORT_FILE as BUILD_SUPPORT_FILE, backup_renderer, integration_hashes, checked_submodule,
                         restore_renderer, tree_hashes, remove_backup, invalidate_cpp, require_clean_renderer)

SOURCE = RENDERER / "Samples/FullSample/Source/App/SceneRenderer.cpp"
BUILD = RENDERER / "build"
BIN = BUILD / "bin"
PATCH = Path(__file__).with_name("rtxdi_external.patch")


def run(*args, cwd=ROOT):
    subprocess.run(args, cwd=cwd, check=True)


def main():
    official = BIN / "FullSample.exe"
    if not official.is_file():
        raise RuntimeError("Build official FullSample first; see docs/setup.md")
    running = subprocess.check_output(["powershell", "-NoProfile", "-Command",
        "Get-Process FullSample* -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"], text=True)
    if running.strip():
        raise RuntimeError("Close FullSample before building the viewer")
    files = [str(SOURCE.relative_to(RENDERER))]
    require_clean_renderer(RENDERER)
    donut = checked_submodule(RENDERER, "External/donut", ["src/engine/GltfImporter.cpp"])
    files.append(str(IMPORTER))
    run("git", "apply", "--check", str(PATCH), cwd=RENDERER)
    variant = BIN / "FullSampleExternal.exe"
    shader_dir = BIN / "shaders/full-sample"
    original_shaders = tree_hashes(shader_dir)
    record = {"built_utc": datetime.now(timezone.utc).isoformat(), "donut": donut,
              "renderer_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=RENDERER, text=True).strip(),
              "integration_sha256": integration_hashes([PATCH, SUPPORT_FILE, BUILD_SUPPORT_FILE, Path(__file__)], ROOT),
              "configuration": "Release", "shader_directory": "shaders/full-sample",
              "shader_sha256": original_shaders}
    backup = Path(tempfile.mkdtemp(prefix="external-build-", dir=BUILD))
    restored = False
    try:
        backup_renderer(backup, RENDERER, files, official, shader_dir)
        try:
            run("git", "apply", str(PATCH), cwd=RENDERER)
            invalidate_cpp(RENDERER)
            with emission_support(RENDERER / IMPORTER):
                run("cmake", "--build", str(BUILD), "--config", "Release", "--target", "FullSample", "--parallel", "4")
            if tree_hashes(shader_dir) != original_shaders:
                raise RuntimeError("Unexpected viewer shader changes; variant was not published")
            shutil.copy2(official, backup / variant.name)
            record["executable_sha256"] = sha(backup / variant.name)
        finally:
            restore_renderer(backup, RENDERER, files, official, shader_dir)
            restored = True
        shutil.copy2(backup / variant.name, variant)
    finally:
        if restored:
            remove_backup(backup, BUILD, "external-build-")
        else:
            print(f"Recovery backup retained: {backup}")
    variant.with_suffix(".build.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"Built {variant}; official sources, executable and shaders restored")


if __name__ == "__main__":
    main()
