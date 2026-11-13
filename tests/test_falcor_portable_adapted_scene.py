"""Portable scene plans use workspace paths and reject path escapes."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.falcor import adapted_scene_loader, prepare_adapted_scene


class PortableAdaptedSceneTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.root=self.base/'first';self.root.mkdir()
        for name in ('adapted_scene_loader.py','donut_scene_adapter.py','gltf_materials.py','prepare_adapted_scene.py','project_paths.py'):
            path=self.root/'scripts/falcor'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(name)
        (self.root/'assets').mkdir()
        self.model=self.root/'assets/model.gltf'
        self.model.write_text(json.dumps({'asset':{'version':'2.0'},'materials':[]}),encoding='utf8')
        (self.root/'assets/scene.json').write_text(json.dumps({'models':['model.gltf'],'graph':[{'model':0}]}),encoding='utf8')
        (self.root/'runtime.json').write_text('{}',encoding='utf8')
        self.spec={'scene_id':'test','view_id':'view-a','scene_file':'assets/scene.json','asset_root':'assets',
                   'animation_policy':'source_default_disabled','source_lighting_model':'rtxdi_fullsample',
                   'environment':{'kind':'none'},'approximations':{},'camera':{}}
        (self.root/'spec.json').write_text(json.dumps(self.spec),encoding='utf8')

    def prepare(self):
        with patch.object(prepare_adapted_scene,'ROOT',self.root), \
             patch.object(prepare_adapted_scene,'__file__',str(self.root/'scripts/falcor/prepare_adapted_scene.py')):
            return prepare_adapted_scene.prepare('spec.json','runs/frozen','runtime.json')

    def test_generated_scene_is_relative_and_reloads_under_another_root(self):
        config_path=self.prepare()
        config=json.loads(config_path.read_text(encoding='utf8'))
        self.assertEqual(config['scene_source'],'runs/frozen/adapted.pyscene')
        for row in config['resources']+config['sources']:
            self.assertFalse(Path(row['path']).is_absolute(),row['path'])
        self.assertIn('scripts/falcor/project_paths.py',{row['path'] for row in config['sources']})
        plan_path=self.root/'runs/frozen/scene-plan.json'
        data=json.loads(plan_path.read_text(encoding='utf8'))
        self.assertEqual(data['path_format'],'workspace-relative-v1')
        self.assertEqual(data['models'][0]['source'],'assets/model.gltf')
        self.assertEqual(data['models'][0]['descriptor'],'runs/frozen/model-00.labgltf')
        descriptor=self.root/'runs/frozen/model-00.labgltf'
        source=descriptor.read_text(encoding='utf8').splitlines()[0]
        self.assertFalse(Path(source).is_absolute())
        self.assertEqual((descriptor.parent/source).resolve(),self.model.resolve())
        scene_script=(self.root/'runs/frozen/adapted.pyscene').read_text(encoding='utf8')
        self.assertNotIn(str(self.root),scene_script)
        self.assertEqual(scene_script,prepare_adapted_scene.build_scene_script())
        moved=self.base/'second';shutil.copytree(self.root,moved)
        captured={}
        def call(builder,falcor,scene,models,**kwargs):
            captured.update(scene=scene,models=models);return {'ok':True}
        with patch.object(adapted_scene_loader,'load_adapted_scene',side_effect=call):
            result=adapted_scene_loader.load_plan_file(object(),object(),moved/'runs/frozen/scene-plan.json',project_root=moved,
                                                       factor_shader_verified=True,material_optimization_disabled=True)
        self.assertEqual(result,{'ok':True})
        self.assertEqual(captured['models'][0]['source'],str(moved/'assets/model.gltf'))
        self.assertEqual(captured['models'][0]['descriptor'],str(moved/'runs/frozen/model-00.labgltf'))
        self.assertEqual(captured['scene']['actions'][0]['source'],str(moved/'assets/model.gltf'))

    def test_spec_inputs_cannot_escape_workspace(self):
        self.spec['scene_file']='../outside.json'
        (self.root/'spec.json').write_text(json.dumps(self.spec),encoding='utf8')
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse((self.root/'runs/frozen').exists())

    def test_plan_rejects_traversal_and_foreign_absolute_paths(self):
        self.prepare();path=self.root/'runs/frozen/scene-plan.json'
        valid=json.loads(path.read_text(encoding='utf8'))
        for bad in ('../../outside.gltf',str(self.base/'outside.gltf'),r'Z:\other\source.gltf'):
            with self.subTest(path=bad):
                doc=json.loads(json.dumps(valid));doc['models'][0]['source']=bad
                path.write_text(json.dumps(doc),encoding='utf8')
                with self.assertRaises(ValueError):
                    adapted_scene_loader.load_plan_file(object(),object(),path,project_root=self.root,
                                                       factor_shader_verified=True,material_optimization_disabled=True)

    def test_historical_absolute_plan_under_current_workspace_can_load(self):
        self.prepare();path=self.root/'runs/frozen/scene-plan.json'
        doc=json.loads(path.read_text(encoding='utf8'))
        doc.pop('path_format')
        # Legacy plans had absolute paths for all explicitly known path fields.
        from scripts.falcor.project_paths import remap_plan_paths
        absolute=remap_plan_paths(doc,self.root,to_absolute=True)
        path.write_text(json.dumps(absolute),encoding='utf8')
        with patch.object(adapted_scene_loader,'load_adapted_scene',return_value={'ok':True}):
            self.assertEqual(adapted_scene_loader.load_plan_file(object(),object(),path,project_root=self.root,
                             factor_shader_verified=True,material_optimization_disabled=True),{'ok':True})


if __name__=='__main__':unittest.main()
