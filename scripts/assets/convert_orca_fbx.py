"""Convert Blender-exported ORCA FBX/DDS materials into a self-contained glTF.

Profile: specular R=occlusion, G=roughness, B=metallic; DirectX normal maps.
This is not a general-purpose FBX material converter. Source files stay unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from gltf import bake_texture_transforms, digest, emissive_triangle_count, resource_path
from orca_materials import convert_materials


def find_blender(explicit):
    if explicit:
        path = Path(explicit).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Blender executable not found: {path}")
        return path
    found = shutil.which("blender")
    if found:
        return Path(found)
    versions = list(Path("C:/Program Files/Blender Foundation").glob("Blender */blender.exe"))
    if versions:
        return max(versions, key=lambda p: tuple(map(int, re.findall(r"\d+", p.parent.name))))
    raise FileNotFoundError("Blender not found; pass --blender PATH")


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


def convert(raw, output, expected_emissive=None):
    raw, output = raw.resolve(), output.resolve()
    if raw == output:
        raise ValueError("Output must differ from the raw glTF")
    gltf = json.loads(raw.read_text(encoding="utf-8"))
    output.parent.mkdir(parents=True, exist_ok=True)
    # Everything below this directory is created by this invocation and disposable.
    with tempfile.TemporaryDirectory(prefix=".orca-", dir=output.parent) as temporary:
        staging = Path(temporary)
        copy_resources(gltf, raw.parent, staging)
        counts = convert_materials(gltf, staging)
        baked, accessors = bake_texture_transforms(gltf, staging)
        count = emissive_triangle_count(gltf)
        if expected_emissive is not None and count != expected_emissive:
            raise ValueError(f"Expected {expected_emissive} emissive triangles, found {count}")

        hashes = resource_hashes(staging / "resources")
        bundle = "".join(f"{value}  {name}\n" for name, value in hashes.items())
        resource_name = "rtxdi-" + hashlib.sha256(bundle.encode()).hexdigest()[:16]
        destination = output.parent / resource_name
        for field in ("images", "buffers"):
            for entry in gltf.get(field, []):
                entry["uri"] = resource_name + "/" + Path(entry["uri"]).name
        prepared = staging / "converted.gltf"
        prepared.write_text(json.dumps(gltf, separators=(",", ":")) + "\n", encoding="utf-8")
        summary = {"source_gltf": str(raw), "source_sha256": digest(raw), "output_gltf": str(output),
                   "output_sha256": digest(prepared), "materials": len(gltf.get("materials", [])),
                   **counts, "uv_baked_primitives": baked, "uv_baked_accessors": accessors,
                   "emissive_triangles": count, "images": len(gltf.get("images", [])),
                   "resources": {resource_name + "/" + name: value for name, value in hashes.items()}}
        if destination.exists():
            if not destination.is_dir() or resource_hashes(destination) != hashes:
                raise ValueError(f"Existing resource bundle is modified: {destination}")
        else:
            (staging / "resources").rename(destination)
        prepared.replace(output)
        output.with_suffix(".conversion.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return summary


def export_fbx(source, target, blender, log_path):
    script = Path(__file__).with_name("blender_export_fbx.py")
    with log_path.open("w", encoding="utf-8") as log:
        subprocess.run([str(blender), "--background", "--factory-startup", "--threads", "4",
                        "--python-exit-code", "1", "--python", str(script), "--", str(source), str(target)],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    if not target.is_file():
        raise RuntimeError(f"Blender produced no glTF; inspect {log_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fbx", type=Path, help="FBX to import using Blender")
    source.add_argument("--raw-gltf", type=Path, help="Existing Blender glTF export with ORCA material slots")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--blender", help="Blender executable")
    parser.add_argument("--expected-emissive-triangles", type=int)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.suffix.lower() != ".gltf":
        parser.error("--output must end in .gltf")
    if args.expected_emissive_triangles is not None and args.expected_emissive_triangles < 0:
        parser.error("--expected-emissive-triangles must be nonnegative")
    try:
        if args.fbx:
            fbx = args.fbx.resolve()
            if not fbx.is_file():
                raise FileNotFoundError(fbx)
            blender = find_blender(args.blender)
            output.parent.mkdir(parents=True, exist_ok=True)
            # Export textures privately: Blender may reuse filenames between different FBXs.
            with tempfile.TemporaryDirectory(prefix=".blender-", dir=output.parent) as temporary:
                raw = Path(temporary) / "raw.gltf"
                export_fbx(fbx, raw, blender, output.with_suffix(".blender.log"))
                summary = convert(raw, output, args.expected_emissive_triangles)
                summary["source_gltf"] = "temporary Blender export"
                summary.update(source_fbx=str(fbx), source_fbx_sha256=digest(fbx),
                               blender_version=subprocess.check_output([str(blender), "--version"], text=True).splitlines()[0])
                output.with_suffix(".conversion.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        else:
            summary = convert(args.raw_gltf, output, args.expected_emissive_triangles)
    except (OSError, ValueError, KeyError, IndexError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Conversion failed: {exc}\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "resources"}, indent=2))


if __name__ == "__main__":
    main()
