"""Build the independent ordinary PT reference without replacing older references."""
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import build_rtxdi_experiments as base
import rtxdi_path_reference as path_reference
import rtxdi_transport
from rtxdi_build import checked_submodule, prepare_variant, build_variant, integration_hashes
from rtxdi_emission import emission_support
from rtxdi_common import sha


def main():
    renderer, binary = base.RENDERER, base.BIN
    official = binary / "FullSample.exe"
    created = [base.DEST, *(renderer / p for p in path_reference.CREATED)]
    prepare_variant(renderer, official, created)
    donut = checked_submodule(renderer, "External/donut", ["src/engine/GltfImporter.cpp"])
    runtime = checked_submodule(renderer, "Libraries/Rtxdi", [])
    base.run("git", "apply", "--check", str(base.PATCH), cwd=renderer)
    files = list(dict.fromkeys([*base.FILES, *base.REFERENCE_FILES, *path_reference.FILES, str(base.IMPORTER)]))
    support = [base.PATCH, base.HELPER, base.SUPPORT_FILE, base.BUILD_SUPPORT_FILE,
               Path(base.__file__), Path(__file__), Path(rtxdi_transport.__file__), *path_reference.SUPPORT]
    record = {"built_utc": datetime.now(timezone.utc).isoformat(), "donut": donut, "runtime": runtime,
              "renderer_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=renderer, text=True).strip(),
              "configuration": "Release", "path_reference_schema": 1,
              "integration_sha256": integration_hashes(support, base.ROOT),
              "compiler_cache_sha256": sha(base.BUILD / "CMakeCache.txt"),
              "shader_directory": "shaders/full-sample-path-reference",
              "estimator": "conventional_path_tracing", "accumulation": "FP32 running mean",
              "bsdf_pdf": "untrimmed-visible-GGX-D-G1V-over-4NoV; delta-discrete-mass",
              "segment_transmittance": "closest-opaque-or-cutout-hit-bounded; at-most-one-additional-trace",
              "validation_status": "requires PT target/sample/resume GPU conformance before formal use"}
    variant = binary / "FullSamplePathReference.exe"
    def validate(official, current):
        base.validate_experiment_shaders(official, current)
        base.validate_reference_shaders(official, current)
    build_variant(renderer=renderer, build=base.BUILD, official=official, variant=variant,
        files=files, shader_dir=binary / "shaders/full-sample", record=record,
        patch=base.PATCH, run=base.run, emission=emission_support(renderer / base.IMPORTER),
        adapt=path_reference.adapt, created=created, shader_destination=binary / record["shader_directory"],
        validate_shaders=validate)
    print(f"Built {variant}; official source, executable and shaders restored")


if __name__ == "__main__":
    main()
