from scripts.falcor import adapted_scene_loader as loader
import unittest
from unittest.mock import patch


class AdaptedSceneLoaderTests(unittest.TestCase):
    def test_loader_rejects_model_transform_mismatch_before_scene_mutation(self):
        scene={'actions':[{'kind':'model','source':'a.gltf','world_matrix':[[1]]}]}
        models=[{'source':'a.gltf','world_matrix':[[2]],'material_plan':{'source':'a.gltf'}}]
        with self.assertRaisesRegex(ValueError, 'matrix mismatch'):
            loader.load_adapted_scene(object(),object(),scene,models,factor_shader_verified=True,material_optimization_disabled=True)


    def test_loader_matches_order_and_binds_each_import(self):
        class Builder:
            materials=[]
            def importScene(self,path): self.materials.append(path)
        calls=[]
        def apply_scene(plan,builder,falcor,callback):
            for action in plan['actions']: callback(action['source'],action['world_matrix'])
            return ['limits']
        def apply_material(builder,plan,falcor,**kwargs):
            calls.append((plan['source'],kwargs['material_offset']))
            return {'source':plan['source']}
        models=[{'source':source,'world_matrix':[[i]],'descriptor':source+'.labgltf',
                 'material_plan':{'source':source}} for i,source in enumerate(('a','b'))]
        scene={'actions':[{'kind':'model','source':m['source'],'world_matrix':m['world_matrix']} for m in models]}
        with patch.object(loader.donut_scene_adapter, 'apply_plan', apply_scene), patch.object(loader.gltf_materials, 'apply_material_plan', apply_material):
            result=loader.load_adapted_scene(Builder(),object(),scene,models,factor_shader_verified=True,material_optimization_disabled=True)
        self.assertEqual(calls, [('a',0),('b',1)])
        self.assertEqual(result['issues'], ['limits'])


if __name__ == '__main__': unittest.main()
