"""ORCA profile: specular slots carry ORM; normals use DirectX green orientation."""
from copy import deepcopy

from PIL import Image, ImageOps

from gltf import remove_extension, resource_path, texture_infos


def convert_materials(gltf, directory):
    images, textures = gltf.get("images", []), gltf.get("textures", [])
    counts = dict(packed_orm_materials=0, normal_materials=0,
                  dropped_textures_without_uv=0, discarded_specular_color_materials=0)
    flipped_images, flipped_textures = {}, {}
    for material in gltf.get("materials", []):
        extension = material.get("extensions", {}).pop("KHR_materials_specular", None)
        if extension:
            if set(extension) == {"specularTexture"}:
                packed = extension["specularTexture"]
                if packed.get("texCoord", 0) >= 0:
                    pbr = material.setdefault("pbrMetallicRoughness", {})
                    pbr.update(metallicRoughnessTexture=deepcopy(packed), roughnessFactor=1., metallicFactor=1.)
                    material["occlusionTexture"] = deepcopy(packed)
                    counts["packed_orm_materials"] += 1
                else:
                    counts["dropped_textures_without_uv"] += 1
            elif set(extension) == {"specularColorFactor"}:
                # Keep the previous ORCA approximation explicit in the conversion record.
                counts["discarded_specular_color_materials"] += 1
            else:
                raise ValueError(f"Unexpected ORCA specular fields in {material.get('name')}: {list(extension)}")
        if material.get("extensions") == {}:
            del material["extensions"]
        for parent, key in list(texture_infos(material)):
            if parent[key].get("texCoord", 0) < 0:
                del parent[key]
                counts["dropped_textures_without_uv"] += 1

        normal = material.get("normalTexture")
        if normal is None:
            continue
        texture_index = normal["index"]
        if texture_index not in flipped_textures:
            texture = textures[texture_index]
            source_index = texture["source"]
            if source_index not in flipped_images:
                source = images[source_index]
                path = directory / f"resources/normal-{source_index:04d}.png"
                with Image.open(resource_path(directory, source["uri"])) as original:
                    r, g, b, a = original.convert("RGBA").split()
                    Image.merge("RGBA", (r, ImageOps.invert(g), b, a)).save(path)
                images.append({"mimeType": "image/png", "uri": path.relative_to(directory).as_posix()})
                flipped_images[source_index] = len(images) - 1
            converted = deepcopy(texture)  # Preserve this texture's sampler, even when images are shared.
            converted["source"] = flipped_images[source_index]
            textures.append(converted)
            flipped_textures[texture_index] = len(textures) - 1
        normal["index"] = flipped_textures[texture_index]
        counts["normal_materials"] += 1
    if not counts["packed_orm_materials"]:
        raise ValueError("No packed specular/ORM maps found; check the ORCA material convention")
    remove_extension(gltf, "KHR_materials_specular")
    return counts
