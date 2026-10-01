"""Preserve glTF emission when source meshes lack texture coordinates."""
import math

from PIL import Image

from gltf import resource_path


def _nonnegative(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def _constant_rgb(path, context):
    with Image.open(path) as image:
        if image.format not in ("PNG", "JPEG") or getattr(image, "n_frames", 1) != 1:
            raise ValueError(f"{context}: unsupported emissive image encoding or animation")
        if image.format == "PNG":
            with path.open("rb") as stream:
                header = stream.read(25)
            if len(header) != 25 or header[24] > 8:
                raise ValueError(f"{context}: unsupported emissive image precision")
        if image.mode not in ("RGB", "RGBA", "L", "LA", "P", "1"):
            raise ValueError(f"{context}: unsupported emissive image precision")
        extrema = image.convert("RGB").getextrema()
        if any(low != high for low, high in extrema):
            raise ValueError(f"{context}: nonconstant emissive texture requires valid UVs")
        color = [low / 255 for low, _ in extrema]
    return [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in color]


def preserve_emission(gltf, directory):
    """Fold only provably constant textures; fail instead of inventing missing UVs."""
    for animation in gltf.get("animations", []):
        for channel in animation.get("channels", []):
            pointer = channel.get("target", {}).get("extensions", {}).get("KHR_animation_pointer", {}).get("pointer", "")
            if pointer.startswith("/materials/") and "emissive" in pointer:
                raise ValueError("Unsupported animated emissive material semantics")

    uses = {}
    for mesh_index, mesh in enumerate(gltf.get("meshes", [])):
        for primitive in mesh.get("primitives", []):
            uses.setdefault(primitive.get("material"), []).append(
                (mesh.get("name", f"mesh {mesh_index}"), primitive.get("attributes", {})))

    folded = []
    for index, material in enumerate(gltf.get("materials", [])):
        name = material.get("name", f"material {index}")
        factor = material.get("emissiveFactor", [0, 0, 0])
        if len(factor) != 3 or not all(_nonnegative(v) and v <= 1 for v in factor):
            raise ValueError(f"{name}: invalid emissiveFactor (expected three finite values in [0, 1])")
        extensions = material.get("extensions", {})
        strength = extensions.get("KHR_materials_emissive_strength", {})
        if set(strength) - {"emissiveStrength"}:
            raise ValueError(f"Unsupported emissive strength fields in {name}")
        if not _nonnegative(strength.get("emissiveStrength", 1)):
            raise ValueError(f"{name}: invalid emissiveStrength")
        if "KHR_materials_unlit" in extensions and (any(factor) or "emissiveTexture" in material):
            raise ValueError(f"Unsupported unlit emissive material semantics in {name}")
        info = material.get("emissiveTexture")
        if info is None:
            continue
        if set(info.get("extensions", {})) - {"KHR_texture_transform"}:
            raise ValueError(f"Unsupported emissive texture extension in {name}")
        texture = gltf["textures"][info["index"]]
        if texture.get("extensions") or "source" not in texture:
            raise ValueError(f"Unsupported emissive texture source in {name}")
        image = gltf["images"][texture["source"]]
        if image.get("extensions") or "uri" not in image:
            raise ValueError(f"Unsupported emissive image source in {name}")
        transform = info.get("extensions", {}).get("KHR_texture_transform", {})
        uv = transform.get("texCoord", info.get("texCoord", 0))
        if not isinstance(uv, int) or isinstance(uv, bool):
            raise ValueError(f"{name}: invalid emissive texCoord")
        affected = [mesh for mesh, attrs in uses.get(index, [])
                    if uv < 0 or f"TEXCOORD_{uv}" not in attrs]
        if uv >= 0 and not affected:
            continue
        context = f"{name} ({', '.join(dict.fromkeys(affected)) or 'unresolved UV set'})"
        color = _constant_rgb(resource_path(directory, image["uri"]), context)
        material["emissiveFactor"] = [f * c for f, c in zip(factor, color)]
        del material["emissiveTexture"]
        folded.append(name)
    return folded
