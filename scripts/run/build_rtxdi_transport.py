"""Build isolated GI/PT comparison with recorded common fixes and CGNS controls."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import shutil
import subprocess
import build_rtxdi_experiments as base
import rtxdi_cgns as cgns
import rtxdi_transport as transport
import rtxdi_transport_fixes as fixes
from rtxdi_build import checked_submodule, prepare_variant, build_variant, integration_hashes
from rtxdi_emission import emission_support
from rtxdi_common import sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-spatial", action="store_true", help="Validation-only native spatial consumers with identical common transport fixes")
    args = parser.parse_args()
    renderer, binary = base.RENDERER, base.BIN
    official = binary / "FullSample.exe"
    created = [base.DEST, *(renderer / p for p in (*cgns.CREATED, *transport.CREATED, *fixes.CREATED)), *fixes.sdk_created(renderer)]
    prepare_variant(renderer, official, created)
    donut = checked_submodule(renderer, "External/donut", ["src/engine/GltfImporter.cpp"])
    runtime = checked_submodule(renderer, "Libraries/Rtxdi", ["Include/Rtxdi/GI/SpatialResampling.hlsli",
        "Include/Rtxdi/PT/SpatialResampling.hlsli", "Include/Rtxdi/PT/SpatialNeighborSelection.hlsli"])
    base.run("git", "apply", "--check", str(base.PATCH), cwd=renderer)
    files = list(dict.fromkeys([*base.FILES, *cgns.FILES, *transport.FILES, *fixes.FILES, str(base.IMPORTER)]))
    support = [base.PATCH, base.HELPER, base.SUPPORT_FILE, base.BUILD_SUPPORT_FILE,
               Path(base.__file__), Path(__file__), *cgns.SUPPORT, *transport.SUPPORT, *fixes.SUPPORT]
    record = {"built_utc": datetime.now(timezone.utc).isoformat(), "donut": donut, "runtime": runtime,
              "renderer_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=renderer, text=True).strip(),
              "configuration": "Release", "cgns": True, "transport_schema": 1,
              "native_spatial_control": args.native_spatial,
              "cgns_author_reference": cgns.AUTHOR_COMMIT,
              "integration_sha256": integration_hashes(support, base.ROOT),
              "compiler_cache_sha256": sha(base.BUILD / "CMakeCache.txt"),
              "shader_directory": "shaders/full-sample-transport" + ("-native" if args.native_spatial else ""),
              "common_fixes": ["GI final reservoir index", "GI delta output", "GI no radiance clamp", "shared legacy-DI glass",
                               "GI secondary delta endpoint", "GI one-sided emission", "PT discrete delta measure",
                               "PT sampled-lobe endpoint gating", "PT continuous NEE support and PDF",
                               "PT canonical indexed emission", "PT actual-hit triangle MIS", "preserve invalid HDR",
                               "PT colored path/replay/suffix visibility", "PT colored forward/inverse reconnection",
                               "GI joint diffuse/delta PDF and null M", "GI independent final MIS terms", "sticky finite diagnostics",
                               "visible-GGX PDF", "GI fixed lobe mixture", "PT continuous inverse footprint",
                               "PT shift-invariant sample-count MIS", "canonical continuous environment",
                               "positive environment proposal support", "closest-hit-bounded segment transmittance"],
              "validation_status": "requires CPU/native/GPU transport conformance before formal use"}

    def adapt():
        shutil.copy2(base.HELPER, base.DEST)
        transport.adapt(renderer, base.DEST)
        fixes.adapt(renderer)
        if args.native_spatial:
            shader_root = renderer / transport.SHADERS
            for algorithm in ("GI", "PT"):
                shutil.copyfile(shader_root / f"LabSdk/Rtxdi/{algorithm}/SpatialResampling.hlsli",
                                shader_root / f"LightingPasses/{algorithm}/CgnsSpatialResampling.hlsli")
            transport.edit(renderer / transport.SOURCE / "App/SceneRenderer.cpp",
                           '"shaders/full-sample-transport"', '"shaders/full-sample-transport-native"')
            transport.edit(base.DEST, "    const auto& t = config[\"transport_method\"];",
                           "    if (TransportCgnsEnabled()) throw std::runtime_error(\"Native-spatial control cannot enable CGNS\");\n    const auto& t = config[\"transport_method\"];")

    variant = binary / ("FullSampleTransportNative.exe" if args.native_spatial else "FullSampleTransport.exe")
    build_variant(renderer=renderer, build=base.BUILD, official=official, variant=variant,
        files=files, shader_dir=binary / "shaders/full-sample", record=record,
        patch=base.PATCH, run=base.run, emission=emission_support(renderer / base.IMPORTER),
        adapt=adapt, created=created, shader_destination=binary / record["shader_directory"],
        validate_shaders=base.validate_experiment_shaders)
    print(f"Built {variant}; official source, executable and shaders restored")


if __name__ == "__main__":
    main()
