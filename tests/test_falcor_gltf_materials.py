import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.falcor.gltf_materials import build_material_plan, apply_material_plan, verify_plan_resources, verify_texture_format, match_materials_by_name


class MaterialPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'texture.dds').write_bytes(b'DDS ' + b'fixture')
        self.scene = self.root / 'scene.gltf'

    def save(self, materials, **extra):
        data = {'asset': {'version': '2.0'}, 'images': [{'uri': 'not-present.png'}, {'uri': 'texture.dds'}],
                'textures': [{'source': 0, 'extensions': {'MSFT_texture_dds': {'source': 1}}}],
                'materials': materials, **extra}
        self.scene.write_text(json.dumps(data), encoding='utf8')
        return self.scene

    def test_specgloss_dds_factors_and_provenance(self):
        p = self.save([{'name': 'surface', 'alphaMode': 'MASK', 'alphaCutoff': .4,
            'extensions': {'KHR_materials_pbrSpecularGlossiness': {'diffuseFactor': [.2, .3, .4, .8],
                'specularFactor': [.6, .7, .8], 'glossinessFactor': .9,
                'diffuseTexture': {'index': 0}, 'specularGlossinessTexture': {'index': 0}}}}])
        plan = build_material_plan(p)
        row = plan['materials'][0]
        self.assertEqual(row['model'], 'specular_glossiness')
        self.assertEqual(row['textures']['base_color']['uri'], 'texture.dds')
        self.assertEqual(row['textures']['base_color']['color_space'], 'srgb')
        self.assertEqual(row['textures']['specular']['color_space'], 'srgb')
        self.assertEqual(row['base_color_factor'], [.2, .3, .4, .8])
        self.assertEqual(row['specular_factor'], [.6, .7, .8])
        self.assertEqual(row['glossiness_factor'], .9)
        self.assertAlmostEqual(row['effective_alpha_cutoff'], .4)
        self.assertTrue(plan['requires_texture_factor_shader'])
        self.assertEqual(plan['source_sha256'], hashlib.sha256(p.read_bytes()).hexdigest())
        self.assertEqual(row['textures']['base_color']['sha256'], hashlib.sha256((self.root/'texture.dds').read_bytes()).hexdigest())

    def test_metalrough_transmission_emission_and_color_spaces(self):
        p = self.save([{'name':'glass', 'pbrMetallicRoughness': {'metallicFactor': 0, 'roughnessFactor': .1},
            'normalTexture': {'index':0}, 'emissiveTexture': {'index':0}, 'emissiveFactor':[.5,.6,.7],
            'extensions': {'KHR_materials_transmission': {'transmissionFactor': .95},
                           'KHR_materials_ior': {'ior':1.4}, 'KHR_materials_emissive_strength': {'emissiveStrength':2}}}])
        r=build_material_plan(p)['materials'][0]
        self.assertEqual(r['model'], 'metallic_roughness')
        self.assertEqual(r['transmission_factor'], .95)
        self.assertTrue(r['thin_surface'])
        self.assertEqual(r['ior'], 1.4)
        self.assertEqual(r['emissive_strength'], 2)
        self.assertEqual(r['textures']['normal']['color_space'], 'linear')
        self.assertEqual(r['textures']['emissive']['color_space'], 'srgb')

    def test_blend_requires_explicit_rtxdi_approximation(self):
        p=self.save([{'name':'decal', 'alphaMode':'BLEND',
                      'pbrMetallicRoughness':{'baseColorFactor':[1,1,1,.8], 'baseColorTexture':{'index':0}}}])
        with self.assertRaisesRegex(ValueError, 'BLEND'): build_material_plan(p)
        plan=build_material_plan(p, blend_policy='rtxdi-mask')
        self.assertEqual(plan['materials'][0]['alpha_interpretation'], 'rtxdi-gbuffer-mask-approximation')
        self.assertAlmostEqual(plan['materials'][0]['effective_alpha_cutoff'], .5)
        self.assertTrue(plan['limitations'])

    def test_rejects_unhandled_material_semantics(self):
        cases = [
            {'name':'m','extensions':{'KHR_materials_clearcoat':{}}},
            {'name':'m','extensions':{'KHR_materials_transmission':{'transmissionFactor':1}, 'KHR_materials_volume':{'thicknessFactor':1}}},
            {'name':'m','doubleSided':'false'},
            {'name':'m','normalTexture':{'index':0,'scale':.5}},
            {'name':'m','normalTexture':{'index':0,'texCoord':1}},
            {'name':'m','extensions':{'KHR_materials_transmission':{'transmissionTexture':{'index':0}}}},
            {'name':'m','pbrMetallicRoughness':{'baseColorFactor':[1,1,1,float('nan')]}},
        ]
        for m in cases:
            with self.subTest(m=m):
                with self.assertRaises(ValueError): build_material_plan(self.save([m]))

    def test_duplicate_names_remain_separate_by_index(self):
        rows = build_material_plan(self.save([{'name':'x'}, {'name':'x'}]))['materials']
        self.assertEqual([r['index'] for r in rows], [0, 1])

    def test_resource_audit_detects_source_or_texture_change(self):
        p=self.save([{'name':'m','normalTexture':{'index':0}}])
        plan=build_material_plan(p)
        verify_plan_resources(plan)
        (self.root/'texture.dds').write_bytes(b'DDS changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            verify_plan_resources(plan)
        plan=build_material_plan(p)
        p.write_text('{}',encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'changed'):
            verify_plan_resources(plan)

    def test_apply_uses_marker_and_checks_loaded_format(self):
        plan = build_material_plan(self.save([{'name':'m', 'pbrMetallicRoughness':{'baseColorTexture':{'index':0}}}]))
        class Material:
            def __init__(self, name, model):
                self.name, self.gltfFactorMarker, self.tex = name, True, {}
            def getTexture(self, slot): return self.tex.get(slot)
        class Builder:
            materials = [SimpleNamespace(name='m')]
            def loadMaterialTexture(self, m, slot, path):
                m.tex[slot] = SimpleNamespace(width=2, height=2, format='ResourceFormat.BC7Unorm', mip_count=1)
            def replaceMaterial(self, old, new): pass
            def waitForMaterialTextureLoading(self): pass
        f = SimpleNamespace(GltfFactorMaterial=Material,
            MaterialTextureSlot=SimpleNamespace(BaseColor=0, Specular=1, Normal=2, Emissive=3),
            ShadingModel=SimpleNamespace(SpecGloss=0, MetalRough=1),
            float4=lambda *v: v, float3=lambda *v: v)
        with self.assertRaisesRegex(ValueError, 'color space'):
            apply_material_plan(Builder(), plan, f, factor_shader_verified=True, material_optimization_disabled=True)
        class Unmarked(Material):
            def __init__(self, name, model): super().__init__(name, model); self.gltfFactorMarker = False
        f.GltfFactorMaterial = Unmarked
        with self.assertRaisesRegex(RuntimeError, 'marker'):
            apply_material_plan(Builder(), plan, f, factor_shader_verified=True, material_optimization_disabled=True)

    def test_transmission_sets_thin_surface_before_binding(self):
        plan=build_material_plan(self.save([{'name':'glass','extensions':{'KHR_materials_transmission':{'transmissionFactor':.95}}},
                                            {'name':'opaque'}]))
        class Material:
            def __init__(self,name,model): self.name,self.gltfFactorMarker,self.thinSurface=name,True,False
        class Builder:
            def __init__(self):
                self.materials=[SimpleNamespace(name='glass'),SimpleNamespace(name='opaque')];self.replaced=[]
            def waitForMaterialTextureLoading(self): pass
            def replaceMaterial(self,old,new):self.replaced.append((old,new))
        b=Builder();f=SimpleNamespace(GltfFactorMaterial=Material,
            MaterialTextureSlot=SimpleNamespace(BaseColor=0,Specular=1,Normal=2,Emissive=3),
            ShadingModel=SimpleNamespace(SpecGloss=0,MetalRough=1),float4=lambda *v:v,float3=lambda *v:v)
        apply_material_plan(b,plan,f,factor_shader_verified=True,material_optimization_disabled=True)
        self.assertTrue(b.replaced[0][1].thinSurface)
        self.assertFalse(b.replaced[1][1].thinSurface)
        self.assertTrue(any('thin' in text.lower() and 'approx' in text.lower() for text in plan['limitations']))

    def test_apply_reordered_materials_without_touching_prior_model(self):
        plan = build_material_plan(self.save([{'name':'one','pbrMetallicRoughness':{'metallicFactor':.2}},
                                              {'name':'two','pbrMetallicRoughness':{'metallicFactor':.8}}]))
        class Material:
            def __init__(self, name, model): self.name, self.gltfFactorMarker = name, True
        class Builder:
            def __init__(self):
                self.materials = [SimpleNamespace(name='one'), SimpleNamespace(name='two'), SimpleNamespace(name='one')]
                self.replaced = []
            def waitForMaterialTextureLoading(self): pass
            def replaceMaterial(self, old, new): self.replaced.append((old,new))
        b = Builder()
        f = SimpleNamespace(GltfFactorMaterial=Material,
            MaterialTextureSlot=SimpleNamespace(BaseColor=0,Specular=1,Normal=2,Emissive=3),
            ShadingModel=SimpleNamespace(SpecGloss=0,MetalRough=1),float4=lambda *v:v,float3=lambda *v:v)
        result = apply_material_plan(b, plan, f, factor_shader_verified=True,
                                     material_optimization_disabled=True, material_offset=1)
        self.assertEqual(result['material_count'], 2)
        self.assertIs(b.replaced[0][0], b.materials[2])
        self.assertIs(b.replaced[1][0], b.materials[1])
        self.assertEqual(b.replaced[0][1].specularParams[2], .2)
        self.assertEqual(b.replaced[1][1].specularParams[2], .8)

    def test_material_matching_is_unique_and_offset_isolated(self):
        source = [{'index': 0, 'name': 'one'}, {'index': 1, 'name': 'two'}]
        old = [SimpleNamespace(name='one'), SimpleNamespace(name='two'),
               SimpleNamespace(name='two'), SimpleNamespace(name='one')]
        matching = match_materials_by_name(source, old, material_offset=2)
        self.assertIs(matching[0], old[3]); self.assertIs(matching[1], old[2])
        failures = [
            ([{'index':0,'name':None}, {'index':1,'name':'two'}], old[2:], 0),
            ([{'index':0,'name':'one'}, {'index':1,'name':'one'}], old[2:], 0),
            (source, [SimpleNamespace(name='one'),SimpleNamespace(name='one')], 0),
            (source, [SimpleNamespace(name='one'),SimpleNamespace(name='missing')], 0),
            (source, old, 1),
        ]
        for rows, imported, offset in failures:
            with self.subTest(rows=rows, offset=offset):
                with self.assertRaises(ValueError): match_materials_by_name(rows, imported, material_offset=offset)

    def test_unmatched_material_does_not_replace_anything(self):
        plan = build_material_plan(self.save([{'name':'one'}, {'name':'two'}]))
        class Builder:
            materials = [SimpleNamespace(name='one'),SimpleNamespace(name='unexpected')]
            replaced = []
            def replaceMaterial(self, old, new): self.replaced.append((old,new))
        b = Builder()
        f = SimpleNamespace(GltfFactorMaterial=object)
        with self.assertRaises(ValueError):
            apply_material_plan(b, plan, f, factor_shader_verified=True, material_optimization_disabled=True)
        self.assertEqual(b.replaced, [])

    def test_texture_format_contract(self):
        for fmt in ('ResourceFormat.BC7UnormSrgb', 'ResourceFormat.RGBA8UnormSrgb'):
            verify_texture_format(fmt, 'srgb')
        for fmt in ('ResourceFormat.BC7Unorm', 'ResourceFormat.RGBA16Float'):
            verify_texture_format(fmt, 'linear')
        for fmt, expected in [('ResourceFormat.BC7Unorm', 'srgb'),
                              ('ResourceFormat.BC7UnormSrgb', 'linear'),
                              ('ResourceFormat.Unknown', 'linear'),
                              ('ResourceFormat.SomethingNew', 'linear')]:
            with self.subTest(fmt=fmt, expected=expected):
                with self.assertRaisesRegex(ValueError, 'color space|format'):
                    verify_texture_format(fmt, expected)

    def test_rejects_bad_dds(self):
        (self.root/'texture.dds').write_bytes(b'not dds')
        with self.assertRaisesRegex(ValueError, 'DDS'): build_material_plan(self.save([{'name':'x','normalTexture':{'index':0}}]))


if __name__=='__main__': unittest.main()



