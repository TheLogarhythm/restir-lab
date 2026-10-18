"""Reuse completed derived outputs by their caller-supplied input fingerprint."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

RECEIPT_NAME = ".controlled-output.json"


def _canonical(identity):
    # A JSON round trip normalizes tuples and JSON object keys before sorting.
    normalized = json.loads(json.dumps(identity, ensure_ascii=False, allow_nan=False))
    return normalized, json.dumps(normalized, sort_keys=True, separators=(",", ":"),
                                  ensure_ascii=False, allow_nan=False)


def _inventory(directory):
    """Hash regular output files without following links or receipt paths."""
    files, pending = {}, [directory]
    while pending:
        for path in sorted(pending.pop().iterdir()):
            if path == directory / RECEIPT_NAME:
                continue
            info = path.lstat()
            if (stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                raise ValueError(f"Linked controlled output is unsupported: {path}")
            if path.is_dir():
                pending.append(path)
            elif path.is_file():
                digest, size = hashlib.sha256(), 0
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                        size += len(block)
                files[path.relative_to(directory).as_posix()] = {"sha256": digest.hexdigest(), "bytes": size}
            else:
                raise ValueError(f"Controlled output is not a regular file: {path}")
    return files


def _matches(directory, digest, canonical):
    receipt_path = directory / RECEIPT_NAME
    if not directory.is_dir() or directory.is_symlink() or receipt_path.is_symlink():
        return False
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        return (isinstance(receipt, dict) and type(receipt.get("schema_version")) is int
            and receipt["schema_version"] == 2 and receipt.get("status") == "completed"
            and receipt.get("identity_sha256") == digest and "identity" in receipt
            and _canonical(receipt["identity"])[1] == canonical
            and isinstance(receipt.get("files"), dict)
            and receipt["files"] == _inventory(directory))
    except (OSError, ValueError, TypeError):
        return False


def _occupied(path):
    return path.exists() or path.is_symlink()


def generate_versioned(destination, identity, generate):
    """Return a matching completed output or generate a fresh version directory.

    ``identity`` is JSON-serializable input settings/hashes; the caller validates
    those raw inputs. ``generate(path)`` owns creation of the absent directory
    and must return successfully only after its output is complete. The helper
    never precreates, overwrites, or removes an output directory. Interrupted
    outputs remain untouched and receive no completion receipt. Calls for the
    same destination should be serialized by the controlling worker.
    """
    destination = Path(destination).absolute()
    if not destination.name:
        raise ValueError("Destination must name an output directory")
    normalized, canonical = _canonical(identity)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    version = destination.with_name(f"{destination.name}-{digest[:12]}")
    pattern = re.compile(re.escape(version.name) + r"(?:-([1-9]\d*))?$")
    candidates = [destination]
    if destination.parent.is_dir():
        versions = []
        for path in destination.parent.iterdir():
            match = pattern.fullmatch(path.name)
            if match:
                versions.append((int(match.group(1) or 0), path))
        candidates.extend(path for _, path in sorted(versions))
    for path in candidates:
        if _matches(path, digest, canonical):
            return path
    target = destination
    if _occupied(target):
        target, counter = version, 1
        while _occupied(target):
            target = version.with_name(f"{version.name}-{counter}")
            counter += 1
    generate(target)
    if not target.is_dir() or target.is_symlink():
        raise RuntimeError("Generator did not create a completed output directory")
    receipt_path = target / RECEIPT_NAME
    if _occupied(receipt_path):
        raise RuntimeError("Generator created the reserved controlled-output receipt")
    receipt = {"schema_version": 2, "status": "completed",
               "identity_sha256": digest, "identity": normalized, "files": _inventory(target)}
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target,
            prefix=RECEIPT_NAME + "-", suffix=".tmp", delete=False) as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
        temporary = Path(stream.name)
    temporary.replace(receipt_path)
    return target
