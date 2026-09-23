"""Extract one named scene folder and source notices from an ORCA ZIP."""

import argparse
from pathlib import Path, PurePosixPath
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--folder", required=True, help="Top-level folder to extract, e.g. MEASURE_ONE")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    folder = PurePosixPath(args.folder)
    if len(folder.parts) != 1 or folder.name in ("", ".", ".."):
        parser.error("--folder must be one top-level directory name")
    notices = {"README.txt", "LICENSE.txt", "CHANGELOG.txt"}
    found = 0
    with zipfile.ZipFile(args.archive) as archive:
        selected = []
        scene_files = 0
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            if not path.parts or path.is_absolute() or ".." in path.parts or "\\" in member.filename or ":" in member.filename:
                raise ValueError(f"Unsafe archive path: {member.filename}")
            in_scene = path.parts[0] == folder.name and len(path.parts) > 1
            if not (in_scene or path.as_posix() in notices):
                continue
            target = (output / Path(*path.parts)).resolve()
            if not target.is_relative_to(output):
                raise ValueError(f"Unsafe extraction path: {member.filename}")
            selected.append((member, target))
            scene_files += int(in_scene and not member.is_dir())
        if not scene_files:
            raise ValueError(f"No files for {folder.name}")
        # Validate the selection before writing notices or partially extracting a scene.
        for member, target in selected:
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, target.open("wb") as dst:
                    while chunk := src.read(1024 * 1024):
                        dst.write(chunk)
            found += 1
    print(f"Extracted {found} entries to {output}")


if __name__ == "__main__":
    main()
