"""Complete shared-lighting provenance for offline reference fixtures."""


def lighting_build():
    return {"renderer_commit": "fixture-renderer", "executable_sha256": "fixture-exe",
            "shader_sha256": {"shader": "fixture-shader"},
            "donut": {"commit": "fixture-donut", "source_sha256": {
                "src/engine/GltfImporter.cpp": "fixture-importer"}},
            "integration_sha256": {
                "scripts/run/build_rtxdi_experiments.py": "fixture-builder",
                "scripts/run/rtxdi_experiments.patch": "fixture-patch",
                "scripts/run/rtxdi_experiments/LabExperiment.h": "fixture-helper",
                "scripts/run/rtxdi_emission.py": "fixture-emission"}}
