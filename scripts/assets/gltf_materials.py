"""Conservative, scene-independent alpha classification for separate glTF assets."""
from PIL import Image

from gltf import resource_path


def _has_extensions(value):
    if isinstance(value, dict):
        return bool(value.get("extensions")) or any(_has_extensions(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_extensions(v) for v in value)
    return False


def _image_is_opaque(path):
    """Return None when decoding could hide alpha precision, mip levels or animation."""
    with Image.open(path) as image:
        if image.format not in ("PNG", "JPEG") or getattr(image, "n_frames", 1) != 1:
            return None
        if image.format == "PNG":
            with path.open("rb") as stream:
                header = stream.read(25)
            # Pillow can reduce 16-bit RGBA to 8-bit, rounding near-opaque alpha to 255.
            if len(header) != 25 or header[24] > 8:
                return None
        return image.convert("RGBA").getchannel("A").getextrema() == (255, 255)


def normalize_opaque_materials(gltf, directory):
    """Promote only proven opaque BLEND materials; retain unknown cases with reasons.

    Supports core glTF with static PNG/JPEG textures. RGBA vertex colors, extensions
    and other texture encodings are retained conservatively, without guessing intent.
    """
    protected = {}
    for mesh in gltf.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            material = primitive.get("material")
            if _has_extensions(primitive):
                protected[material] = "primitive_extension"
            color = primitive.get("attributes", {}).get("COLOR_0")
            if color is not None and gltf["accessors"][color].get("type") != "VEC3":
                protected[material] = "vertex_alpha"

    extensions = bool(gltf.get("extensionsUsed") or gltf.get("extensionsRequired") or gltf.get("extensions"))
    animated_materials = any(
        _has_extensions(channel.get("target", {})) or channel.get("target", {}).get("path") == "pointer"
        for animation in gltf.get("animations", []) for channel in animation.get("channels", []))
    images, textures = gltf.get("images", []), gltf.get("textures", [])
    opaque_images = {}
    converted, retained = [], []
    for index, material in enumerate(gltf.get("materials", [])):
        if material.get("alphaMode", "OPAQUE") != "BLEND":
            continue
        pbr = material.get("pbrMetallicRoughness", {})
        reason = protected.get(index)
        if extensions or _has_extensions(material):
            reason = "unverified_extensions"
        if animated_materials:
            reason = "material_animation"
        if pbr.get("baseColorFactor", [1, 1, 1, 1])[3] != 1:
            reason = "factor_alpha"
        info = pbr.get("baseColorTexture")
        if reason is None and info is not None:
            texture = textures[info["index"]]
            source = texture.get("source")
            if _has_extensions(texture) or source is None:
                reason = "unverified_texture"
            else:
                image = images[source]
                if _has_extensions(image) or "uri" not in image:
                    reason = "unverified_texture"
                else:
                    if source not in opaque_images:
                        opaque_images[source] = _image_is_opaque(resource_path(directory, image["uri"]))
                    opaque = opaque_images[source]
                    if opaque is not True:
                        reason = "texture_alpha" if opaque is False else "unverified_texture"
        if reason is not None:
            retained.append({"material": index, "reason": reason})
            continue
        material["alphaMode"] = "OPAQUE"
        converted.append(index)
    return {"converted": converted, "retained_blend": retained}
