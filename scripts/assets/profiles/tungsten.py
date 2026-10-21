"""Veach Ajar's Tungsten subset to glTF, retaining authored geometry and radiance.

WO3 layout and YXZ rotations follow tunabrain/tungsten's MeshIO.cpp,
Vertex.hpp, Triangle.hpp and Mat4f.cpp; camera FOV follows PinholeCamera.cpp.
Unsupported scene features fail rather than silently changing their meaning.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import shutil
import struct

from PIL import Image

from gltf import digest, resource_path


def _vector(value, name, *, scalar=False, minimum=None, maximum=None):
    if scalar and isinstance(value, (int, float)) and not isinstance(value, bool):
        value = [value] * 3
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must have three components")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           or (minimum is not None and v < minimum) or (maximum is not None and v > maximum) for v in value):
        raise ValueError(f"{name} has invalid or nonfinite components")
    return list(value)


def _normalize(value):
    length = math.sqrt(sum(v * v for v in value))
    if length <= 1e-12:
        raise ValueError("Degenerate normal or camera direction")
    return [v / length for v in value]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def read_wo3(path):
    """Read the little-endian WO3 ABI used by Bitterli's resource archive."""
    data = Path(path).read_bytes()
    if len(data) < 16:
        raise ValueError(f"Truncated WO3 mesh: {path}")
    count = struct.unpack_from("<Q", data)[0]
    offset = 8 + count * 32
    if not count or offset + 8 > len(data):
        raise ValueError(f"Invalid WO3 vertex count: {path}")
    triangles = struct.unpack_from("<Q", data, offset)[0]
    if not triangles or offset + 8 + triangles * 16 != len(data):
        raise ValueError(f"Invalid WO3 triangle count or file length: {path}")
    vertices = list(struct.iter_unpack("<8f", memoryview(data)[8:offset]))
    if any(not math.isfinite(v) for vertex in vertices for v in vertex):
        raise ValueError(f"WO3 attributes must be finite: {path}")
    faces = [face[:3] for face in struct.iter_unpack("<IIIi", memoryview(data)[offset + 8:])]
    if any(index >= count for face in faces for index in face):
        raise ValueError(f"WO3 triangle index is outside the vertex array: {path}")
    # A Tungsten primitive with one BSDF overrides the source mesh's material IDs.
    return vertices, faces


def _transform(value):
    if not isinstance(value, dict) or set(value) - {"position", "rotation", "scale"}:
        raise ValueError("Only position/rotation/scale mesh transforms are supported")
    position = _vector(value.get("position", [0, 0, 0]), "position")
    scale = _vector(value.get("scale", 1), "scale", scalar=True, minimum=1e-12)
    x, y, z = [math.radians(v) for v in _vector(value.get("rotation", [0, 0, 0]), "rotation")]
    cx, cy, cz, sx, sy, sz = math.cos(x), math.cos(y), math.cos(z), math.sin(x), math.sin(y), math.sin(z)
    # Tungsten's convention is Ry(-y) * Rx(x) * Rz(z), followed by scale.
    rows = [[cy * cz - sy * sx * sz, -cy * sz - sy * sx * cz, -sy * cx],
            [cx * sz, cx * cz, -sx],
            [sy * cz + cy * sx * sz, -sy * sz + cy * sx * cz, cy * cx]]
    return [rows[r][c] * scale[c] if r < 3 and c < 3 else position[r] if c == 3 and r < 3
            else 1 if r == c else 0 for c in range(4) for r in range(4)]


