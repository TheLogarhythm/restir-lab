"""Shared build fingerprints and recoverable restoration for pinned renderer variants."""
from pathlib import Path
import shutil
import subprocess
from rtxdi_common import sha

SUPPORT_FILE = Path(__file__).resolve()


def lighting_signature(build):
    """Shared scene/light interpretation, excluding estimator-specific binaries/shaders."""
    sources = ("scripts/run/build_rtxdi_experiments.py", "scripts/run/rtxdi_experiments.patch",
               "scripts/run/rtxdi_experiments/LabExperiment.h", "scripts/run/rtxdi_emission.py")
    try:
        values = (build["renderer_commit"], build["donut"]["commit"],
                  build["donut"]["source_sha256"]["src/engine/GltfImporter.cpp"],
                  *(build["integration_sha256"][name] for name in sources))
    except (KeyError, TypeError) as exc:
        raise ValueError("Missing lighting provenance; rebuild and regenerate baseline/reference runs") from exc
    if not all(isinstance(value, str) and value for value in values):
        raise ValueError("Invalid lighting provenance; rebuild and regenerate baseline/reference runs")
    return values


def integration_hashes(paths, root):
    return {Path(path).relative_to(root).as_posix(): sha(path) for path in paths}


def validate_integration(record, root, required=()):
    hashes = record.get("integration_sha256", {})
    expected = {Path(path).relative_to(root).as_posix() for path in required}
    if not hashes or not expected.issubset(hashes):
        raise RuntimeError("Incomplete build signature; rebuild the executable")
    for name, digest in hashes.items():
        path = root / name
        if not path.is_file() or sha(path) != digest:
            raise RuntimeError(f"Integration changed ({name}); rebuild the executable")


def checked_submodule(renderer, name, sources):
    """Check the dependency in its own repository before recording pristine inputs."""
    def git(directory, *args):
        return subprocess.check_output(["git", *args], cwd=directory, text=True).strip()

    entry = git(renderer, "ls-tree", "HEAD", "--", name).split(maxsplit=3)
    if len(entry) != 4 or entry[:2] != ["160000", "commit"]:
        raise RuntimeError(f"Expected pinned submodule: {name}")
    directory = renderer / name
    revision = git(directory, "rev-parse", "HEAD")
    if revision != entry[2]:
        raise RuntimeError(f"{name} differs from the pinned revision")
    if git(directory, "status", "--porcelain", "--untracked-files=no", "--ignore-submodules=none"):
        raise RuntimeError(f"{name} has local changes; refusing to build")
    return {"path": name, "commit": revision,
            "source_sha256": {source: sha(directory / source) for source in sources}}


def require_clean_renderer(renderer):
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=normal", "--ignore-submodules=none"],
        cwd=renderer, text=True).strip()
    if status:
        raise RuntimeError("Renderer or dependencies have local changes; refusing to build")


def invalidate_cpp(renderer):
    # Restored source mtimes can precede object files from a different variant.
    for source in (renderer / "Samples/FullSample/Source").rglob("*.cpp"):
        source.touch()


def tree_hashes(directory):
    return {str(p.relative_to(directory)): sha(p) for p in directory.rglob("*") if p.is_file()}


def restore_shader_tree(backup, destination):
    expected = tree_hashes(backup)
    shutil.copytree(backup, destination, dirs_exist_ok=True)
    for path in destination.rglob("*"):
        if path.is_file() and str(path.relative_to(destination)) not in expected:
            if not path.resolve().is_relative_to(destination.resolve()):
                raise RuntimeError("Shader path escaped build directory")
            path.unlink()
    if tree_hashes(destination) != expected:
        raise RuntimeError("Shader restoration verification failed")


def backup_renderer(backup, renderer, files, official, shader_dir):
    for name in files:
        target = backup / "sources" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(renderer / name, target)
    shutil.copy2(official, backup / "official.exe")
    shutil.copytree(shader_dir, backup / "shaders")


def restore_renderer(backup, renderer, files, official, shader_dir, created=()):
    errors = []
    copies = [(backup / "sources" / name, renderer / name, True) for name in files]
    copies.append((backup / "official.exe", official, False))
    for source, destination, is_source in copies:
        try:
            shutil.copy2(source, destination)
            if sha(source) != sha(destination):
                raise RuntimeError("Restoration verification failed")
            if is_source:
                # copy2 restores old mtimes; invalidate objects compiled with the temporary patch.
                destination.touch()
        except Exception as exc:
            errors.append(f"{destination}: {exc}")
    for path in created:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(f"{path}: {exc}")
    try:
        restore_shader_tree(backup / "shaders", shader_dir)
    except Exception as exc:
        errors.append(f"shaders: {exc}")
    if errors:
        raise RuntimeError(f"Renderer restoration failed; recovery files retained at {backup}: " + "; ".join(errors))


def remove_backup(backup, build, prefix):
    resolved = backup.resolve()
    if resolved.parent != build.resolve() or not resolved.name.startswith(prefix) or backup.is_symlink():
        raise RuntimeError(f"Unexpected backup directory: {backup}")
    shutil.rmtree(resolved)
