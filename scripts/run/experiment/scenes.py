"""Scene registration, camera validation and the exact runtime asset closure."""
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys

from rtxdi_common import ROOT, sha
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.assets.gltf import resource_path

ACTIVE_SCENES = ("cornell-box", "arcade", "bistro")


def registered_scenes(root=ROOT):
    document = json.loads((root / "scenes/manifest.yaml").read_text(encoding="utf-8"))
    return {s["id"]: s for s in document["scenes"] if s.get("backend_configs", {}).get("rtxdi")}


def vector(value, name):
    if not isinstance(value, list) or len(value) != 3 or not all(
            isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in value):
        raise ValueError(f"{name} must have three finite coordinates")
    return value


def validate_scene(scene):
    if scene["schema_version"] != 2 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", scene["scene_id"]):
        raise ValueError("Invalid scene version or ID")
    source = scene["source"]
    if source["kind"] not in ("builtin", "file"):
        raise ValueError("Scene source kind must be builtin or file")
    if source["kind"] == "builtin" and source["asset"] not in ("CornellBox", "Arcade", "Bistro", "BistroMirror"):
        raise ValueError("Unknown upstream scene asset; use a file source for new scenes")
    camera = scene["camera"]
    vector(camera["position"], "camera.position")
    direction, up = vector(camera["direction"], "camera.direction"), vector(camera["up"], "camera.up")
    cross = [direction[1]*up[2]-direction[2]*up[1],
             direction[2]*up[0]-direction[0]*up[2],
             direction[0]*up[1]-direction[1]*up[0]]
    if not all(math.isfinite(x) for x in cross) or sum(x*x for x in cross) < 1e-12:
        raise ValueError("Camera direction/up must be nonzero and not parallel")
    if not math.isfinite(camera["vertical_fov"]) or not 0 < camera["vertical_fov"] < 180:
        raise ValueError("Camera vertical_fov must be in (0, 180) degrees")
    vector(scene["motion"]["end_position"], "motion.end_position")
    lighting = scene["lighting"]
    if lighting["environment"] != "procedural":
        raise ValueError("Only the pinned sample's procedural environment is currently supported")
    for key in ("environment_intensity_ev", "environment_rotation_degrees", "emissive_scale"):
        if not isinstance(lighting[key], (int, float)) or not math.isfinite(lighting[key]):
            raise ValueError(f"Non-finite lighting setting: {key}")
    if lighting["emissive_scale"] <= 0:
        raise ValueError("emissive_scale must be positive")
    for value in (lighting["environment_intensity_ev"], scene["preview"]["exposure_ev"]):
        if not math.isfinite(value) or not -32 <= value <= 32:
            raise ValueError("Exposure must be finite and between -32 and 32 EV")


def load_scene(scene_id, root=ROOT):
    records = registered_scenes(root)
    if scene_id not in records:
        raise ValueError(f"Unknown/unconfigured scene {scene_id!r}; available: {', '.join(records)}")
    record = records[scene_id]
    path = resource_path(root, record["backend_configs"]["rtxdi"])
    scene = json.loads(path.read_text(encoding="utf-8"))
    validate_scene(scene)
    if scene["scene_id"] != scene_id:
        raise ValueError("Scene configuration ID differs from its registry entry")
    scene = copy.deepcopy(scene)
    asset_root = resource_path(root, scene["source"]["root"])
    entry = resource_path(asset_root, scene["source"]["entry"])
    scene["source"].update(root=asset_root.relative_to(root).as_posix(), path=entry.relative_to(root).as_posix())
    scene["registry"] = record
    scene["config_sha256"] = sha(path)
    return scene


def scene_arguments(scene):
    camera, source = scene["camera"], scene["source"]
    # File sources bypass the built-in asset switch; startup camera is still explicit.
    return {"scene.asset": source.get("asset", "CornellBox"), "scene.animation": 0,
            "camera.position": " ".join(map(str, camera["position"])),
            "camera.direction": " ".join(map(str, camera["direction"]))}


def asset_files(entry, root):
    """Hash the wrapper, referenced models, buffers, textures and optional environment maps."""
    root, entry = Path(root).resolve(), Path(entry).resolve()
    files = {}
    visited = set()

    def add(path, document=False):
        path = path.resolve()
        if not path.is_relative_to(root):
            raise ValueError("Scene resource escapes its asset root")
        if path in visited:
            return
        visited.add(path)
        if not path.is_file():
            raise ValueError(f"Missing scene resource: {path}")
        with path.open("rb") as stream:
            if stream.read(80).startswith(b"version https://git-lfs.github.com/spec/v1"):
                raise ValueError(f"Unresolved Git LFS asset: {path}")
        files[path.relative_to(root).as_posix()] = sha(path)
        if not document:
            return
        text = path.read_text(encoding="utf-8")
        if path.name.endswith(".scene.json"):
            # Donut's JsonCpp scene files allow comments and trailing commas.
            # Match strings first so their contents are never rewritten.
            string = r'"(?:\\.|[^"\\])*"'
            text = re.sub(string + r"|//[^\n]*|/\*.*?\*/",
                          lambda m: m[0] if m[0].startswith('"') else " ", text, flags=re.S)
            text = re.sub(string + r"|,\s*(?=[}\]])",
                          lambda m: m[0] if m[0].startswith('"') else "", text)
        data = json.loads(text)
        if path.name.endswith(".scene.json"):
            for uri in data.get("models", []):
                add(resource_path(path.parent, uri, root=root), document=True)
            for uri in data.get("environmentMaps", []):
                add(resource_path(path.parent, uri, root=root))
            def profiles(node):
                if isinstance(node, dict):
                    if isinstance(node.get("profile"), str):
                        add(resource_path(root / "ies-profiles", node["profile"], root=root))
                    for child in node.values():
                        profiles(child)
                elif isinstance(node, list):
                    for child in node:
                        profiles(child)
            profiles(data.get("graph", []))
        elif path.suffix.lower() == ".gltf":
            for field in ("buffers", "images"):
                for item in data.get(field, []):
                    uri = item.get("uri")
                    if uri is not None:
                        # Embedded resources are covered by the containing glTF hash.
                        if not uri.startswith("data:"):
                            resource = resource_path(path.parent, uri, root=root)
                            # The pinned Donut importer prefers same-stem DDS textures.
                            if field == "images" and resource.with_suffix(".dds").is_file():
                                resource = resource.with_suffix(".dds")
                            add(resource)
        else:
            raise ValueError(f"Unsupported scene document: {path.name}")

    add(entry, document=True)
    return dict(sorted(files.items()))


def bundle_digest(files):
    text = "".join(f"{digest}  {name}\n" for name, digest in sorted(files.items()))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_assets(scene, root=ROOT):
    files = asset_files(resource_path(root, scene["source"]["path"]),
                        resource_path(root, scene["source"]["root"]))
    digest = bundle_digest(files)
    expected = scene["registry"].get("runtime_assets")
    if not expected or digest != expected["sha256"] or len(files) != expected["file_count"]:
        raise ValueError(f"Runtime assets differ from the registered bundle for {scene['scene_id']}")
    return {"registry": scene["registry"], "file_sha256": files, "sha256": digest}
