import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from scripts.falcor.donut_scene_adapter import plan_scene, require_supported, apply_plan, parse_jsonc

class DonutSceneAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'m.gltf').write_text(json.dumps({'asset':{'version':'2.0'},'buffers':[{'uri':'data.bin'}],
          'images':[{'uri':'missing.png'},{'uri':'a.dds'}],
          'textures':[{'source':0,'extensions':{'MSFT_texture_dds':{'source':1}}}]}))
        (self.root/'data.bin').write_bytes(b'buffer')
        (self.root/'a.dds').write_bytes(b'DDS texture')
        (self.root/'x.ies').write_bytes(b'IESNA: test')
        (self.root/'env.hdr').write_bytes(b'light data')
        self.path = self.root/'scene.json'
    def plan(self, data, **kw):
        self.path.write_text(json.dumps(data))
        kw.setdefault('source_lighting_model','donut')
        return plan_scene(self.path,self.root,environment={'kind':'none'},**kw)
    def test_jsonc_preserves_strings_and_removes_comments_and_trailing_commas(self):
        self.assertEqual(parse_jsonc('{"url":"https://a//b",/* comment */"x":[1,2,],}'), {'url':'https://a//b','x':[1,2]})
        with self.assertRaises(ValueError): parse_jsonc('{"a": 1, /* unclosed')
    def test_dependencies_choose_dds_and_hash_actual_assets(self):
        p=self.plan({'models':['m.gltf'],'graph':[{'name':'A','model':0}]})
        require_supported(p)
        self.assertEqual({Path(d['path']).name for d in p['dependencies']}, {'scene.json','m.gltf','data.bin','a.dds'})
        self.assertTrue(all(len(d['sha256'])==64 for d in p['dependencies']))
    def test_hierarchy_world_transform_is_applied_to_model_and_light(self):
        p=self.plan({'models':['m.gltf'],'graph':[{'name':'root','translation':[2,0,0],'rotation':[0,0,0.7071067811865475,0.7071067811865476],
             'children':[{'name':'child','translation':[1,0,0],'model':0},{'name':'pt','type':'PointLight','translation':[0,1,0],'intensity':2,'color':[1,.5,.25]}]}]})
        require_supported(p)
        model=next(a for a in p['actions'] if a['kind']=='model')
        light=next(a for a in p['actions'] if a['kind']=='light')
        self.assertAlmostEqual(model['world_matrix'][0][3],2)
        self.assertAlmostEqual(model['world_matrix'][1][3],1)
        self.assertAlmostEqual(light['position'][0],1)
        self.assertAlmostEqual(light['position'][1],0)
    def test_default_rejects_unimplemented_physics_before_any_builder_mutation(self):
        p=self.plan({'models':['m.gltf'],'graph':[{'name':'A','model':0},{'name':'spot','type':'SpotLight','radius':.01,'range':10,'profile':'x.ies','innerAngle':20,'outerAngle':30,'intensity':1}]}, ies_dirs=[self.root])
        self.assertEqual({i['code'] for i in p['issues'] if i['severity']=='error'}, {'light_radius','light_range','light_ies'})
        operations=[]
        with self.assertRaises(ValueError):apply_plan(p,SimpleNamespace(),SimpleNamespace(),lambda *args:operations.append(args))
        self.assertEqual(operations,[])
    def test_approximations_are_opt_in_specific_and_keep_original_ies(self):
        p=self.plan({'graph':[{'name':'spot','type':'SpotLight','radius':.01,'range':10,'profile':'x.ies','innerAngle':20,'outerAngle':30,'intensity':1}]}, ies_dirs=[self.root],approximations={'light_radius':'delta','light_range':'unbounded','light_ies':'omit'})
        require_supported(p)
        self.assertEqual({i['code'] for i in p['issues'] if i['severity']=='approximation'}, {'light_radius','light_range','light_ies'})
        a=p['actions'][0]
        self.assertEqual(a['source']['profile'],'x.ies')
        self.assertIn('x.ies',{Path(d['path']).name for d in p['dependencies']})
    def test_animations_cameras_and_auxiliary_fields_are_explicit(self):
        data={'graph':[{'name':'camera','type':'PerspectiveCamera','verticalFov':1.0}], 'animations':[{'name':'A'}], 'rtxgi-volumes':[{'name':'g'}]}
        p=self.plan(data)
        self.assertEqual({i['code'] for i in p['issues'] if i['severity']=='error'}, {'animation_policy','camera_policy','top_level_unsupported'})
        q=self.plan(data,animation_policy='source_default_disabled',camera_policy='external',ignored_top_level={'rtxgi-volumes':'not used by path tracer'})
        require_supported(q)
        self.assertFalse(q['animation']['time_zero_applied'])
        self.assertTrue(q['runtime_requirements']['disable_scene_animation'])
        self.assertEqual(q['ignored_top_level']['rtxgi-volumes'],'not used by path tracer')
    def test_unexpected_field_cannot_be_whitelisted_as_approximation(self):
        with self.assertRaises(ValueError):
            self.plan({'graph':[{'name':'x','type':'QuantumLight'}]},approximations={'unknown_node_type':'ignore'})
        p=self.plan({'graph':[{'name':'x','type':'QuantumLight'}]})
        with self.assertRaises(ValueError):require_supported(p)
    def test_asset_change_rejected_before_applying_scene(self):
        p=self.plan({'models':['m.gltf'],'graph':[{'name':'A','model':0}]})
        (self.root/'a.dds').write_bytes(b'changed')
        calls=[]
        with self.assertRaises(ValueError): apply_plan(p,SimpleNamespace(),SimpleNamespace(),lambda *args:calls.append(args))
        self.assertEqual(calls,[])
    def test_procedural_environment_substitution_needs_explicit_policy(self):
        self.path.write_text('{}')
        p=plan_scene(self.path,self.root,environment={'kind':'procedural','fallback_hdr':str(self.root/'env.hdr'),'intensity_ev':0})
        with self.assertRaises(ValueError):require_supported(p)
        q=plan_scene(self.path,self.root,environment={'kind':'procedural','fallback_hdr':str(self.root/'env.hdr'),'intensity_ev':0},approximations={'procedural_environment':'hdr_substitute'})
        require_supported(q)
        self.assertEqual(q['environment']['source_kind'],'procedural')
        self.assertEqual(q['environment']['effective_kind'],'hdr')
        self.assertIn('env.hdr',{Path(d['path']).name for d in q['dependencies']})
    def test_model_loader_receives_world_matrix(self):
        p=self.plan({'models':['m.gltf'],'graph':[{'translation':[3,2,1],'model':0}]})
        calls=[]
        apply_plan(p,SimpleNamespace(),SimpleNamespace(),lambda *args:calls.append(args))
        self.assertEqual(len(calls),1)
        self.assertEqual(Path(calls[0][0]).name,'m.gltf')
        self.assertEqual([calls[0][1][i][3] for i in range(3)],[3,2,1])
    def test_baked_procedural_sky_requires_and_hashes_receipt(self):
        self.path.write_text('{}')
        env={'kind':'procedural','baked_hdr':str(self.root/'env.hdr')}
        with self.assertRaises(ValueError):
            plan_scene(self.path,self.root,environment=env,approximations={'procedural_environment':'baked_hdr'})
        receipt=self.root/'receipt.json';receipt.write_text('{}')
        env['bake_receipt']=str(receipt)
        plan=plan_scene(self.path,self.root,environment=env,approximations={'procedural_environment':'baked_hdr'})
        require_supported(plan)
        self.assertEqual({Path(x['path']).name for x in plan['dependencies']},{'scene.json','env.hdr','receipt.json'})
    def test_git_lfs_pointer_is_rejected(self):
        (self.root/'data.bin').write_text('version https://git-lfs.github.com/spec/v1\noid sha256:bad\n')
        with self.assertRaisesRegex(ValueError,'Unresolved Git LFS'):
            self.plan({'models':['m.gltf']})
    def test_spotlight_angles_intensity_and_direction_follow_donut(self):
        scene={'graph':[{'name':'spot','type':'SpotLight','translation':[1,2,3],
                         'rotation':[0,0.7071067811865475,0,0.7071067811865476],
                         'intensity':4,'color':[1,.5,.25],'innerAngle':60,'outerAngle':90}]}
        p=self.plan(scene)
        created=[]
        class FakeLight:
            def __init__(self,name): self.name=name
        f=SimpleNamespace(PointLight=FakeLight,float3=lambda *xyz: xyz)
        apply_plan(p,SimpleNamespace(addLight=created.append),f,None)
        light=created[0]
        self.assertAlmostEqual(light.openingAngle,math.pi/2)
        self.assertAlmostEqual(light.penumbraAngle,math.pi/6)
        self.assertEqual(light.intensity,(4,2,1))
        self.assertEqual(light.position,(1,2,3))
        self.assertAlmostEqual(light.direction[0],-1)
        self.assertAlmostEqual(light.direction[2],0)
        def smoothstep(a,b,x):
            t=max(0,min(1,(x-a)/(b-a)))
            return t*t*(3-2*t)
        # Donut directly uses inner/outer angles; Falcor uses remaining cone angle.
        for angle in [0,60,65,75,85,90,120]:
            theta=math.radians(angle)
            donut=1-smoothstep(math.pi/3,math.pi/2,theta)
            falcor=0 if theta>light.openingAngle else smoothstep(0,light.penumbraAngle,light.openingAngle-theta)
            self.assertAlmostEqual(donut,falcor)
        # RTXDI FullSample instead smoothsteps in cosine space; it is not equivalent.
        rtxdi=smoothstep(0,1-60/90,math.cos(math.radians(75)))
        self.assertGreater(rtxdi,0.85)
        self.assertAlmostEqual(1-smoothstep(60,90,75),0.5)
    def test_rtxdi_spot_falloff_requires_explicit_policy_and_records_range_semantics(self):
        scene={'graph':[{'name':'spot','type':'SpotLight','radius':0,'range':10,'innerAngle':60,'outerAngle':90}]}
        p=self.plan(scene,source_lighting_model=None)
        self.assertIn('source_lighting_model',{i['code'] for i in p['issues']})
        q=self.plan(scene,source_lighting_model='rtxdi_fullsample')
        self.assertEqual({i['code'] for i in q['issues']},{'rtxdi_spot_falloff'})
        with self.assertRaises(ValueError):require_supported(q)
        q=self.plan(scene,source_lighting_model='rtxdi_fullsample',approximations={'rtxdi_spot_falloff':'donut_angular'})
        require_supported(q)
        self.assertEqual(q['issues'][0]['severity'],'approximation')
        self.assertEqual(q['source_lighting_model'],'rtxdi_fullsample')
        self.assertIn('does not use range',q['actions'][0]['source_range_semantics'])
if __name__=='__main__':unittest.main()
