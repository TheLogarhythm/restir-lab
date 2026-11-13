import unittest
from pathlib import Path
from scripts.falcor.bistro_gltf_material_plan import build_material_plan, effective_alpha_cutoff

class BistroGltfMaterialPlanTests(unittest.TestCase):
    def test_prefers_explicit_dds_and_preserves_factors(self):
        data = {'images': [{'uri': 'fallback.png'}, {'uri': 'source.dds'}],
                'textures': [{'source': 0, 'extensions': {'MSFT_texture_dds': {'source': 1}}}],
                'materials': [{'name': 'm', 'alphaMode': 'MASK', 'alphaCutoff': .3,
                  'extensions': {'KHR_materials_pbrSpecularGlossiness': {'diffuseFactor': [.2,.3,.4,.5],
                    'specularFactor': [.6,.7,.8], 'glossinessFactor': .9, 'diffuseTexture': {'index': 0}}}}]}
        item = build_material_plan(data)[0]
        self.assertEqual(item['model'], 'specular_glossiness')
        self.assertEqual(item['textures']['base_color'], 'source.dds')
        self.assertEqual(item['base_color_factor'], [.2,.3,.4,.5])
        self.assertEqual(item['specular_factor'], [.6,.7,.8])
        self.assertEqual(item['glossiness_factor'], .9)
        self.assertEqual(item['alpha_mode'], 'MASK')
        self.assertEqual(item['alpha_cutoff'], .3)

    def test_opaque_never_discards_alpha(self):
        self.assertEqual(effective_alpha_cutoff('OPAQUE', .5), 0.0)
        self.assertEqual(effective_alpha_cutoff('MASK', .3), .3)
        self.assertAlmostEqual(effective_alpha_cutoff('MASK', .5, .86), .5 / .86)
        with self.assertRaises(ValueError): effective_alpha_cutoff('BLEND', .5)

    def test_transmission_is_preserved(self):
        data={'images': [], 'textures': [], 'materials': [{'name':'g', 'extensions': {'KHR_materials_transmission': {'transmissionFactor':.95}}}]}
        self.assertEqual(build_material_plan(data)[0]['transmission_factor'], .95)

    def test_rejects_texture_uv_not_zero(self):
        data={'images':[{'uri':'a.dds'}], 'textures':[{'source':0}], 'materials':[{'name':'m','normalTexture':{'index':0,'texCoord':1}}]}
        with self.assertRaises(ValueError): build_material_plan(data)

if __name__ == '__main__': unittest.main()


