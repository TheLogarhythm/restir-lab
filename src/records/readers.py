"""Select saved formats without importing any live renderer or build helpers."""

from pathlib import Path

from .validation import artifact_path, checked_image, read_json
from .provenance import sha256


def read_run(directory, backend=None):
    directory = Path(directory).resolve()
    manifest, digest = read_json(artifact_path(directory, "manifest.json"))
    if manifest.get("status") != "completed":
        raise ValueError("Saved run is not completed")
    recorded = manifest.get("backend")
    inferred = recorded or (
        "rtxdi" if "captures" in manifest and "config_sha256" in manifest else None
    )
    if backend is not None and backend != inferred:
        raise ValueError("Requested backend differs from saved format")
    try:
        if inferred == "rtxdi":
            from backends.rtxdi.records import normalize
        elif inferred == "falcor":
            from backends.falcor.records import normalize
        else:
            raise ValueError("Unsupported saved-run format")
        return normalize(directory, manifest, digest)
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError(f"Malformed {inferred} saved-run record: {exc}") from exc


def load_frame(run, index):
    """Recheck artifact ownership, hash and dimensions on every load."""
    validate_record(run)
    frame = run.frame(index)
    relative = frame.image.relative_to(run.directory).as_posix()
    path = artifact_path(run.directory, relative)
    return checked_image(
        path, frame.sha256, run.width, run.height, float32_exr=run.backend == "falcor"
    )


def validate_record(run):
    """A record is a snapshot; reject metadata changes before using it again."""
    for name, digest in run.provenance["record_files"].items():
        if sha256(artifact_path(run.directory, name)) != digest:
            raise ValueError("Saved record changed since it was read: " + name)