def _camera(value):
    if value.get("type") != "pinhole":
        raise ValueError("Only Tungsten pinhole cameras are supported")
    transform = value["transform"]
    if set(transform) - {"position", "look_at", "up"}:
        raise ValueError("Camera requires position/look_at/up")
    position = _vector(transform["position"], "camera position")
    target = _vector(transform["look_at"], "camera target")
    direction = _normalize([b - a for a, b in zip(position, target)])
    right = _normalize(_cross(direction, _vector(transform.get("up", [0, 1, 0]), "camera up")))
    up = _normalize(_cross(right, direction))
    resolution = value["resolution"]
    if (not isinstance(resolution, list) or len(resolution) != 2
            or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in resolution)):
        raise ValueError("Camera resolution must contain two positive integers")
    fov = value["fov"]
    if isinstance(fov, bool) or not isinstance(fov, (int, float)) or not 0 < fov < 180:
        raise ValueError("Camera horizontal FOV must be between 0 and 180 degrees")
    aspect = resolution[0] / resolution[1]
    vertical = 2 * math.atan(math.tan(math.radians(fov) / 2) / aspect)
    matrix = [*right, 0, *up, 0, *[-v for v in direction], 0, *position, 1]
    return ({"position": position, "direction": direction, "up": up, "vertical_fov": math.degrees(vertical)},
            {"type": "perspective", "perspective": {"aspectRatio": aspect, "yfov": vertical, "znear": .01}}, matrix)


