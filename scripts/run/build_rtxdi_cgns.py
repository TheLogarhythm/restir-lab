"""Build isolated CGNS shaders/executable, restoring the official renderer."""
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import build_rtxdi_experiments as base
import rtxdi_cgns as cgns
from rtxdi_build import checked_submodule, prepare_variant, build_variant, integration_hashes
from rtxdi_emission import emission_support
from rtxdi_common import sha


def main():
    renderer, binary = base.RENDERER, base.BIN
    official = binary / "FullSample.exe"
    created = [base.DEST, *(renderer / name for name in cgns.CREATED)]
    prepare_variant(renderer, official, created)
    donut = checked_submodule(renderer, "External/donut", ["src/engine/GltfImporter.cpp"])
    runtime = checked_submodule(renderer, "Libraries/Rtxdi", ["Include/Rtxdi/DI/SpatialResampling.hlsli"])
    base.run("git", "apply", "--check", str(base.PATCH), cwd=renderer)
    files = list(dict.fromkeys([*base.FILES, *cgns.FILES, str(base.IMPORTER)]))
    support = [base.PATCH, base.HELPER, base.SUPPORT_FILE, base.BUILD_SUPPORT_FILE,
               Path(base.__file__), Path(__file__), *cgns.SUPPORT]
    record = {"built_utc": datetime.now(timezone.utc).isoformat(), "donut": donut, "runtime": runtime,
              "renderer_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=renderer, text=True).strip(),
              "configuration": "Release", "cgns": True, "cgns_author_reference": cgns.AUTHOR_COMMIT,
              "integration_sha256": integration_hashes(support, base.ROOT),
              "compiler_cache_sha256": sha(base.BUILD / "CMakeCache.txt"),
              "shader_directory": "shaders/full-sample-cgns"}

    def adapt():
        shutil.copy2(base.HELPER, base.DEST)
        cgns.adapt(renderer, base.DEST)

    variant = binary / "FullSampleCgns.exe"
    build_variant(renderer=renderer, build=base.BUILD, official=official, variant=variant,
        files=files, shader_dir=binary / "shaders/full-sample", record=record,
        patch=base.PATCH, run=base.run, emission=emission_support(renderer / base.IMPORTER),
        adapt=adapt, created=created, shader_destination=binary / record["shader_directory"],
        validate_shaders=base.validate_experiment_shaders)
    print(f"Built {variant}; official source, executable and shaders restored")


if __name__ == "__main__":
    main()
