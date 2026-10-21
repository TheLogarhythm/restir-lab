"""Download, verify and convert a scene pinned in scenes/manifest.yaml."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from urllib.request import Request, urlopen
import zipfile

from asset_io import validate_bundle
from convert_scene import convert_scene
from gltf import digest

ROOT = Path(__file__).resolve().parents[2]
RECORD = ".installation.json"


def relative_entry(value, name):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\0" in value:
        raise ValueError(f"Unsafe {name}: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.rstrip("/").split("/")):
        raise ValueError(f"Unsafe {name}: {value!r}")
    return path


def scene_record(scene_id, root):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", scene_id):
        raise ValueError("Invalid scene ID")
    scenes = json.loads((root / "scenes/manifest.yaml").read_text(encoding="utf-8"))["scenes"]
    matches = [scene for scene in scenes if scene["id"] == scene_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one registered scene: {scene_id}")
    record = matches[0]
    for key in ("source_download_url", "source_revision", "source_sha256", "installation", "runtime_assets"):
        if key not in record:
            raise ValueError(f"Scene {scene_id} needs {key}")
    revision = relative_entry(record["source_revision"], "archive filename")
    if len(revision.parts) != 1 or revision.suffix.lower() != ".zip":
        raise ValueError("source_revision must be one ZIP filename")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", record["source_sha256"]):
        raise ValueError("source_sha256 must be a pinned SHA-256 digest")
    if not isinstance(record["source_download_url"], str) or not record["source_download_url"].startswith("https://"):
        raise ValueError("source_download_url must use HTTPS")
    runtime = record["runtime_assets"]
    if (not isinstance(runtime, dict) or not isinstance(runtime.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", runtime["sha256"])
            or type(runtime.get("file_count")) is not int or runtime["file_count"] < 1):
        raise ValueError("runtime_assets must pin a SHA-256 digest and positive file_count")
    installation = record["installation"]
    for key in ("source_entry", "profile", "output_entry"):
        if not isinstance(installation.get(key), str) or not installation[key]:
            raise ValueError(f"Scene installation needs {key}")
    relative_entry(installation["source_entry"], "source entry")
    output = relative_entry(installation["output_entry"], "output entry")
    if len(output.parts) != 1 or output.suffix.lower() != ".gltf":
        raise ValueError("output_entry must be one glTF filename")
    return record


def acquire_archive(record, destination):
    expected = record["source_sha256"].lower()
    if destination.exists():
        if destination.is_symlink() or not destination.is_file() or digest(destination) != expected:
            raise ValueError(f"Existing archive SHA-256 differs; preserve or move it manually: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".download-", dir=destination.parent) as directory:
        temporary = Path(directory) / destination.name
        checksum = hashlib.sha256()
        request = Request(record["source_download_url"], headers={"User-Agent": "restir-lab-scene-installer/1"})
        with urlopen(request, timeout=60) as source, temporary.open("xb") as target:
            while chunk := source.read(1024 * 1024):
                target.write(chunk)
                checksum.update(chunk)
        if checksum.hexdigest() != expected:
            raise ValueError(f"Downloaded archive SHA-256 differs from source_sha256: {destination.name}")
        if destination.exists():
            raise FileExistsError(f"Archive appeared during download: {destination}")
        temporary.rename(destination)


def archive_members(archive):
    """Validate the complete ZIP before extracting any entry (including Windows aliases)."""
    selected, names, prefixes = [], set(), {}
    for member in archive.infolist():
        path = relative_entry(member.orig_filename, "archive path")
        if path.parts[0].casefold() == RECORD.casefold():
            raise ValueError(f"Unsafe archive record name: {member.filename}")
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ValueError(f"Archive symlink is unsupported: {member.filename}")
        if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ValueError(f"Unsafe archive file type: {member.filename}")
        key = path.as_posix().casefold()
        if key in names:
            raise ValueError(f"Archive path collision: {member.filename}")
        names.add(key)
        for count in range(1, len(path.parts) + 1):
            prefix = PurePosixPath(*path.parts[:count]).as_posix()
            previous = prefixes.setdefault(prefix.casefold(), prefix)
            if previous != prefix:
                raise ValueError(f"Archive case collision: {member.filename}")
        selected.append((member, path))
    file_names = {path.as_posix().casefold() for member, path in selected if not member.is_dir()}
    for member, path in selected:
        if any(parent.as_posix().casefold() in file_names for parent in path.parents if parent.parts):
            raise ValueError(f"Archive file/directory collision: {member.filename}")
    return selected


def prepared_hashes(directory):
    hashes = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Prepared scene contains a symlink: {path}")
        if path.is_file() and path != directory / RECORD:
            hashes[path.relative_to(directory).as_posix()] = digest(path)
    return hashes


def prepare_archive(archive_path, destination, record):
    source_entry = record["installation"]["source_entry"]
    if destination.exists():
        try:
            marker = destination / RECORD
            if destination.is_symlink() or marker.is_symlink():
                raise ValueError("Prepared scene cannot be a symlink")
            if marker.exists():
                installed = json.loads(marker.read_text(encoding="utf-8"))
            else:
                # An independently extracted tree is adopted only after checking
                # every file against the pinned ZIP, including the source notices.
                hashes = {}
                with zipfile.ZipFile(archive_path) as archive:
                    for member, path in archive_members(archive):
                        if not member.is_dir():
                            with archive.open(member) as source:
                                hashes[path.as_posix()] = hashlib.file_digest(source, "sha256").hexdigest()
                installed = {"source_sha256": record["source_sha256"].lower(),
                             "source_entry": source_entry, "files": dict(sorted(hashes.items()))}
            matches = (not destination.is_symlink() and installed["source_sha256"] == record["source_sha256"].lower()
                       and installed["source_entry"] == source_entry
                       and installed["files"] == prepared_hashes(destination)
                       and (destination / source_entry).is_file())
            if matches and not marker.exists():
                with marker.open("x", encoding="utf-8") as stream:
                    stream.write(json.dumps(installed, indent=2) + "\n")
        except (OSError, ValueError, KeyError):
            matches = False
        if not matches:
            raise ValueError(f"Prepared scene is unverified or modified; preserve or move it manually: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        selected = archive_members(archive)
        if source_entry not in {path.as_posix() for member, path in selected if not member.is_dir()}:
            raise ValueError(f"Archive does not contain the configured source entry: {source_entry}")
        with tempfile.TemporaryDirectory(prefix=".extract-", dir=destination.parent) as directory:
            staging = Path(directory) / "scene"
            staging.mkdir()
            hashes = {}
            for member, relative in selected:
                target = staging.joinpath(*relative.parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                hashes[relative.as_posix()] = digest(target)
            installed = {"source_sha256": record["source_sha256"].lower(), "source_entry": source_entry,
                         "files": dict(sorted(hashes.items()))}
            (staging / RECORD).write_text(json.dumps(installed, indent=2) + "\n", encoding="utf-8")
            if destination.exists():
                raise FileExistsError(f"Prepared directory appeared during extraction: {destination}")
            staging.rename(destination)


def verified_conversion(source, output, profile, source_archive_sha256):
    try:
        record = json.loads(output.with_suffix(".conversion.json").read_text(encoding="utf-8"))
        matches = (not output.parent.is_symlink() and not output.is_symlink()
                   and record["profile"] == profile and record["source_sha256"] == digest(source)
                   and record.get("source_archive_sha256") == source_archive_sha256.lower()
                   and record["output_gltf"] == output.name and record["output_sha256"] == digest(output)
                   and record["resources"] == validate_bundle(output))
    except (OSError, ValueError, KeyError, IndexError):
        matches = False
    if not matches:
        raise ValueError(f"Converted scene or source archive is unverified or modified; preserve or move it manually: {output.parent}")
    return record


def install_scene(scene_id, *, root=ROOT, download_only=False, blender=None):
    root = Path(root).resolve()
    record = scene_record(scene_id, root)
    archive = root / "assets/sources" / scene_id / record["source_revision"]
    acquire_archive(record, archive)
    if download_only:
        return archive
    prepared = root / "assets/prepared" / scene_id
    prepare_archive(archive, prepared, record)
    installation = record["installation"]
    source = prepared / installation["source_entry"]
    output = root / "assets/converted" / scene_id / installation["output_entry"]
    if output.parent.exists():
        converted = verified_conversion(source, output, installation["profile"], record["source_sha256"])
    else:
        converted = convert_scene(source, output, installation["profile"], blender=blender,
                                  source_archive_sha256=record["source_sha256"])
    # The converter records validate_bundle's actual resources (including wrapper/HDR);
    # reuse above rehashes them before these values are trusted.
    files = {output.name: converted["output_sha256"], **converted["resources"]}
    closure = "".join(f"{value}  {name}\n" for name, value in sorted(files.items()))
    actual = hashlib.sha256(closure.encode("utf-8")).hexdigest()
    expected = record["runtime_assets"]
    if actual != expected["sha256"].lower() or len(files) != expected["file_count"]:
        raise ValueError(f"Runtime assets differ from the registered bundle for {scene_id}: "
                         f"expected {expected['sha256']} ({expected['file_count']} files), "
                         f"got {actual} ({len(files)} files). Use the tested conversion toolchain "
                         f"documented in scripts/assets/README.md; preserve or move {output.parent} "
                         "manually before reconverting. No existing files were overwritten.")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--download-only", action="store_true", help="Verify/download the pinned archive without extraction or conversion")
    parser.add_argument("--blender", help="Blender executable used when conversion is needed")
    args = parser.parse_args()
    try:
        output = install_scene(args.scene, download_only=args.download_only, blender=args.blender)
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Scene installation failed: {exc}\n")
    print(output)


if __name__ == "__main__":
    main()
