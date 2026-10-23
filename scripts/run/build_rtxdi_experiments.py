"""Build the isolated experiment executable, restoring pinned source and official binary."""
from datetime import datetime, timezone
import argparse
from pathlib import Path
import shutil
import subprocess
from rtxdi_common import ROOT, RENDERER, sha
from rtxdi_emission import emission_support, SUPPORT_FILE, IMPORTER
from rtxdi_build import (SUPPORT_FILE as BUILD_SUPPORT_FILE, integration_hashes, checked_submodule,
                         prepare_variant, build_variant, tree_hashes)


HERE = Path(__file__).resolve().parent
BUILD = RENDERER / "build"
BIN = BUILD / "bin"
PATCH = HERE / "rtxdi_experiments.patch"
HELPER = HERE / "rtxdi_experiments/LabExperiment.h"
FILES = ["Samples/FullSample/Source/App/SceneRenderer.cpp", "Samples/FullSample/Source/Profiler.h",
         "Samples/FullSample/Source/App/SceneRenderer.h", "Samples/FullSample/Source/main.cpp",
         "Samples/FullSample/Source/App/CommandLineArgs.cpp",
         "Samples/FullSample/Source/RenderPasses/PrepareLightsPass.cpp",
         "Samples/FullSample/Source/RenderPasses/PrepareLightsPass.h"]
DEST = RENDERER / "Samples/FullSample/Source/App/LabExperiment.h"
REFERENCE_SHADER = HERE / "rtxdi_experiments/ReferenceSamples.hlsl"
REFERENCE_FILES = ["Samples/FullSample/Source/RenderTargets.cpp",
                   "Samples/FullSample/Source/RenderPasses/LightingPasses/ReSTIRDIRenderPasses.cpp",
                   "Samples/FullSample/Source/RenderPasses/LightingPasses/LightingPasses.cpp",
                   "Samples/FullSample/Shaders/LightingPasses/DI/ShadeSamples.hlsl"]


def replace_once(path, old, new):
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"Unexpected pinned source at {path.relative_to(RENDERER)}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def adapt_reference():
    source = RENDERER / "Samples/FullSample/Source"
    replace_once(source / "App/SceneRenderer.cpp", '"shaders/full-sample"', '"shaders/full-sample-reference"')
    for name in ("DiffuseLighting", "SpecularLighting", "HdrColor"):
        replace_once(source / "RenderTargets.cpp",
                     f'desc.format = nvrhi::Format::RGBA16_FLOAT;\n    desc.debugName = "{name}";',
                     f'desc.format = nvrhi::Format::RGBA32_FLOAT;\n    desc.debugName = "{name}";')
    # Leave light preparation/PDF construction active, but don't create RIS pools.
    replace_once(source / "RenderPasses/LightingPasses/LightingPasses.cpp",
                 '    bool needLocalLightPresampling = isContext.IsLocalLightPowerRISEnabled() ||',
                 '    return; // Conventional reference samples PDF mipmaps directly.\n\n    bool needLocalLightPresampling = isContext.IsLocalLightPowerRISEnabled() ||')
    path = source / "RenderPasses/LightingPasses/ReSTIRDIRenderPasses.cpp"
    replace_once(path,
                 '        ExecuteRayTracingPass(commandList, m_generateInitialSamplesPass, m_enableRayCounts, "DIGenerateInitialSamples", dispatchSize, *m_profiler, ProfilerSection::InitialSamples, m_descriptorTable, m_bindingSet);',
                 '        // Conventional reference: no initial RIS or reservoir generation.')
    # ShaderMake compares mtimes; copy2 can leave the replacement older than
    # an official blob and silently publish the wrong estimator.
    shutil.copyfile(REFERENCE_SHADER, RENDERER / REFERENCE_FILES[-1])
    DEST.write_text("#define LAB_REFERENCE_BUILD\n" + HELPER.read_text(encoding="utf-8"), encoding="utf-8")


def validate_reference_shaders(official, current):
    shading = [name for name in official if name.replace("\\", "/").endswith("/ShadeSamples.bin")]
    if not shading or any(name not in current or current[name] == official[name] for name in shading):
        raise RuntimeError("Conventional reference shader did not rebuild; refusing publication")


def run(*args, cwd=ROOT):
    subprocess.run(args, cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", action="store_true", help="Build isolated conventional reference executable/shaders")
    args = parser.parse_args()
    files = FILES + (REFERENCE_FILES if args.reference else [])
    official = BIN / "FullSample.exe"
    prepare_variant(RENDERER, official, created=[DEST])
    donut = checked_submodule(RENDERER, "External/donut", ["src/engine/GltfImporter.cpp"])
    files.append(str(IMPORTER))
    run("git", "apply", "--check", str(PATCH), cwd=RENDERER)
    shader_dir = BIN / "shaders/full-sample"
    record = {"built_utc": datetime.now(timezone.utc).isoformat(), "donut": donut,
              "renderer_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=RENDERER, text=True).strip(),
              "configuration": "Release", "integration_sha256": integration_hashes(
                  [PATCH, HELPER, SUPPORT_FILE, BUILD_SUPPORT_FILE, Path(__file__),
                   *([REFERENCE_SHADER] if args.reference else [])], ROOT),
              "compiler_cache_sha256": sha(BUILD / "CMakeCache.txt")}
    variant = BIN / ("FullSampleReference.exe" if args.reference else "FullSampleExperiments.exe")
    record["shader_directory"] = "shaders/full-sample-reference" if args.reference else "shaders/full-sample"
    def adapt():
        shutil.copy2(HELPER, DEST)
        if args.reference:
            adapt_reference()

    build_variant(renderer=RENDERER, build=BUILD, official=official, variant=variant,
        files=files, shader_dir=shader_dir, record=record, patch=PATCH, run=run,
        emission=emission_support(RENDERER / IMPORTER), adapt=adapt, created=[DEST],
        shader_destination=BIN / record["shader_directory"] if args.reference else None,
        validate_shaders=validate_reference_shaders if args.reference else None)
    print(f"Built {variant}; official source, executable and shaders restored")


if __name__ == "__main__":
    main()
