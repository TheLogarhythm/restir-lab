import unittest
from scripts.falcor.bistro_gltf_shader_patch import patch_sources

class BistroGltfShaderPatchTests(unittest.TestCase):
    def test_correct_factors_and_emission_light_data(self):
        sources = {
          'standard': 'const float3 baseColor = ms.sampleTexture(data.texBaseColor, s, sd.uv, data.baseColor, lod).rgb;\nconst float4 spec = ms.sampleTexture(data.texSpecular, s, sd.uv, data.specular, lod);\nemission = ms.sampleTexture(data.texEmissive, s, sd.uv, float4(data.emissive, 1), lod).rgb * data.emissiveFactor;',
          'system': 'return sampleTexture(md.texEmissive, s, uv, float4(md.emissive, 1.f), lod).rgb * md.emissiveFactor;',
          'finalize': 'float3 averageRadiance = averageEmissiveColor * materialData.emissiveFactor;',
        }
        result = patch_sources(sources)
        self.assertIn('data.baseColor.rgb *', result['standard'])
        self.assertIn('data.specular *', result['standard'])
        self.assertIn('data.emissive *', result['standard'])
        self.assertIn('md.emissive *', result['system'])
        self.assertIn('isEmissiveTextured', result['finalize'])
        self.assertIn('materialData.emissive', result['finalize'])

    def test_mismatched_source_rejected(self):
        with self.assertRaises(ValueError):
            patch_sources({'standard':'', 'system':'', 'finalize':''})

if __name__ == '__main__': unittest.main()
