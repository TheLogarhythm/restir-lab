"""Emission preservation checks for the ORCA conversion profile."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/assets"))
from orca_materials import convert_materials


class EmissiveConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        Image.new("RGB", (2, 2), (255, 67, 0)).save(self.directory / "emission.png")
        self.material = {
            "name": "test emitter",
            "extensions": {"KHR_materials_specular": {"specularTexture": {"index": 0}}},
            "emissiveFactor": [.5, .25, 1],
            "emissiveTexture": {"index": 1},
        }
        self.gltf = {
            "images": [{"uri": "emission.png"}],
            "textures": [{"source": 0}, {"source": 0}],
            "materials": [self.material],
            "meshes": [{"name": "test mesh", "primitives": [
                {"material": 0, "attributes": {"POSITION": 0, "TEXCOORD_0": 1}}]}],
        }

    def test_valid_uv_preserves_emission_factor_texture_and_strength(self):
        self.material["extensions"]["KHR_materials_emissive_strength"] = {"emissiveStrength": 12}
        before = deepcopy(self.material)
        convert_materials(self.gltf, self.directory)
        for key in ("emissiveFactor", "emissiveTexture"):
            self.assertEqual(self.material[key], before[key])
        self.assertEqual(self.material["extensions"]["KHR_materials_emissive_strength"], {"emissiveStrength": 12})

    def assert_folded(self):
        result = convert_materials(self.gltf, self.directory)
        self.assertNotIn("emissiveTexture", self.material)
        self.assertAlmostEqual(self.material["emissiveFactor"][0], .5)
        self.assertAlmostEqual(self.material["emissiveFactor"][1], .25 * ((67/255 + .055)/1.055)**2.4)
        self.assertEqual(self.material["emissiveFactor"][2], 0)
        self.assertEqual(result["baked_constant_emissive_materials"], ["test emitter"])

    def test_negative_uv_constant_texture_is_folded_in_linear_space(self):
        self.material["emissiveTexture"]["texCoord"] = -1
        self.assert_folded()

    def test_missing_primitive_uv_is_detected_without_negative_texcoord(self):
        del self.gltf["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_0"]
        self.assert_folded()

    def test_one_missing_uv_in_shared_material_is_detected(self):
        self.gltf["meshes"].append({"name": "second mesh", "primitives": [
            {"material": 0, "attributes": {"POSITION": 0}}]})
        self.assert_folded()

    def test_spatially_varying_texture_without_uv_fails_with_context(self):
        im = Image.new("RGB", (2, 2), (255, 67, 0))
        im.putpixel((1, 1), (0, 0, 0))
        im.save(self.directory / "emission.png")
        self.material["emissiveTexture"]["texCoord"] = -1
        with self.assertRaisesRegex(ValueError, "test emitter.*test mesh.*nonconstant"):
            convert_materials(self.gltf, self.directory)

    def test_texture_transform_uv_override_is_checked(self):
        self.material["emissiveTexture"]["extensions"] = {"KHR_texture_transform": {"texCoord": -1}}
        self.assert_folded()

    def test_unknown_emission_texture_extension_fails(self):
        self.material["emissiveTexture"]["extensions"] = {"EXT_unknown": {}}
        with self.assertRaisesRegex(ValueError, "Unsupported.*emissive"):
            convert_materials(self.gltf, self.directory)

    def test_invalid_strength_fails(self):
        for strength in (-1, float("nan"), float("inf")):
            with self.subTest(strength=strength):
                self.material["extensions"]["KHR_materials_emissive_strength"] = {"emissiveStrength": strength}
                with self.assertRaisesRegex(ValueError, "emissiveStrength"):
                    convert_materials(deepcopy(self.gltf), self.directory)

    def test_unknown_strength_fields_fail(self):
        self.material["extensions"]["KHR_materials_emissive_strength"] = {"unknown": 2}
        with self.assertRaisesRegex(ValueError, "Unsupported.*emissive"):
            convert_materials(self.gltf, self.directory)

    def test_folding_preserves_strength(self):
        self.material["extensions"]["KHR_materials_emissive_strength"] = {"emissiveStrength": 12}
        self.material["emissiveTexture"]["texCoord"] = -1
        self.assert_folded()
        self.assertEqual(self.material["extensions"]["KHR_materials_emissive_strength"]["emissiveStrength"], 12)

    def test_high_precision_texture_is_not_silently_reduced(self):
        Image.new("I;16", (2, 2), 65534).save(self.directory / "emission.png")
        self.material["emissiveTexture"]["texCoord"] = -1
        with self.assertRaisesRegex(ValueError, "precision"):
            convert_materials(self.gltf, self.directory)


if __name__ == "__main__":
    unittest.main()
