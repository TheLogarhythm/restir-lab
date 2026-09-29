"""Small glTF/ZIP regressions; no Blender, GPU, or downloaded scenes required."""
from copy import deepcopy
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/assets"))
from convert_orca_fbx import convert, emissive_triangle_count


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def fixture(self, folder="input", color=(10, 20, 30, 255)):
        folder = self.directory / folder
        folder.mkdir(parents=True)
        Image.new("RGBA", (2, 2), color).save(folder / "packed.png")
        Image.new("RGBA", (2, 2), (128, 64, 255, 255)).save(folder / "normal.png")
        data = struct.pack("<15f", 0, 0, 0, 1, 0, 0, 0, 1, 0, .25, .5, .5, .25, 0, 0)
        (folder / "mesh.bin").write_bytes(data)
        material = {"extensions": {"KHR_materials_specular": {"specularTexture": {"index": 0}}},
                    "normalTexture": {"index": 1}, "emissiveFactor": [1, 1, 1]}
        gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
                "nodes": [{"mesh": 0}], "buffers": [{"uri": "mesh.bin", "byteLength": len(data)}],
                "bufferViews": [{"buffer": 0, "byteLength": 36}, {"buffer": 0, "byteOffset": 36, "byteLength": 24}],
                "accessors": [{"bufferView": 0, "count": 3, "componentType": 5126, "type": "VEC3"},
                              {"bufferView": 1, "count": 3, "componentType": 5126, "type": "VEC2"}],
                "images": [{"uri": "packed.png"}, {"uri": "normal.png"}],
                "samplers": [{"wrapS": 33071, "wrapT": 33071}, {"wrapS": 10497}],
                "textures": [{"source": 0, "sampler": 0}, {"source": 1, "sampler": 0}, {"source": 1, "sampler": 1}],
                "materials": [material],
                "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "material": 0}]}]}
        return folder / "raw.gltf", gltf

    def run_conversion(self, raw, gltf, output=None, expected=1):
        raw.write_text(json.dumps(gltf), encoding="utf-8")
        output = output or raw.with_name("converted.gltf")
        summary = convert(raw, output, expected)
        return json.loads(output.read_text()), summary

    def test_normal_conversion_preserves_each_sampler(self):
        raw, gltf = self.fixture()
        other = deepcopy(gltf["materials"][0])
        other["normalTexture"]["index"] = 2
        gltf["materials"].append(other)
        result, _ = self.run_conversion(raw, gltf)
        normals = [result["textures"][m["normalTexture"]["index"]] for m in result["materials"]]
        self.assertEqual([t["sampler"] for t in normals], [0, 1])
        path = raw.parent / result["images"][normals[0]["source"]]["uri"]
        with Image.open(path) as normal:
            self.assertEqual(normal.getpixel((0, 0)), (128, 191, 255, 255))

    def test_fully_opaque_blend_is_normalized_without_changing_source(self):
        raw, gltf = self.fixture()
        material = gltf["materials"][0]
        material.update(alphaMode="BLEND", name="arbitrary material",
                        pbrMetallicRoughness={"baseColorTexture": {"index": 0}})
        result, summary = self.run_conversion(raw, gltf)
        self.assertEqual(result["materials"][0]["alphaMode"], "OPAQUE")
        self.assertEqual(json.loads(raw.read_text())["materials"][0]["alphaMode"], "BLEND")
        self.assertEqual(summary["alpha_normalization"]["converted"], [0])
        from gltf_materials import normalize_opaque_materials
        self.assertEqual(normalize_opaque_materials(result, raw.parent)["converted"], [])

    def test_textureless_opaque_blend_is_normalized_but_mask_is_preserved(self):
        raw, gltf = self.fixture()
        gltf["materials"][0]["alphaMode"] = "BLEND"
        gltf["materials"].append({"alphaMode": "MASK", "alphaCutoff": .3})
        result, _ = self.run_conversion(raw, gltf)
        self.assertEqual(result["materials"][0]["alphaMode"], "OPAQUE")
        self.assertEqual(result["materials"][1], {"alphaMode": "MASK", "alphaCutoff": .3})

    def test_factor_or_single_nonopaque_texel_preserves_blending(self):
        for factor, texel in ((.5, 255), (1, 254), (1, 0)):
            with self.subTest(factor=factor, texel=texel):
                raw, gltf = self.fixture(f"alpha-{factor}-{texel}")
                material = gltf["materials"][0]
                material.update(alphaMode="BLEND", pbrMetallicRoughness={
                    "baseColorTexture": {"index": 0}, "baseColorFactor": [1, 1, 1, factor]})
                with Image.open(raw.parent / "packed.png") as source:
                    source.putpixel((1, 1), (10, 20, 30, texel))
                    source.save(raw.parent / "packed.png")
                result, _ = self.run_conversion(raw, gltf)
                self.assertEqual(result["materials"][0]["alphaMode"], "BLEND")

    def test_vertex_alpha_protects_all_uses_of_shared_material(self):
        for components, expected in ((3, "OPAQUE"), (4, "BLEND")):
            with self.subTest(components=components):
                raw, gltf = self.fixture(f"vertex-{components}")
                gltf["materials"][0]["alphaMode"] = "BLEND"
                data = (raw.parent / "mesh.bin").read_bytes()
                colors = struct.pack("<" + "f" * (components * 3), *([1, 1, 1, .5][:components] * 3))
                (raw.parent / "mesh.bin").write_bytes(data + colors)
                gltf["buffers"][0]["byteLength"] += len(colors)
                gltf["bufferViews"].append({"buffer": 0, "byteOffset": len(data), "byteLength": len(colors)})
                gltf["accessors"].append({"bufferView": 2, "count": 3, "componentType": 5126,
                                          "type": f"VEC{components}"})
                other = deepcopy(gltf["meshes"][0]["primitives"][0])
                other["attributes"]["COLOR_0"] = 2
                gltf["meshes"][0]["primitives"].append(other)
                result, _ = self.run_conversion(raw, gltf, expected=2)
                self.assertEqual(result["materials"][0]["alphaMode"], expected)

    def test_material_animation_and_unknown_extensions_preserve_blending(self):
        for kind in ("animation", "material", "texture", "primitive"):
            with self.subTest(kind=kind):
                raw, gltf = self.fixture(kind)
                material = gltf["materials"][0]
                material.update(alphaMode="BLEND", pbrMetallicRoughness={"baseColorTexture": {"index": 0}})
                if kind == "animation":
                    gltf["extensionsUsed"] = ["KHR_animation_pointer"]
                    gltf["animations"] = [{"channels": [{"target": {"path": "pointer", "extensions": {
                        "KHR_animation_pointer": {"pointer": "/materials/0/pbrMetallicRoughness/baseColorFactor"}}}}]}]
                elif kind == "material":
                    material["extensions"]["EXT_unknown_material"] = {}
                elif kind == "texture":
                    gltf["textures"][0]["extensions"] = {"EXT_unknown_texture": {"source": 0}}
                else:
                    gltf["meshes"][0]["primitives"][0]["extensions"] = {"EXT_unknown_primitive": {}}
                result, _ = self.run_conversion(raw, gltf)
                self.assertEqual(result["materials"][0]["alphaMode"], "BLEND")

    def test_palette_transparency_preserves_blending(self):
        raw, gltf = self.fixture()
        material = gltf["materials"][0]
        material.update(alphaMode="BLEND", pbrMetallicRoughness={"baseColorTexture": {"index": 0}})
        image = Image.new("P", (2, 2), 0)
        image.putpalette([10, 20, 30] * 256)
        image.save(raw.parent / "packed.png", transparency=0)
        result, _ = self.run_conversion(raw, gltf)
        self.assertEqual(result["materials"][0]["alphaMode"], "BLEND")

    def test_16bit_alpha_is_not_mistaken_for_opaque_after_decoding(self):
        raw, gltf = self.fixture()
        gltf["materials"][0].update(alphaMode="BLEND",
            pbrMetallicRoughness={"baseColorTexture": {"index": 0}})
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        # 65534/65535 is transparent, but Pillow's RGBA8 decoding returns alpha 255.
        row = b"\x00" + struct.pack(">4H", 1000, 2000, 3000, 65534) * 2
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", 2, 2, 16, 6, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(row * 2)) + chunk(b"IEND", b""))
        (raw.parent / "packed.png").write_bytes(png)
        result, _ = self.run_conversion(raw, gltf)
        self.assertEqual(result["materials"][0]["alphaMode"], "BLEND")

    def test_two_outputs_do_not_overwrite_shared_texture_paths(self):
        raw, gltf = self.fixture()
        first, _ = self.run_conversion(raw, gltf, raw.with_name("one.gltf"))
        path = raw.parent / first["images"][0]["uri"]
        previous = path.read_bytes()
        Image.new("RGBA", (2, 2), (90, 80, 70, 255)).save(raw.parent / "packed.png")
        self.run_conversion(raw, gltf, raw.with_name("two.gltf"))
        self.assertEqual(path.read_bytes(), previous)

    def test_failure_leaves_source_and_output_directory_unchanged(self):
        raw, gltf = self.fixture()
        raw.write_text(json.dumps(gltf))
        before = {p.relative_to(raw.parent).as_posix(): p.read_bytes() for p in raw.parent.rglob("*") if p.is_file()}
        with self.assertRaises(ValueError):
            convert(raw, raw.with_name("converted.gltf"), 999)
        self.assertEqual({p.relative_to(raw.parent).as_posix(): p.read_bytes() for p in raw.parent.rglob("*") if p.is_file()}, before)

    def test_integer_uv_offset_is_baked_for_clamped_sampler(self):
        raw, gltf = self.fixture()
        mat = gltf["materials"][0]
        for info in [mat["normalTexture"], mat["extensions"]["KHR_materials_specular"]["specularTexture"]]:
            info["extensions"] = {"KHR_texture_transform": {"offset": [1, 0]}}
        result, _ = self.run_conversion(raw, gltf)
        index = result["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_0"]
        accessor = result["accessors"][index]
        view = result["bufferViews"][accessor["bufferView"]]
        data = (raw.parent / result["buffers"][view["buffer"]]["uri"]).read_bytes()
        uv = struct.unpack_from("<ff", data, view.get("byteOffset", 0) + accessor.get("byteOffset", 0))
        self.assertEqual(uv, (1.25, .5))

    def test_uv_set_without_transform_is_rejected(self):
        raw, gltf = self.fixture()
        gltf["materials"][0]["normalTexture"]["texCoord"] = 1
        with self.assertRaisesRegex(ValueError, "texCoord"):
            self.run_conversion(raw, gltf)

    def test_emissive_count_uses_scene_instances_and_factor(self):
        _, gltf = self.fixture()
        gltf["nodes"].append({"mesh": 0})
        gltf["scenes"][0]["nodes"].append(1)
        self.assertEqual(emissive_triangle_count(gltf), 2)
        gltf["materials"][0]["emissiveFactor"] = [0, 0, 0]
        gltf["materials"][0]["emissiveTexture"] = {"index": 0}
        self.assertEqual(emissive_triangle_count(gltf), 0)

    def test_repeat_conversion_to_another_directory_is_stable(self):
        raw, gltf = self.fixture()
        output = self.directory / "published" / "scene.gltf"
        result, first = self.run_conversion(raw, gltf, output)
        source_bytes = {p.name: p.read_bytes() for p in raw.parent.iterdir()}
        _, second = self.run_conversion(raw, gltf, output)
        self.assertEqual(first["output_sha256"], second["output_sha256"])
        self.assertEqual(first["resources"], second["resources"])
        self.assertEqual({p.name: p.read_bytes() for p in raw.parent.iterdir()}, source_bytes)
        self.assertTrue(all((output.parent / x["uri"]).is_file() for key in ("buffers", "images") for x in result[key]))

    def test_unsupported_transform_does_not_replace_existing_output(self):
        raw, gltf = self.fixture()
        output = raw.with_name("scene.gltf")
        self.run_conversion(raw, gltf, output)
        before = output.read_bytes()
        gltf["materials"][0]["normalTexture"]["extensions"] = {"KHR_texture_transform": {"scale": [2, 2]}}
        with self.assertRaisesRegex(ValueError, "incompatible"):
            self.run_conversion(raw, gltf, output)
        self.assertEqual(output.read_bytes(), before)

    def test_uv_accessor_cannot_read_past_its_view(self):
        raw, gltf = self.fixture()
        for info in [gltf["materials"][0]["normalTexture"], gltf["materials"][0]["extensions"]["KHR_materials_specular"]["specularTexture"]]:
            info["extensions"] = {"KHR_texture_transform": {"scale": [2, 2]}}
        gltf["bufferViews"][1]["byteLength"] = 8
        with self.assertRaisesRegex(ValueError, "buffer view"):
            self.run_conversion(raw, gltf)

    def test_path_escape_is_rejected(self):
        raw, gltf = self.fixture()
        gltf["images"][0]["uri"] = "../outside.png"
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.run_conversion(raw, gltf)

    def test_missing_zip_scene_is_not_satisfied_by_notices(self):
        archive = self.directory / "scene.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("README.txt", "source notice")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/assets/extract_orca.py"),
                                 "--archive", str(archive), "--folder", "MISSING", "--output", str(self.directory / "out")], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.directory / "out").exists())


if __name__ == "__main__":
    unittest.main()
