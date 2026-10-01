"""Build the isolated experiment executable, restoring pinned source and official binary."""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from rtxdi_common import ROOT, RENDERER, sha

HERE = Path(__file__).resolve().parent
BUILD = RENDERER / "build"
BIN = BUILD / "bin"
PATCH = HERE / "rtxdi_experiments.patch"
HELPER = HERE / "rtxdi_experiments/LabExperiment.h"
FILES = ["Samples/FullSample/Source/App/SceneRenderer.cpp", "Samples/FullSample/Source/Profiler.h",
         "Samples/FullSample/Source/App/SceneRenderer.h", "Samples/FullSample/Source/main.cpp",
         "Samples/FullSample/Source/App/CommandLineArgs.cpp"]
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
    shutil.copy2(REFERENCE_SHADER, RENDERER / REFERENCE_FILES[-1])
    DEST.write_text("#define LAB_REFERENCE_BUILD\n" + HELPER.read_text(encoding="utf-8"), encoding="utf-8")


def run(*args, cwd=ROOT):
    subprocess.run(args, cwd=cwd, check=True)


def tree_hashes(directory):
    return {str(p.relative_to(directory)): sha(p) for p in directory.rglob("*") if p.is_file()}


def restore_shader_tree(backup, destination):
    """Restore files and remove outputs absent from the backup."""
    expected = tree_hashes(backup)
    shutil.copytree(backup, destination, dirs_exist_ok=True)
    for path in destination.rglob("*"):
        if path.is_file() and str(path.relative_to(destination)) not in expected:
            if not path.resolve().is_relative_to(destination.resolve()):
                raise RuntimeError(f"Shader output escapes its directory: {path}")
            path.unlink()
    if tree_hashes(destination) != expected:
        raise RuntimeError("Shader restoration verification failed")


def restore_official(backup, files, official, shader_dir):
    """Attempt every recovery step; retain all backups if any step fails."""
    errors = []
    for name in files:
        try:
            source = backup / "sources" / name
            destination = RENDERER / name
            shutil.copy2(source, destination)
            if sha(source) != sha(destination):
                raise RuntimeError("Source restoration verification failed")
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    try:
        DEST.unlink(missing_ok=True)
    except OSError as exc:
        errors.append(f"helper: {exc}")
    try:
        shutil.copy2(backup / "official.exe", official)
        if sha(official) != sha(backup / "official.exe"):
            raise RuntimeError("Executable restoration verification failed")
    except Exception as exc:
        errors.append(f"executable: {exc}")
    try:
        restore_shader_tree(backup / "shaders", shader_dir)
    except Exception as exc:
        errors.append(f"shaders: {exc}")
    if errors:
        raise RuntimeError(f"Official renderer restoration failed; recovery files retained at {backup}: "
                           + "; ".join(errors))


def remove_backup(backup):
    # The only recursive removal is a verified temporary directory under this build.
    resolved = backup.resolve()
    if resolved.parent != BUILD.resolve() or not resolved.name.startswith("experiment-build-"):
        raise RuntimeError(f"Unexpected backup directory: {backup}")
    shutil.rmtree(resolved)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", action="store_true", help="Build isolated conventional reference executable/shaders")
    args = parser.parse_args()
    files = FILES + (REFERENCE_FILES if args.reference else [])
    official = BIN / "FullSample.exe"
    if not official.is_file():
        raise RuntimeError("Build official FullSample first; see docs/setup.md")
    running = subprocess.check_output(["powershell", "-NoProfile", "-Command",
        "Get-Process FullSample* -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"], text=True)
    if running.strip():
        raise RuntimeError("Close FullSample before building its experiment variant")
    if DEST.exists():
        raise RuntimeError(f"Refusing to overwrite {DEST}")
    run("git", "diff", "--exit-code", "HEAD", "--", *files, cwd=RENDERER)
    run("git", "apply", "--check", str(PATCH), cwd=RENDERER)
    shader_dir = BIN / "shaders/full-sample"
    shader_hashes = tree_hashes(shader_dir)
    record = {"built_utc": datetime.now(timezone.utc).isoformat(),
              "renderer_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=RENDERER, text=True).strip(),
              "configuration": "Release", "integration_sha256": {
                  str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in [PATCH, HELPER, Path(__file__), *([REFERENCE_SHADER] if args.reference else [])]},
              "compiler_cache_sha256": sha(BUILD / "CMakeCache.txt")}
    variant = BIN / ("FullSampleReference.exe" if args.reference else "FullSampleExperiments.exe")
    record["shader_directory"] = "shaders/full-sample-reference" if args.reference else "shaders/full-sample"
    temporary = Path(tempfile.mkdtemp(prefix="experiment-build-", dir=BUILD))
    restored = False
    try:
        for name in files:
            target = temporary / "sources" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(RENDERER / name, target)
        shutil.copy2(official, temporary / "official.exe")
        # No shader changes are intended; preserve the official outputs even if CMake rebuilds them.
        shutil.copytree(shader_dir, temporary / "shaders")
        try:
            run("git", "apply", str(PATCH), cwd=RENDERER)
            shutil.copy2(HELPER, DEST)
            if args.reference:
                adapt_reference()
            run("cmake", "--build", str(BUILD), "--config", "Release", "--target", "FullSample", "--parallel", "4")
            current = tree_hashes(shader_dir)
            if not args.reference and current != shader_hashes:
                raise RuntimeError("Unexpected compiled shader changes; experiment variant was not published")
            if args.reference:
                shutil.copytree(shader_dir, temporary / "reference-shaders")
            shutil.copy2(official, temporary / variant.name)
            record["executable_sha256"] = sha(temporary / variant.name)
        finally:
            restore_official(temporary, files, official, shader_dir)
            restored = True
        shutil.copy2(temporary / variant.name, variant)
        if args.reference:
            restore_shader_tree(temporary / "reference-shaders", BIN / record["shader_directory"])
    finally:
        if restored:
            remove_backup(temporary)
        else:
            print(f"Recovery backup retained: {temporary}")
    record["shader_sha256"] = current if args.reference else shader_hashes
    variant.with_suffix(".build.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"Built {variant}; official source, executable and shaders restored")


if __name__ == "__main__":
    main()
