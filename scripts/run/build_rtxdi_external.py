"""Build the external-scene viewer and restore official sources, binary and shaders."""
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from rtxdi_common import ROOT, RENDERER, sha
from rtxdi_emission import emission_support, SUPPORT_FILE, IMPORTER
from rtxdi_build import (SUPPORT_FILE as BUILD_SUPPORT_FILE, integration_hashes, checked_submodule,
                         prepare_variant, build_variant)


SOURCE = RENDERER / "Samples/FullSample/Source/App/SceneRenderer.cpp"
BUILD = RENDERER / "build"
BIN = BUILD / "bin"
PATCH = Path(__file__).with_name("rtxdi_external.patch")


def run(*args, cwd=ROOT):
    subprocess.run(args, cwd=cwd, check=True)


def main():
    official = BIN / "FullSample.exe"
    prepare_variant(RENDERER, official)
    files = [str(SOURCE.relative_to(RENDERER))]
    donut = checked_submodule(RENDERER, "External/donut", ["src/engine/GltfImporter.cpp"])
    files.append(str(IMPORTER))
    run("git", "apply", "--check", str(PATCH), cwd=RENDERER)
    variant = BIN / "FullSampleExternal.exe"
    shader_dir = BIN / "shaders/full-sample"
    record = {"built_utc": datetime.now(timezone.utc).isoformat(), "donut": donut,
              "renderer_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=RENDERER, text=True).strip(),
              "integration_sha256": integration_hashes([PATCH, SUPPORT_FILE, BUILD_SUPPORT_FILE, Path(__file__)], ROOT),
              "configuration": "Release", "shader_directory": "shaders/full-sample"}
    build_variant(renderer=RENDERER, build=BUILD, official=official, variant=variant,
        files=files, shader_dir=shader_dir, record=record, patch=PATCH, run=run,
        emission=emission_support(RENDERER / IMPORTER), prefix="external-build-")
    print(f"Built {variant}; official sources, executable and shaders restored")


if __name__ == "__main__":
    main()