class _Bundle:
    def __init__(self, source, output):
        self.source, self.output = source, output
        self.resources = output.parent / "resources"
        self.resources.mkdir(parents=True)
        self.data = bytearray()
        self.document = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": []}],
                         "nodes": [], "meshes": [], "materials": [], "bufferViews": [], "accessors": [],
                         "images": [], "textures": [],
                         "samplers": [{"wrapS": 10497, "wrapT": 10497, "magFilter": 9729, "minFilter": 9987}]}
        self.inputs, self.approximations = {}, []
        self.textures = {}

    def resource(self, relative):
        path = resource_path(self.source.parent, relative)
        if not path.is_file():
            raise FileNotFoundError(path)
        self.inputs[relative] = digest(path)
        return path

    def accessor(self, rows, kind, component=5126):
        size = {"VEC2": 2, "VEC3": 3, "SCALAR": 1}[kind]
        code = "f" if component == 5126 else "I"
        offset = len(self.data)
        pack = struct.Struct("<" + code * size)
        for row in rows:
            self.data.extend(pack.pack(*row))
        view = len(self.document["bufferViews"])
        self.document["bufferViews"].append({"buffer": 0, "byteOffset": offset, "byteLength": len(self.data) - offset,
                                             "target": 34963 if kind == "SCALAR" else 34962})
        entry = {"bufferView": view, "count": len(rows), "componentType": component, "type": kind}
        if kind == "VEC3":
            entry.update(min=[min(r[i] for r in rows) for i in range(size)],
                         max=[max(r[i] for r in rows) for i in range(size)])
        self.document["accessors"].append(entry)
        return len(self.document["accessors"]) - 1

    def texture(self, albedo):
        key = json.dumps(albedo, sort_keys=True)
        if key in self.textures:
            return self.textures[key]
        index = len(self.document["images"])
        if isinstance(albedo, str):
            source = self.resource(albedo)
            with Image.open(source) as image:
                if image.format not in ("PNG", "JPEG") or getattr(image, "n_frames", 1) != 1:
                    raise ValueError(f"Only static PNG/JPEG albedo textures are supported: {albedo}")
                image.verify()
            target = self.resources / f"albedo-{index:03d}{source.suffix.lower()}"
            shutil.copyfile(source, target)
        else:
            if not isinstance(albedo, dict) or set(albedo) - {"type", "on_color", "off_color", "res_u", "res_v"} or albedo.get("type") != "checker":
                raise ValueError("Unsupported Tungsten albedo texture")
            width, height = albedo.get("res_u", 20), albedo.get("res_v", 20)
            if any(isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 512 for v in (width, height)):
                raise ValueError("Checker cell counts must be integers in 1..512")
            def srgb(value):
                return round(255 * (12.92 * value if value <= .0031308 else 1.055 * value ** (1 / 2.4) - .055))
            on = tuple(srgb(v) for v in _vector(albedo.get("on_color", .8), "checker on", scalar=True, minimum=0, maximum=1))
            off = tuple(srgb(v) for v in _vector(albedo.get("off_color", .2), "checker off", scalar=True, minimum=0, maximum=1))
            image = Image.new("RGB", (width * 8, height * 8))
            # Converted UVs use 1-v, so evaluate the source checker from the bottom row.
            image.putdata([on if ((x // 8) ^ (height - 1 - y // 8)) & 1 else off
                           for y in range(height * 8) for x in range(width * 8)])
            target = self.resources / f"checker-{index:03d}.png"
            image.save(target)
        self.document["images"].append({"uri": target.relative_to(self.output.parent).as_posix()})
        self.document["textures"].append({"source": index, "sampler": 0})
        self.textures[key] = index
        return index

    def material(self, value):
        name, kind = value["name"], value["type"]
        if set(value) - {"name", "type", "albedo", "material", "distribution", "roughness", "ior", "enable_refraction"}:
            raise ValueError(f"Unsupported Tungsten material fields: {name}")
        if kind not in ("lambert", "rough_conductor", "dielectric", "null"):
            raise ValueError(f"Unsupported Tungsten material: {kind}")
        albedo = value.get("albedo", 1)
        texture = isinstance(albedo, (str, dict))
        color = [1, 1, 1] if texture else _vector(albedo, "albedo", scalar=True, minimum=0, maximum=1)
        pbr = {"baseColorFactor": color + [1], "metallicFactor": 0, "roughnessFactor": 1}
        material = {"name": name, "pbrMetallicRoughness": pbr}
        if texture:
            pbr["baseColorTexture"] = {"index": self.texture(albedo)}
        if kind == "rough_conductor":
            if value.get("material") != "Al" or value.get("distribution", "ggx") not in ("ggx", "beckmann"):
                raise ValueError(f"Unsupported conductor material/distribution: {name}")
            alpha = value.get("roughness", .1)
            if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not 0 <= alpha <= 1:
                raise ValueError(f"Invalid conductor roughness: {name}")
            # Normal-incidence Fresnel from Tungsten's ComplexIorData.hpp aluminum RGB eta/k.
            eta, k = [1.6574599595, .8803689579, .5212287346], [9.2238691996, 6.2695232477, 4.8370012281]
            reflectance = [((n - 1) ** 2 + j * j) / ((n + 1) ** 2 + j * j) for n, j in zip(eta, k)]
            pbr.update(baseColorFactor=[a * b for a, b in zip(color, reflectance)] + [1],
                       metallicFactor=1, roughnessFactor=math.sqrt(alpha))
            self.approximations.append(f"{name}: complex-IOR {value.get('distribution', 'ggx')} aluminum mapped to GGX metallic PBR")
        elif kind == "dielectric":
            if value.get("ior", 1.5) != 1.5 or value.get("enable_refraction", True) is not True:
                raise ValueError(f"Only refractive IOR 1.5 dielectric is supported: {name}")
            pbr["roughnessFactor"] = 0
            material["extensions"] = {"KHR_materials_transmission": {"transmissionFactor": 1}}
            self.approximations.append(f"{name}: dielectric mapped to Donut thin-surface transmission (IOR 1.5)")
        elif kind == "null":
            pbr["baseColorFactor"] = [0, 0, 0, 1]
        self.document["materials"].append(material)
        return len(self.document["materials"]) - 1

    def geometry(self, vertices, faces, smooth):
        if smooth:
            normals = [_normalize(vertex[3:6]) for vertex in vertices]
        else:
            expanded, normals = [], []
            for face in faces:
                points = [vertices[index] for index in face]
                a, b = ([points[i][j] - points[0][j] for j in range(3)] for i in (1, 2))
                normal = _normalize(_cross(a, b))
                expanded.extend(points)
                normals.extend([normal] * 3)
            vertices = expanded
            faces = [(i, i + 1, i + 2) for i in range(0, len(vertices), 3)]
        return {"attributes": {"POSITION": self.accessor([v[:3] for v in vertices], "VEC3"),
                               "NORMAL": self.accessor(normals, "VEC3"),
                               "TEXCOORD_0": self.accessor([(v[6], 1 - v[7]) for v in vertices], "VEC2")},
                "indices": self.accessor([(i,) for face in faces for i in face], "SCALAR", 5125)}


def convert(source, output):
    """Write a staged glTF bundle; caller owns atomic publication of its directory."""
    source, output = Path(source).resolve(), Path(output).resolve()
    scene = json.loads(source.read_text(encoding="utf-8"))
    if scene.get("media"):
        raise ValueError("Tungsten participating media are unsupported")
    camera, gltf_camera, camera_matrix = _camera(scene["camera"])
    bundle = _Bundle(source, output)
    document = bundle.document
    materials = {}
    for material in scene["bsdfs"]:
        if not material.get("name") or material["name"] in materials:
            raise ValueError("Tungsten material names must be unique and nonempty")
        materials[material["name"]] = bundle.material(material)
    geometries = {}
    emissive_triangles, triangle_count = 0, 0
    for index, primitive in enumerate(scene["primitives"]):
        if set(primitive) - {"type", "name", "file", "smooth", "backface_culling", "recompute_normals", "bsdf", "transform", "emission"}:
            raise ValueError(f"Unsupported primitive fields at index {index}")
        for flag in ("smooth", "backface_culling", "recompute_normals"):
            if flag in primitive and not isinstance(primitive[flag], bool):
                raise ValueError(f"Primitive {flag} must be boolean")
        if primitive.get("recompute_normals", False):
            raise ValueError("Recomputed smooth normals are unsupported")
        kind, name = primitive["type"], primitive.get("name", f"primitive-{index:03d}")
        smooth = primitive.get("smooth", False)
        if kind == "mesh":
            key = (primitive["file"], smooth)
            if key not in geometries:
                vertices, faces = read_wo3(bundle.resource(primitive["file"]))
                geometries[key] = (bundle.geometry(vertices, faces, smooth), len(faces))
            geometry, count = geometries[key]
        elif kind == "quad":
            vertices = [(x, 0, z, 0, 1, 0, u, v) for (x, z, u, v) in
                        ((-.5, -.5, 0, 0), (.5, -.5, 1, 0), (.5, .5, 1, 1), (-.5, .5, 0, 1))]
            geometry, count = bundle.geometry(vertices, [(0, 2, 1), (0, 3, 2)], True), 2
        else:
            raise ValueError(f"Unsupported Tungsten primitive: {kind}")
        if primitive["bsdf"] not in materials:
            raise ValueError(f"Unknown primitive material: {primitive['bsdf']}")
        material = deepcopy(document["materials"][materials[primitive["bsdf"]]])
        material["doubleSided"] = not primitive.get("backface_culling", False) if kind == "mesh" else False
        emission = _vector(primitive.get("emission", 0), "emission", scalar=True, minimum=0)
        if any(emission):
            strength = max(1, max(emission))
            material["emissiveFactor"] = [v / strength for v in emission]
            if strength > 1:
                material.setdefault("extensions", {})["KHR_materials_emissive_strength"] = {"emissiveStrength": strength}
            emissive_triangles += count
        document["materials"].append(material)
        document["meshes"].append({"name": name, "primitives": [{**geometry, "material": len(document["materials"]) - 1}]})
        document["nodes"].append({"name": name, "mesh": len(document["meshes"]) - 1,
                                  "matrix": _transform(primitive.get("transform", {}))})
        triangle_count += count
    document["nodes"].append({"name": "Source camera", "camera": 0, "matrix": camera_matrix})
    document["scenes"][0]["nodes"] = list(range(len(document["nodes"])))
    document["cameras"] = [gltf_camera]
    extensions = sorted({extension for material in document["materials"] for extension in material.get("extensions", {})})
    if extensions:
        document["extensionsUsed"] = extensions
    document["buffers"] = [{"uri": "resources/geometry.bin", "byteLength": len(bundle.data)}]
    (bundle.resources / "geometry.bin").write_bytes(bundle.data)
    output.write_text(json.dumps(document, separators=(",", ":")) + "\n", encoding="utf-8")
    return {"camera": camera, "source_lights": [], "source_resources": bundle.inputs,
            "triangles": triangle_count, "emissive_triangles": emissive_triangles,
            "material_approximations": bundle.approximations,
            "limitations": ["Tungsten conductor BRDFs mapped to metallic PBR; dielectric uses Donut thin-surface transmission",
                            "RTXDI DI does not reproduce the scene's indirect illumination, dielectric refraction or caustics",
                            "Procedural checker baked to 8 texels per cell; source image filtering and transfer curve may differ",
                            "Source camera, static transforms and quad emission retained; not the CGNS authors' scene configuration"]}
