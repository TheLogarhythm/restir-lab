import unittest
from tests.fixtures.falcor_shaders import SHADERS, PATHS
from scripts.falcor.gltf_factor_shader_patch import patch_sources

class GltfFactorShaderPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = {k: (SHADERS / p).read_text(encoding='utf8') for k, p in PATHS.items()}

    def test_marked_material_uses_factor_without_changing_native_fallbacks(self):
        result = patch_sources(self.original)
        standard = result['standard']
        self.assertIn('data.flags & (1u << 20)', standard)
        self.assertIn('data.baseColor.rgb * ms.sampleTexture(data.texBaseColor', standard)
        self.assertIn('data.specular * ms.sampleTexture(data.texSpecular', standard)
        self.assertIn('data.emissive * ms.sampleTexture(data.texEmissive', standard)
        self.assertIn('baseColor * (1.f - max(spec.r, max(spec.g, spec.b))) : baseColor', standard)
        self.assertIn('ms.sampleTexture(data.texBaseColor, s, sd.uv, data.baseColor, lod).rgb', standard)
        self.assertIn('ms.sampleTexture(data.texSpecular, s, sd.uv, data.specular, lod)', standard)

    def test_alpha_and_emission_apply_factor_only_to_marked_materials(self):
        result = patch_sources(self.original)
        system = result['system']
        self.assertIn('md.flags & (1u << 20)', system)
        self.assertIn('alpha *= float(md.baseColor.a)', system)
        self.assertIn('md.emissive * sampleTexture(md.texEmissive', system)
        final = result['finalize']
        self.assertIn('materialData.flags & (1u << 20)', final)
        self.assertIn('isEmissiveTextured(tri.materialID)', final)
        self.assertIn('averageEmissiveColor *= materialData.emissive', final)

    def test_changed_or_duplicate_pinned_shader_fails_closed(self):
        broken = dict(self.original)
        broken['standard'] = broken['standard'].replace('const float4 spec = ', 'const float4 spec_changed = ', 1)
        with self.assertRaises(ValueError):
            patch_sources(broken)
        broken = dict(self.original)
        broken['finalize'] += '\nfloat3 averageRadiance = averageEmissiveColor * materialData.emissiveFactor;\n'
        with self.assertRaises(ValueError):
            patch_sources(broken)

    def test_srgb_rgb_and_linear_normal_slot_contract_is_pinned(self):
        text = (SHADERS / 'Scene/Material/StandardMaterial.cpp').read_text(encoding='utf8')
        self.assertIn('TextureSlotInfo{"specular", TextureChannelFlags::RGBA, true}', text)
        self.assertIn('"normal", TextureChannelFlags::RGB, false', text)
        self.assertIn('"emissive", TextureChannelFlags::RGB, true', text)

if __name__ == '__main__': unittest.main()
