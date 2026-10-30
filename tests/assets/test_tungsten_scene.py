"""Tungsten mesh/scene regressions without downloaded assets or Blender."""
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/assets"))
from profiles.tungsten import convert, read_wo3


class TungstenSceneTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "scene.json"
        self.output = self.root / "converted" / "scene.gltf"
        self.scene = {"media": [], "bsdfs": [{"name": "Light", "type": "null", "albedo": 1}],
                      "primitives": [{"type": "quad", "bsdf": "Light", "emission": 1000,
                                      "transform": {"position": [-4, 1.5, -4.5],
                                                    "scale": [2, 3, 4], "rotation": [-90, 0, 0]}}],
                      "camera": {"type": "pinhole", "fov": 60, "resolution": [1280, 720],
                                 "transform": {"position": [4, 2, -2], "look_at": [-4, 2, -2], "up": [0, 1, 0]}}}

    def run_conversion(self):
        self.source.write_text(json.dumps(self.scene), encoding="utf-8")
        record = convert(self.source, self.output)
        return json.loads(self.output.read_text()), record

    def mesh(self, *, smooth=True, index=2):
        path = self.root / "triangle.wo3"
        vertices = [(0, 0, 0, 0, 1, 0, .25, .75),
                    (1, 0, 0, 0, 1, 0, .5, .25),
                    (0, 1, 0, 0, 1, 0, .75, .5)]
        path.write_bytes(struct.pack("<Q", 3) + b"".join(struct.pack("<8f", *v) for v in vertices)
                         + struct.pack("<QIIIi", 1, 0, 1, index, -1))
        self.scene["primitives"] = [{"type": "mesh", "file": path.name, "bsdf": "Light", "smooth": smooth}]
        return path

    def accessor(self, document, index):
        entry = document["accessors"][index]
        view = document["bufferViews"][entry["bufferView"]]
        data = (self.output.parent / document["buffers"][0]["uri"]).read_bytes()
        components = {"VEC2": 2, "VEC3": 3, "SCALAR": 1}[entry["type"]]
        scalar = "f" if entry["componentType"] == 5126 else "I"
        return list(struct.iter_unpack("<" + scalar * components,
                                      data[view.get("byteOffset", 0):view.get("byteOffset", 0) + view["byteLength"]]))

    def test_preserves_radiance_and_quad_front_face_after_transform(self):
        document, record = self.run_conversion()
        material = document["materials"][document["meshes"][0]["primitives"][0]["material"]]
        factor = material["emissiveFactor"]
        strength = material["extensions"]["KHR_materials_emissive_strength"]["emissiveStrength"]
        self.assertTrue(all(0 <= v <= 1 for v in factor))
        self.assertEqual([v * strength for v in factor], [1000, 1000, 1000])
        self.assertIn("KHR_materials_emissive_strength", document["extensionsUsed"])
        self.assertEqual(record["emissive_triangles"], 2)
        matrix = document["nodes"][0]["matrix"]
        self.assertEqual(matrix[12:15], [-4, 1.5, -4.5])
        self.assertAlmostEqual(matrix[6], -3)
        geometry = document["meshes"][0]["primitives"][0]
        self.assertEqual(self.accessor(document, geometry["attributes"]["NORMAL"])[0], (0, 1, 0))
        self.assertEqual(self.accessor(document, geometry["indices"])[0:3], [(0,), (2,), (1,)])

    def test_camera_uses_horizontal_fov_and_original_y_up_coordinates(self):
        document, record = self.run_conversion()
        self.assertAlmostEqual(record["camera"]["vertical_fov"], 35.98339777135764)
        self.assertEqual(record["camera"]["position"], [4, 2, -2])
        self.assertEqual(record["camera"]["direction"], [-1, 0, 0])
        camera = document["nodes"][-1]["matrix"]
        self.assertEqual(camera[8:11], [1, 0, 0])  # local -Z faces -X
        self.assertAlmostEqual(document["cameras"][0]["perspective"]["aspectRatio"], 1280 / 720)

    def test_tungsten_positive_y_rotation_is_clockwise(self):
        self.scene["primitives"][0]["transform"] = {"rotation": [0, 90, 0]}
        document, _ = self.run_conversion()
        matrix = document["nodes"][0]["matrix"]
        self.assertAlmostEqual(matrix[2], 1)
        self.assertAlmostEqual(matrix[8], -1)

    def test_mesh_uvs_flip_v_and_flat_meshes_use_geometric_normals(self):
        self.mesh(smooth=False)
        document, _ = self.run_conversion()
        attributes = document["meshes"][0]["primitives"][0]["attributes"]
        self.assertEqual(self.accessor(document, attributes["NORMAL"]), [(0, 0, 1)] * 3)
        self.assertEqual(self.accessor(document, attributes["TEXCOORD_0"])[0], (.25, .25))

    def test_malformed_meshes_fail_before_unsafe_allocation(self):
        path = self.mesh()
        valid = path.read_bytes()
        for data in (b"", struct.pack("<Q", 2**63), valid[:-1], valid + b"x"):
            with self.subTest(length=len(data)):
                path.write_bytes(data)
                with self.assertRaises(ValueError):
                    read_wo3(path)
        self.mesh(index=3)
        with self.assertRaisesRegex(ValueError, "index"):
            read_wo3(path)

    def test_mesh_nonfinite_attributes_fail(self):
        path = self.mesh()
        data = bytearray(path.read_bytes())
        struct.pack_into("<f", data, 8, float("nan"))
        path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "finite"):
            read_wo3(path)

    def test_external_texture_and_mesh_paths_are_rejected(self):
        for index, path in enumerate(("../outside.wo3", "C:/outside.wo3", "https://example.test/mesh.wo3")):
            self.output = self.root / f"invalid-{index}" / "scene.gltf"
            self.scene["primitives"] = [{"type": "mesh", "file": path, "bsdf": "Light"}]
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.run_conversion()
        self.output = self.root / "invalid-texture" / "scene.gltf"
        self.scene["primitives"] = []
        self.scene["bsdfs"][0] = {"name": "Paint", "type": "lambert", "albedo": "../outside.png"}
        with self.assertRaises(ValueError):
            self.run_conversion()

    def test_checker_is_srgb_encoded_with_authored_cell_counts(self):
        self.scene["bsdfs"][0] = {"name": "Floor", "type": "rough_conductor", "material": "Al",
                                  "distribution": "ggx", "roughness": .1,
                                  "albedo": {"type": "checker", "on_color": .8, "off_color": .2,
                                             "res_u": 2, "res_v": 4}}
        self.scene["primitives"][0]["bsdf"] = "Floor"
        document, record = self.run_conversion()
        with Image.open(self.output.parent / document["images"][0]["uri"]) as image:
            self.assertEqual(image.size, (16, 32))
            self.assertEqual(image.getpixel((4, 4)), (231, 231, 231))  # original V is flipped
            self.assertEqual(image.getpixel((12, 4)), (124, 124, 124))
        self.assertAlmostEqual(document["materials"][0]["pbrMetallicRoughness"]["roughnessFactor"], math.sqrt(.1))
        self.assertTrue(record["material_approximations"])

    def test_dielectric_transmission_is_preserved_and_approximation_recorded(self):
        self.scene["bsdfs"][0] = {"name": "Glass", "type": "dielectric", "ior": 1.5,
                                  "albedo": .9, "enable_refraction": True}
        self.scene["primitives"][0]["bsdf"] = "Glass"
        self.scene["primitives"][0].pop("emission")
        document, record = self.run_conversion()
        self.assertEqual(document["materials"][0]["extensions"]["KHR_materials_transmission"]["transmissionFactor"], 1)
        self.assertTrue(any("dielectric" in entry.lower() for entry in record["limitations"]))

    def test_unsupported_material_does_not_silently_become_diffuse(self):
        self.scene["bsdfs"][0]["type"] = "unrecognized"
        with self.assertRaisesRegex(ValueError, "material"):
            self.run_conversion()


    def test_vector_roughness_is_rejected_instead_of_using_first_channel(self):
        self.scene["bsdfs"][0] = {"name": "Light", "type": "rough_conductor", "material": "Al",
                                  "roughness": [.1, .2, .3]}
        with self.assertRaisesRegex(ValueError, "roughness"):
            self.run_conversion()

    def test_string_mesh_flags_are_rejected_instead_of_becoming_true(self):
        self.mesh()
        self.scene["primitives"][0]["smooth"] = "false"
        with self.assertRaisesRegex(ValueError, "boolean"):
            self.run_conversion()

    def test_hdr_colored_emission_normalizes_and_keeps_transmission_extension(self):
        self.scene["bsdfs"][0] = {"name": "Glass", "type": "dielectric", "ior": 1.5}
        self.scene["primitives"][0].update(bsdf="Glass", emission=[2000, 1000, 0])
        document, _ = self.run_conversion()
        material = document["materials"][-1]
        self.assertEqual(material["emissiveFactor"], [1, .5, 0])
        self.assertEqual(material["extensions"]["KHR_materials_emissive_strength"]["emissiveStrength"], 2000)
        self.assertEqual(set(document["extensionsUsed"]),
                         {"KHR_materials_transmission", "KHR_materials_emissive_strength"})

if __name__ == "__main__":
    unittest.main()
