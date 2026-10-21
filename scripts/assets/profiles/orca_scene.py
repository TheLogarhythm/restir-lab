"""ORCA FBX scene additions: read Falcor settings as data, retain HDR and emission."""
import json
import math
import re
import shutil
from gltf import resource_path


def source_settings(source):
    description = source.with_suffix(".pyscene")
    text = description.read_text(encoding="utf-8")
    maps = re.findall(r'sceneBuilder\.envMap\s*=\s*EnvMap\(\s*[\"\']([^\"\']+)[\"\']\s*\)', text)
    if len(maps) != 1:
        raise ValueError("Expected one source environment map in the ORCA .pyscene")
    environment = resource_path(source.parent, maps[0])
    scales = re.findall(r'm\.emissiveFactor\s*\*=\s*([0-9.eE+-]+)', text)
    if len(scales) > 1:
        raise ValueError("Ambiguous ORCA source emissive scaling")
    scale = float(scales[0]) if scales else 1.0
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Source emissive multiplier must be positive and finite")
    return {"environment": environment, "emissive_scale": scale}


def finish_scene(source, output, metadata):
    settings = source_settings(source)
    document = json.loads(output.read_text(encoding="utf-8"))
    scale = settings["emissive_scale"]
    if scale != 1:
        for material in document.get("materials", []):
            if any(material.get("emissiveFactor", [])):
                extension = material.setdefault("extensions", {}).setdefault(
                    "KHR_materials_emissive_strength", {"emissiveStrength": 1.0})
                extension["emissiveStrength"] *= scale
        used = document.setdefault("extensionsUsed", [])
        if "KHR_materials_emissive_strength" not in used:
            used.append("KHR_materials_emissive_strength")
    output.write_text(json.dumps(document, separators=(",", ":")) + "\n", encoding="utf-8")
    shutil.copyfile(settings["environment"], output.parent / "environment.hdr")
    wrapper = {"models": [output.name], "graph": [{"name": source.stem, "model": 0}],
               "environmentMaps": ["environment.hdr"]}
    output.with_suffix(".scene.json").write_text(json.dumps(wrapper, indent=2) + "\n", encoding="utf-8")
    return {**metadata, "source_environment": settings["environment"].name,
            "source_emissive_multiplier": scale,
            "limitations": ["FBX material and punctual-light import follows Blender's conversion; not exact Falcor equivalence",
                            "Static source view; animation is omitted"]}
