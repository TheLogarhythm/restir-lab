"""Small read-only IO and inventory checks shared by compact archive verifiers."""

from pathlib import Path, PureWindowsPath

from .provenance import sha256
from .validation import read_json_value, require_digest


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    """Read saved object or array JSON with the run-format integrity protections."""
    return read_json_value(path)[0]


def child(root, relative, *, must_exist=True):
    """Resolve an archive member, rejecting portable traversal and symlink escapes."""
    if not isinstance(relative, str) or not relative or "\0" in relative:
        raise ValueError("Expected a contained relative path: " + str(relative))
    portable = PureWindowsPath(relative)
    if (Path(relative).is_absolute() or portable.drive or portable.root
            or ".." in portable.parts):
        raise ValueError("Expected a contained relative path: " + relative)
    root = Path(root).resolve()
    path = (root / relative).resolve()
    require(path.is_relative_to(root), "Path escapes archive: " + relative)
    if must_exist:
        require(path.exists(), "Missing archive path: " + relative)
    return path


def verify_inventory(root, files, *, allowed_unindexed=(),
                     changed_message="File changed", extra_message="Unindexed files"):
    """Check every listed file's size/hash and reject unlisted current files."""
    root = Path(root).resolve()
    indexed = {}
    for record in files:
        require(isinstance(record, dict), "Invalid archive inventory record")
        name = record["path"]
        path = child(root, name)
        require(name not in indexed, "Duplicate file: " + name)
        require(path.is_file(), "Missing archive file: " + name)
        require(type(record.get("bytes")) is int and record["bytes"] >= 0,
                "Invalid byte count: " + name)
        try:
            digest = require_digest(record.get("sha256"))
        except ValueError as exc:
            raise ValueError("Invalid archive digest: " + name) from exc
        require(path.stat().st_size == record["bytes"] and sha256(path) == digest,
                changed_message + ": " + name)
        indexed[name] = record
    actual = {path.relative_to(root).as_posix()
              for path in root.rglob("*") if path.is_file()}
    extras = actual - set(indexed) - set(allowed_unindexed)
    require(not extras, extra_message + ": " + str(sorted(extras)[:5]))
    return indexed
