"""Build the external-scene sample using a reviewable patch; restore official files."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from rtxdi_common import ROOT, RENDERER, sha

SOURCE = RENDERER / "Samples/FullSample/Source/App/SceneRenderer.cpp"
BUILD = RENDERER / "build"
BIN = BUILD / "bin"
PATCH = Path(__file__).with_name("rtxdi_external.patch")


def run(*args, cwd=ROOT):
    subprocess.run(args, cwd=cwd, check=True)


def main():
    official = BIN / "FullSample.exe"
    if not official.is_file():
        raise RuntimeError("Build official FullSample first; see docs/setup.md")
    relative = str(SOURCE.relative_to(RENDERER))
    clean = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", relative], cwd=RENDERER)
    if clean.returncode:
        raise RuntimeError("SceneRenderer.cpp has staged or unstaged changes; refusing to patch it")
    run("git", "apply", "--check", str(PATCH), cwd=RENDERER)
    original = SOURCE.read_bytes()
    original_binary_hash = sha(official)
    variant = BIN / "FullSampleExternal.exe"
    record = {"built_utc": datetime.now(timezone.utc).isoformat(),
              "renderer_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=RENDERER, text=True).strip(),
              "source_sha256": sha(SOURCE), "patch_sha256": sha(PATCH),
              "build_script_sha256": sha(Path(__file__)), "configuration": "Release"}
    # Back up the executable directly: restoring it must not depend on another build succeeding.
    with tempfile.TemporaryDirectory(prefix="external-build-", dir=BUILD) as temporary:
        backup = Path(temporary) / "FullSample.exe"
        shutil.copy2(official, backup)
        try:
            run("git", "apply", str(PATCH), cwd=RENDERER)
            run("cmake", "--build", str(BUILD), "--config", "Release", "--target", "FullSample", "--parallel", "4")
            staged = Path(temporary) / variant.name
            shutil.copy2(official, staged)
            record["executable_sha256"] = sha(staged)
        finally:
            SOURCE.write_bytes(original)
            shutil.copy2(backup, official)
        if SOURCE.read_bytes() != original or sha(official) != original_binary_hash:
            raise RuntimeError("Official source/executable restoration failed")
        staged.replace(variant)
    variant.with_suffix(".build.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"Built {variant}; official source and executable restored")


if __name__ == "__main__":
    main()
