import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.falcor import prepare_adapted_scene as prep
from scripts.falcor.adapted_reference_runner import inventory_resources

class PrepareAdaptedSceneTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for name in ['adapted_scene_loader.py','donut_scene_adapter.py','gltf_materials.py','prepare_adapted_scene.py','project_paths.py']:
            p=self.root/'scripts/falcor'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(name)
        self.patch_root=patch.object(prep,'ROOT',self.root);self.patch_root.start();self.addCleanup(self.patch_root.stop)
        self.patch_file=patch.object(prep,'__file__',str(self.root/'scripts/falcor/prepare_adapted_scene.py'));self.patch_file.start();self.addCleanup(self.patch_file.stop)
        self.model=self.root/'model.gltf'
        self.model.write_text(json.dumps({'asset':{'version':'2.0'},'materials':[]}))
        self.scene=self.root/'scene.json';self.scene.write_text(json.dumps({'models':['model.gltf'],'graph':[{'model':0}]}))
        self.runtime=self.root/'runtime-receipt.json';self.runtime.write_text('{}')
        self.spec={'scene_id':'test','view_id':'view-a','scene_file':str(self.scene),'asset_root':str(self.root),
                   'animation_policy':'source_default_disabled','source_lighting_model':'rtxdi_fullsample',
                   'environment':{'kind':'none'},'approximations':{},'camera':{}}
        self.specpath=self.root/'spec.json'
    def prepare(self):
        self.specpath.write_text(json.dumps(self.spec))
        return prep.prepare(self.specpath,self.root/'frozen',self.runtime)
    def test_embedded_punctual_lights_rejected_before_scene_is_written(self):
        for location in ('used','required','root','node'):
            with self.subTest(location=location):
                gltf={'asset':{'version':'2.0'},'materials':[]}
                if location=='used':gltf['extensionsUsed']=['KHR_lights_punctual']
                elif location=='required':gltf['extensionsRequired']=['KHR_lights_punctual']
                elif location=='root':gltf['extensions']={'KHR_lights_punctual':{}}
                else:gltf['nodes']=[{'extensions':{'KHR_lights_punctual':{'light':0}}}]
                self.model.write_text(json.dumps(gltf))
                with self.assertRaisesRegex(ValueError,'Embedded glTF lights'):self.prepare()
                self.assertFalse((self.root/'frozen').exists())
    def test_sky_source_change_is_detected_after_freeze(self):
        sky=self.root/'env.exr';sky.write_bytes(b'fixture')
        code=self.root/'sky-source.py';code.write_text('original')
        digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        receipt=self.root/'sky-receipt.json'
        receipt.write_text(json.dumps({'sha256':digest(sky),'source_sha256':{str(code):digest(code)}}))
        self.spec['environment']={'kind':'procedural','baked_hdr':str(sky),'bake_receipt':str(receipt),
                                  'fallback_hdr':str(self.root/'unused-fallback.exr')}
        self.spec['approximations']={'procedural_environment':'baked_hdr'}
        config=json.loads(self.prepare().read_text())
        inventory_resources(config['sources'],self.root)
        code.write_text('changed')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            inventory_resources(config['sources'],self.root)

if __name__=='__main__':unittest.main()
