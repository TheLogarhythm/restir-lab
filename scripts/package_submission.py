"""Build the two-scene Canvas code archive from the current project's sources and verified runtime.

From the Git checkout, run: python -B -m scripts.package_submission
"""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import unquote
import zipfile

from scripts.falcor.live_runtime import POINTER, ROOT, locate


SCENES = (
    "assets/converted/classroom/classroom.gltf",
    "assets/converted/veach-ajar/veach-ajar.gltf",
)
EXTRA_FILES = (
    "assets/converted/classroom/classroom.scene.json",
    "assets/prepared/classroom/classroom/ReadMe.txt",
    "assets/prepared/veach-ajar/veach-ajar/LICENSE.txt",
    "renderers/rtxdi/Assets/Media/environment/urban_street_04_4k.exr",
    "renderers/rtxdi/Assets/Media/environment/README.txt",
    "renderers/rtxdi/Assets/Media/LICENSE",
    "renderers/rtxdi/LICENSE.txt",
    "renderers/falcor/upstream/LICENSE.md",
)
SOURCE_DIRS = {
    ".github", "docs", "experiments", "renderers", "results", "scenes",
    "scripts", "src", "tests", "web", "writing",
}
PRESENTATION_TESTS = {
    "tests/test_final_presentation_build.py", "tests/test_final_presentation_media.py",
}


def source_files():
    # Git supplies project files and new non-ignored source files in the working tree.
    # Submodules are directory entries; ship the pinned versions and adapted code.
    inventory = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT,
    )
    for name in inventory.decode("utf-8").split("\0"):
        if not name or name.startswith("writing/final/") or name in PRESENTATION_TESTS:
            continue
        p = Path(name)
        if len(p.parts) == 1 and name not in {
            ".gitattributes", ".gitignore", ".gitmodules", "AGENTS.md", "CONTRIBUTING.md",
            "LICENSE", "README.md", "THIRD_PARTY.md", "pyproject.toml", "run-demo.ps1",
        }:
            continue
        if len(p.parts) > 1 and p.parts[0] not in SOURCE_DIRS:
            continue
        if (ROOT / p).is_file():
            yield ROOT / p


def scene_files():
    for name in SCENES:
        scene = ROOT / name
        yield scene
        model = json.loads(scene.read_text(encoding="utf-8-sig"))
        for item in model.get("buffers", []) + model.get("images", []):
            uri = item.get("uri")
            if not uri or uri.startswith("data:"):
                continue
            resource = (scene.parent / unquote(uri)).resolve(strict=True)
            if not resource.is_relative_to(scene.parent):
                raise ValueError(f"Scene resource outside its directory: {resource}")
            yield resource


def build_zip(output):
    runtime = locate(full=True)
    receipt = runtime.parent / "receipt.json"
    deployed_files = json.loads(receipt.read_text(encoding="utf8"))["files"]

    files = set(source_files()) | set(scene_files())
    files.update(ROOT / name for name in EXTRA_FILES)
    # Third-party notices for libraries linked into the Falcor core.
    external = ROOT / "renderers/falcor/upstream/external"
    for name in ("args/LICENSE", "fmt/LICENSE.rst", "glfw/LICENSE.md", "imgui/LICENSE.txt",
                 "pybind11/LICENSE", "vulkan-headers/LICENSE.txt"):
        files.add(external / name)
    files.update((runtime / name) for name in deployed_files)
    files.update((receipt, POINTER))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        staged = Path(temporary) / "code.zip"
        with zipfile.ZipFile(staged, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for p in sorted(files):
                name = p.relative_to(ROOT).as_posix()
                if p.stat().st_size < 1024:
                    with p.open("rb") as stream:
                        if stream.readline(80).strip() == b"version https://git-lfs.github.com/spec/v1":
                            raise ValueError(f"Fetch the actual Git LFS object before packaging: {name}")
                archive.write(p, name)
        with zipfile.ZipFile(staged) as archive:
            damaged = archive.testzip()
            if damaged is not None:
                raise ValueError(f"ZIP CRC mismatch: {damaged}")
        staged.replace(output)
    print(f"{output} ({len(files)} files, {output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/submission/code.zip")
    build_zip(parser.parse_args().output.resolve())
