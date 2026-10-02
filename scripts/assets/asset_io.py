"""Resource copying and validation for self-contained separate glTF bundles."""
import json
import shutil
from gltf import digest, resource_path


def copy_resources(gltf, source_dir, staging):
    resources = staging / "resources"
    resources.mkdir()
    for field, prefix in (("buffers", "buffer"), ("images", "image")):
        for index, entry in enumerate(gltf.get(field, [])):
            if "uri" not in entry:
                raise ValueError("Expected separate glTF with local buffers and image files")
            source = resource_path(source_dir, entry["uri"])
            suffix = source.suffix.lower() if field == "images" else ".bin"
            if field == "images" and suffix not in {".png", ".jpg", ".jpeg", ".dds"}:
                raise ValueError(f"Unsupported image format: {source.name}")
            target = resources / f"{prefix}-{index:04d}{suffix}"
            shutil.copyfile(source, target)
            entry["uri"] = target.relative_to(staging).as_posix()


def resource_hashes(directory):
    return {p.name: digest(p) for p in sorted(directory.iterdir()) if p.is_file()}


def validate_bundle(output):
    document = json.loads(output.read_text(encoding="utf-8"))
    hashes = {}
    for field in ("buffers", "images"):
        for entry in document.get(field, []):
            if "uri" not in entry:
                raise ValueError("Expected separate glTF resources with local URIs")
            path = resource_path(output.parent, entry["uri"])
            hashes[entry["uri"]] = digest(path)
    wrapper = output.with_suffix(".scene.json")
    if wrapper.exists():
        scene = json.loads(wrapper.read_text(encoding="utf-8"))
        if scene.get("models") != [output.name]:
            raise ValueError("Scene wrapper must reference the converted glTF")
        hashes[wrapper.name] = digest(wrapper)
    return hashes
