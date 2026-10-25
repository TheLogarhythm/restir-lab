"""Build an isolated PDF-similarity experiment variant; restore upstream files/binaries."""
from datetime import datetime, timezone
import shutil
import subprocess
from pathlib import Path
import build_rtxdi_experiments as base
import rtxdi_pdf as pdf
from rtxdi_build import integration_hashes, checked_submodule, prepare_variant, build_variant

from rtxdi_emission import emission_support
from rtxdi_common import sha


def main():
    renderer, binary = base.RENDERER, base.BIN
    official = binary / "FullSample.exe"
    created = [base.DEST, *(renderer / name for name in pdf.CREATED)]
    prepare_variant(renderer, official, created)
    donut = checked_submodule(renderer, "External/donut", ["src/engine/GltfImporter.cpp"])
    runtime = checked_submodule(renderer, "Libraries/Rtxdi", ["Include/Rtxdi/DI/SpatialResampling.hlsli"])
    base.run("git", "apply", "--check", str(base.PATCH), cwd=renderer)
    files = list(dict.fromkeys([*base.FILES, *pdf.FILES, str(base.IMPORTER)]))
    sources = [base.PATCH, base.HELPER, base.SUPPORT_FILE, base.BUILD_SUPPORT_FILE,
               Path(base.__file__), Path(__file__), *pdf.SUPPORT]
    record = {"built_utc": datetime.now(timezone.utc).isoformat(), "donut": donut, "runtime": runtime,
              "renderer_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=renderer, text=True).strip(),
              "configuration": "Release", "pdf_similarity": True,
              "integration_sha256": integration_hashes(sources, base.ROOT),
              "compiler_cache_sha256": sha(base.BUILD / "CMakeCache.txt"),
              "shader_directory": "shaders/full-sample-pdf"}
    shaders = binary / "shaders/full-sample"
    variant = binary / "FullSamplePdf.exe"

    def adapt():
        shutil.copy2(base.HELPER, base.DEST)
        pdf.adapt(renderer, base.DEST)

    build_variant(renderer=renderer, build=base.BUILD, official=official, variant=variant,
        files=files, shader_dir=shaders, record=record, patch=base.PATCH, run=base.run,
        emission=emission_support(renderer / base.IMPORTER), adapt=adapt, created=created,
        shader_destination=binary / record["shader_directory"],
        validate_shaders=base.validate_experiment_shaders)
    print(f"Built {variant}; upstream files, official executable and shaders restored")


if __name__ == "__main__":
    main()
