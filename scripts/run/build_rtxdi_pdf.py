"""Build an isolated PDF-similarity experiment variant; restore upstream files/binaries."""
from datetime import datetime, timezone
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
import build_rtxdi_experiments as base
import rtxdi_pdf as pdf
from rtxdi_build import (backup_renderer, restore_renderer, restore_shader_tree, tree_hashes,
                        integration_hashes, checked_submodule, require_clean_renderer, invalidate_cpp)
from rtxdi_emission import emission_support
from rtxdi_common import sha


def main():
    renderer, binary = base.RENDERER, base.BIN
    official = binary / "FullSample.exe"
    if not official.is_file():
        raise RuntimeError("Build official FullSample first")
    running = subprocess.check_output(["powershell", "-NoProfile", "-Command",
        "Get-Process FullSample* -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"], text=True)
    if running.strip():
        raise RuntimeError("Close FullSample before building")
    require_clean_renderer(renderer)
    created = [base.DEST, *(renderer / name for name in pdf.CREATED)]
    if any(path.exists() for path in created):
        raise RuntimeError("A PDF integration destination already exists")
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
    temporary = Path(tempfile.mkdtemp(prefix="experiment-build-", dir=base.BUILD))
    variant = binary / "FullSamplePdf.exe"
    restored = False
    try:
        backup_renderer(temporary, renderer, files, official, shaders)
        try:
            base.run("git", "apply", str(base.PATCH), cwd=renderer)
            shutil.copy2(base.HELPER, base.DEST)
            pdf.adapt(renderer, base.DEST)
            invalidate_cpp(renderer)
            with emission_support(renderer / base.IMPORTER):
                base.run("cmake", "--build", str(base.BUILD), "--config", "Release", "--target", "FullSample", "--parallel", "4")
            shutil.copytree(shaders, temporary / "pdf-shaders")
            shutil.copy2(official, temporary / variant.name)
            record["executable_sha256"] = sha(temporary / variant.name)
            record["shader_sha256"] = tree_hashes(temporary / "pdf-shaders")
        finally:
            restore_renderer(temporary, renderer, files, official, shaders, created=created)
            restored = True
        shutil.copy2(temporary / variant.name, variant)
        restore_shader_tree(temporary / "pdf-shaders", binary / record["shader_directory"])
    finally:
        if restored:
            base.remove_backup(temporary)
        else:
            print(f"Recovery backup retained: {temporary}")
    variant.with_suffix(".build.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"Built {variant}; upstream files, official executable and shaders restored")


if __name__ == "__main__":
    main()
