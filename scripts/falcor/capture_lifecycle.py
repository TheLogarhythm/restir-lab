"""Shared environment and attempt lifecycle rules for Falcor captures."""

import json
import os
import re
import tempfile
from pathlib import Path


def check_shader_environment():
    """Private runtime receipts are meaningful only with deployment shaders."""
    if os.environ.get("FALCOR_DEVMODE") == "1":
        raise RuntimeError("FALCOR_DEVMODE overrides isolated shaders")


def preserve_failure(directory, error, *, receipt_name="launch-failure.json"):
    """Retain a pre-launch failure when the process runner made no attempt yet."""
    directory = Path(directory)
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=False)
        atomic_json(directory / receipt_name, {"status": "failed", "error": str(error)})


def atomic_json(path, value):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=".campaign-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf8", newline="\n") as f:
            json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def choose_attempt(directory, *, retry_failed=False):
    directory = Path(directory)
    if type(retry_failed) is not bool:
        raise ValueError("Invalid retry flag")
    if not directory.exists():
        return (directory / "attempt-001", False)
    attempts = []
    for p in directory.iterdir():
        if p.name.startswith("attempt-"):
            if not p.is_dir() or not re.fullmatch("attempt-\\d{3}", p.name):
                raise ValueError("Unexpected attempt entry")
            attempts.append(p)
    if not attempts:
        return (directory / "attempt-001", False)
    attempts.sort(key=lambda p: p.name)
    if [p.name for p in attempts] != [f"attempt-{i:03d}" for i in range(1, len(attempts) + 1)]:
        raise ValueError("Attempt numbering is not contiguous")
    latest = attempts[-1]
    path = latest / "manifest.json"
    if path.is_file():
        meta = json.loads(path.read_text(encoding="utf8"))
        if meta.get("status") == "completed":
            return (latest, True)
    if not retry_failed:
        raise ValueError(
            "Incomplete or failed attempt preserved; use --retry-failed to create a new attempt"
        )
    if len(attempts) >= 999:
        raise ValueError("Attempt limit reached")
    return (directory / f"attempt-{len(attempts) + 1:03d}", False)
