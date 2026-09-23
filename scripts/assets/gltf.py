"""Local glTF resources, UV baking, and scene-instance light counts."""
import hashlib
import math
import struct
from urllib.parse import unquote, urlsplit


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def resource_path(directory, uri):
    parsed = urlsplit(uri)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError(f"Only local relative resource URIs are supported: {uri[:80]}")
    decoded = unquote(parsed.path)
    if not decoded or "\\" in decoded or ":" in decoded or decoded.startswith("/"):
        raise ValueError(f"Invalid relative resource URI: {uri[:80]}")
    path = (directory / decoded).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError(f"Resource URI escapes its directory: {uri[:80]}")
    return path


def texture_infos(material):
    for parent, keys in ((material, ("normalTexture", "occlusionTexture", "emissiveTexture")),
                         (material.get("pbrMetallicRoughness", {}), ("baseColorTexture", "metallicRoughnessTexture"))):
        for key in keys:
            if key in parent:
                yield parent, key


def remove_extension(gltf, name):
    for field in ("extensionsUsed", "extensionsRequired"):
        remaining = [item for item in gltf.get(field, []) if item != name]
        if remaining:
            gltf[field] = remaining
        else:
            gltf.pop(field, None)


def _transform(info):
    transform = info.get("extensions", {}).get("KHR_texture_transform", {})
    if transform.get("texCoord", info.get("texCoord", 0)) != 0:
        raise ValueError("Only texCoord 0 is supported by this conversion")
    scale, offset = transform.get("scale", [1, 1]), transform.get("offset", [0, 0])
    if len(scale) != 2 or len(offset) != 2:
        raise ValueError("UV scale and offset must have two components")
    result = (*scale, *offset, transform.get("rotation", 0))
    if not all(math.isfinite(value) for value in result):
        raise ValueError("Non-finite UV transform")
    return result


def bake_texture_transforms(gltf, directory):
    """Bake one common transform into UV0; reject unsupported per-slot UVs."""
    transforms = {}
    for index, material in enumerate(gltf.get("materials", [])):
        infos = [parent[key] for parent, key in texture_infos(material)]
        variants = {_transform(info) for info in infos}
        if len(variants) > 1:
            raise ValueError(f"Material {material.get('name', index)} has incompatible per-texture UV transforms")
        if variants:
            transforms[index] = variants.pop()
        for info in infos:
            info.get("extensions", {}).pop("KHR_texture_transform", None)
            if info.get("extensions") == {}:
                del info["extensions"]

    encoded = bytearray()
    cache, source_buffers = {}, {}
    baked = 0
    for mesh in gltf.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            transform = transforms.get(primitive.get("material"))
            if transform is None:
                continue
            attributes = primitive.get("attributes", {})
            if "TEXCOORD_0" not in attributes:
                raise ValueError("Textured primitive has no TEXCOORD_0")
            if transform == (1, 1, 0, 0, 0):
                continue
            if "TANGENT" in attributes:
                raise ValueError("UV baking with exported tangents is unsupported; export without tangents")
            source = attributes["TEXCOORD_0"]
            key = (source, transform)
            if key not in cache:
                accessor = gltf["accessors"][source]
                if accessor["componentType"] != 5126 or accessor["type"] != "VEC2" or "sparse" in accessor:
                    raise ValueError("Expected ordinary float VEC2 UV accessors")
                view = gltf["bufferViews"][accessor["bufferView"]]
                buffer_index = view["buffer"]
                if buffer_index not in source_buffers:
                    source_buffers[buffer_index] = resource_path(directory, gltf["buffers"][buffer_index]["uri"]).read_bytes()
                data = source_buffers[buffer_index]
                offset = accessor.get("byteOffset", 0)
                stride, count = view.get("byteStride", 8), accessor["count"]
                begin = view.get("byteOffset", 0) + offset
                if count <= 0 or stride < 8 or offset < 0 or begin < 0:
                    raise ValueError("Invalid UV accessor layout")
                if offset + (count - 1) * stride + 8 > view["byteLength"] or begin + (count - 1) * stride + 8 > len(data):
                    raise ValueError("UV accessor exceeds its buffer view")
                sx, sy, ox, oy, angle = transform
                cosine, sine = math.cos(angle), math.sin(angle)
                start = len(encoded)
                smallest, largest = [math.inf, math.inf], [-math.inf, -math.inf]
                for vertex in range(count):
                    u, v = struct.unpack_from("<ff", data, begin + vertex * stride)
                    x = cosine * sx * u - sine * sy * v + ox
                    y = sine * sx * u + cosine * sy * v + oy
                    if not math.isfinite(x) or not math.isfinite(y):
                        raise ValueError("Non-finite transformed UV")
                    encoded.extend(struct.pack("<ff", x, y))
                    smallest = [min(smallest[0], x), min(smallest[1], y)]
                    largest = [max(largest[0], x), max(largest[1], y)]
                gltf["bufferViews"].append({"buffer": len(gltf["buffers"]), "byteOffset": start,
                                            "byteLength": len(encoded) - start, "target": 34962})
                gltf["accessors"].append({"bufferView": len(gltf["bufferViews"]) - 1, "componentType": 5126,
                                          "count": count, "type": "VEC2", "min": smallest, "max": largest})
                cache[key] = len(gltf["accessors"]) - 1
            attributes["TEXCOORD_0"] = cache[key]
            baked += 1
    if encoded:
        path = directory / "resources/uv.bin"
        path.write_bytes(encoded)
        gltf["buffers"].append({"byteLength": len(encoded), "uri": "resources/uv.bin"})
    remove_extension(gltf, "KHR_texture_transform")
    return baked, len(cache)


def emissive_triangle_count(gltf):
    """Count emissive triangles instantiated in the default scene, not mesh definitions."""
    mesh_counts = []
    for mesh in gltf.get("meshes", []):
        count = 0
        for primitive in mesh.get("primitives", []):
            material = gltf["materials"][primitive["material"]] if "material" in primitive else {}
            strength = material.get("extensions", {}).get("KHR_materials_emissive_strength", {}).get("emissiveStrength", 1)
            if strength <= 0 or not any(v > 0 for v in material.get("emissiveFactor", [0, 0, 0])):
                continue
            if primitive.get("mode", 4) != 4:
                raise ValueError("An emissive primitive is not triangles")
            index = primitive.get("indices", primitive["attributes"]["POSITION"])
            vertices = gltf["accessors"][index]["count"]
            if vertices % 3:
                raise ValueError("Triangle primitive count is not divisible by three")
            count += vertices // 3
        mesh_counts.append(count)
    scenes = gltf.get("scenes", [])
    pending = list(scenes[gltf.get("scene", 0)].get("nodes", [])) if scenes else []
    visited, total = set(), 0
    while pending:
        index = pending.pop()
        if index in visited:
            raise ValueError("Scene graph contains a cycle or a multiply referenced node")
        visited.add(index)
        node = gltf["nodes"][index]
        if "mesh" in node:
            total += mesh_counts[node["mesh"]]
        pending.extend(node.get("children", []))
    return total
