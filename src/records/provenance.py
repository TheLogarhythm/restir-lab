"""Stable file and shared-source fingerprints; no live renderer inspection."""

import hashlib
from pathlib import Path


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


PACKAGE_NAMES = ("analysis", "backends", "image_io", "metrics", "records")


def _package_files(base):
    # The installed base can be site-packages; never fingerprint its other libraries.
    return sorted(
        path for name in PACKAGE_NAMES for path in (base / name).rglob("*.py")
    )


def shared_source_hashes(root):
    """Include package/config changes in new run and frozen-batch inventories."""
    root = Path(root)
    files = _package_files(root / "src")
    project = root / "pyproject.toml"
    if project.is_file():
        files.append(project)
    return {path.relative_to(root).as_posix(): sha256(path) for path in files}


def package_source_hashes():
    """Fingerprint installed/editable package code using location-independent keys."""
    package = Path(__file__).resolve().parents[1]
    return {
        path.relative_to(package).as_posix(): sha256(path)
        for path in _package_files(package)
    }
