"""Extract one named scene folder and source notices into a new directory."""
import argparse
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import zipfile

from gltf import digest

NOTICES = {"README.txt", "LICENSE.txt", "CHANGELOG.txt"}


def selected_members(archive, folder):
    """Validate paths and reject names that collide on case-insensitive filesystems."""
    selected, names, prefixes = [], set(), {}
    for member in archive.infolist():
        path = PurePosixPath(member.filename)
        if (not path.parts or path.is_absolute() or ".." in path.parts
                or "\\" in member.filename or ":" in member.filename):
            raise ValueError(f"Unsafe archive path: {member.filename}")
        in_scene = path.parts[0] == folder and len(path.parts) > 1
        if not (in_scene or path.as_posix() in NOTICES):
            continue
        if stat.S_ISLNK(member.external_attr >> 16):
            raise ValueError(f"Archive symlink is unsupported: {member.filename}")
        key = path.as_posix().casefold()
        if key in names:
            raise ValueError(f"Archive path collision: {member.filename}")
        names.add(key)
        for count in range(1, len(path.parts) + 1):
            prefix = PurePosixPath(*path.parts[:count]).as_posix()
            if prefixes.setdefault(prefix.casefold(), prefix) != prefix:
                raise ValueError(f"Archive case collision: {member.filename}")
        selected.append((member, path))
    if not any(len(path.parts) > 1 and path.parts[0] == folder and not member.is_dir()
               for member, path in selected):
        raise ValueError(f"No files for {folder}")
    return selected


def extract_scene(archive_path, folder, output, *, expected_sha256=None):
    """Stage a complete extraction and publish only after every CRC has passed."""
    archive_path, output = Path(archive_path).resolve(), Path(output).resolve()
    if (len(PurePosixPath(folder).parts) != 1 or folder in ("", ".", "..")
            or any(character in folder for character in ("/", "\\", ":"))):
        raise ValueError("folder must be one top-level directory name")
    if output.exists():
        raise FileExistsError(f"Use a new extraction directory: {output}")
    if expected_sha256 is not None:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
            raise ValueError("Expected SHA-256 must contain 64 hexadecimal digits")
        if digest(archive_path) != expected_sha256.lower():
            raise ValueError("Archive SHA-256 differs from the expected source")
    with zipfile.ZipFile(archive_path) as archive:
        selected = selected_members(archive, folder)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".extraction-", dir=output.parent) as temporary:
            stage = Path(temporary) / "scene"
            stage.mkdir()
            for member, path in selected:
                target = (stage / Path(*path.parts)).resolve()
                if not target.is_relative_to(stage):
                    raise ValueError(f"Unsafe extraction path: {member.filename}")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open("xb") as destination:
                        shutil.copyfileobj(source, destination, length=1024 * 1024)
            if output.exists():
                raise FileExistsError(f"Output directory appeared during extraction: {output}")
            stage.rename(output)
    return len(selected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--folder", required=True, help="Top-level folder to extract, e.g. MEASURE_SEVEN")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-sha256", help="Verify the pinned source archive before extracting")
    args = parser.parse_args()
    try:
        count = extract_scene(args.archive, args.folder, args.output, expected_sha256=args.expected_sha256)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Extraction failed: {exc}\n")
    print(f"Extracted {count} entries to {args.output.resolve()}")


if __name__ == "__main__":
    main()
