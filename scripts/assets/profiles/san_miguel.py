"""McGuire OBJ profile: restore embedded foliage alpha without adding lights."""
import json
from PIL import Image
from asset_io import copy_resources
from gltf import resource_path
from gltf_materials import normalize_opaque_materials


def prepare(raw, output):
    document = json.loads(raw.read_text(encoding="utf-8"))
    copy_resources(document, raw.parent, output.parent)
    masked = []
    for index, material in enumerate(document.get("materials", [])):
        texture = material.get("pbrMetallicRoughness", {}).get("baseColorTexture")
        if not texture or material.get("alphaMode", "OPAQUE") != "OPAQUE":
            continue
        source = document["textures"][texture["index"]]["source"]
        path = resource_path(output.parent, document["images"][source]["uri"])
        with Image.open(path) as image:
            if image.format == "PNG" and image.convert("RGBA").getchannel("A").getextrema()[0] < 255:
                material.update(alphaMode="MASK", alphaCutoff=0.5)
                masked.append(index)
    alpha = normalize_opaque_materials(document, output.parent)
    output.write_text(json.dumps(document, separators=(",", ":")) + "\n", encoding="utf-8")
    return {"cutout_materials": masked, "alpha_normalization": alpha,
            "limitations": ["OBJ-to-PBR roughness/specular conversion is approximate"]}
