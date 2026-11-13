import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.falcor.adapted_reference_runner import inventory_resources, make_render_script

class AdaptedReferenceRunnerTests(unittest.TestCase):
    def test_records_selected_existing_resources_and_detects_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); gltf=root/'a.gltf'; dds=root/'a.dds'; gltf.write_bytes(b'gltf'); dds.write_bytes(b'dds')
            records=[{'path':str(gltf),'sha256':hashlib.sha256(b'gltf').hexdigest()}, {'path':str(dds),'sha256':hashlib.sha256(b'dds').hexdigest()}]
            actual=inventory_resources(records,root)
            self.assertEqual(set(actual),{'a.gltf','a.dds'})
            dds.write_bytes(b'altered')
            with self.assertRaises(ValueError):inventory_resources(records,root)

    def test_rejects_resource_outside_workspace(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as other:
            root=Path(td); path=Path(other)/'outside.dds';path.write_bytes(b'file')
            with self.assertRaises(ValueError): inventory_resources([{'path':str(path),'sha256':hashlib.sha256(b'file').hexdigest()}],root)

    def test_render_uses_original_seed_camera_and_disables_material_optimization(self):
        camera={'position':[0,0,0],'direction':[0,0,-1],'up':[0,1,0],'vertical_fov':60}
        script=make_render_script(Path('scene.pyscene'),camera,Path('out'),2,4)
        self.assertIn('SceneBuilderFlags.DontOptimizeMaterials',script)
        self.assertIn('tracer.fixedSeed = 2048 + sample',script)
        self.assertIn('camera.animated = False',script)
        self.assertIn('for sample in range(4)',script)

    def test_optional_near_plane_is_rendered_as_python_and_validated(self):
        camera={'position':[0,0,0],'direction':[0,0,-1],'up':[0,1,0],
                'vertical_fov':60,'near_plane':.01}
        script=make_render_script('s.pyscene',camera,'output',0,1)
        compile(script,'render.py','exec')
        self.assertIn('camera.nearPlane = 0.01', script)

    def test_renderer_environment_does_not_leave_bytecode_setting_changed(self):
        import os
        from scripts.falcor.adapted_reference_runner import isolated_python_environment
        with patch.dict(os.environ):
            os.environ.pop('PYTHONDONTWRITEBYTECODE', None)
            with isolated_python_environment():
                self.assertEqual(os.environ['PYTHONDONTWRITEBYTECODE'], '1')
            self.assertNotIn('PYTHONDONTWRITEBYTECODE', os.environ)
            os.environ['PYTHONDONTWRITEBYTECODE']='0'
            with isolated_python_environment():
                self.assertEqual(os.environ['PYTHONDONTWRITEBYTECODE'], '1')
            self.assertEqual(os.environ['PYTHONDONTWRITEBYTECODE'], '0')


if __name__=='__main__': unittest.main()
