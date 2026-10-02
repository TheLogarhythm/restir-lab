"""ORCA FBX/DDS material profile (ORM packing and DirectX normals)."""
import hashlib
import json
from pathlib import Path
import tempfile
from asset_io import copy_resources, resource_hashes
from gltf import bake_texture_transforms, digest, emissive_triangle_count
from gltf_materials import normalize_opaque_materials
from orca_materials import convert_materials


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
        alpha_normalization = normalize_opaque_materials(gltf, staging)
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
                   **counts, "alpha_normalization": alpha_normalization,
                   "uv_baked_primitives": baked, "uv_baked_accessors": accessors,
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


