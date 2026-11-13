import json,hashlib
from pathlib import Path
import numpy as np
import tempfile
import unittest
from unittest.mock import patch
from scripts.falcor import reference_extension_provenance as p


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data),encoding='utf8')

def baseline(test, tmp_path):
    test.enterContext(patch.object(p, 'ROOT', tmp_path))
    test.enterContext(patch.object(p, 'IMAGE_SHAPE', (1,1,3)))
    import src.image_io.exr as exr
    test.enterContext(patch.object(exr, 'read_exr', lambda path,require_float32=False:np.full((1,1,3),float(Path(path).read_text()),dtype=np.float32)))
    graph=tmp_path/'scripts/falcor/reference_graph.py';graph.parent.mkdir(parents=True);graph.write_text('graph')
    for name in ('falcor-reference-runtime','falcor-gltf-composite-runtime-v3'):
        q=tmp_path/'build'/name/'receipt.json';write(q,{'runtime':name})
    test.enterContext(patch.object(p.reference_runner, 'asset_inventory', lambda c:{c['asset']:sha(tmp_path/c['asset'])}))
    test.enterContext(patch.object(p, '_bistro_equivalent', lambda old,new,root,seed: ({'bistro':'same'},{})))
    root=tmp_path/'runs/refs';root.mkdir(parents=True);views=[];configs=[]
    for i in range(6):
        sid,vid=('bistro','view-a') if i==0 else ('scene'+str(i),'view-a');dir=root/sid/vid;dir.mkdir(parents=True)
        asset=tmp_path/f'asset{i}.bin';asset.write_text('asset')
        cfg={'scene_id':sid,'view_id':vid,'asset':asset.name,'camera':{'position':[0,0,0]}}
        config=tmp_path/f'config{i}.json';write(config,cfg);configs.append(config)
        rec=[];rt=tmp_path/'build'/('falcor-gltf-composite-runtime-v3' if i==0 else 'falcor-reference-runtime')/'receipt.json'
        for k in range(8):
            image=dir/f'seed{k}.exr';image.write_text(str(k));m={'status':'completed','seed_index':k,'samples_per_pixel':1024,'resolution':[1920,1080], 'sample_seed_first':k*1024,'sample_seed_last':k*1024+1023,'graph_sha256':sha(graph),'runtime_receipt_sha256':sha(rt),'config_sha256':sha(config),'scene_config':cfg,'asset_sha256':{asset.name:sha(asset)}}
            manifest=dir/f'seed{k}.json';write(manifest,m);rec.append({'index':k,'path':image.relative_to(root).as_posix(),'sha256':sha(image),'manifest':manifest.relative_to(root).as_posix(),'manifest_sha256':sha(manifest)})
        ref=dir/'reference.exr';ref.write_text('3.5');views.append({'scene_id':sid,'view_id':vid,'reference':ref.relative_to(root).as_posix(),'reference_sha256':sha(ref),'seeds':rec})
    write(root/'manifest.json',{'views':views})
    return root,configs,tmp_path


class ReferenceExtensionProvenanceTests(unittest.TestCase):
    def test_valid_fixture(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        root, configs, _ = baseline(self, Path(folder))
        self.assertEqual(len(p.verify_baseline(root, configs)['views']), 6)

    def test_changed_inputs_are_rejected(self):
        for kind in ('seed', 'graph', 'runtime', 'config', 'asset'):
            with self.subTest(kind=kind):
                folder = self.enterContext(tempfile.TemporaryDirectory())
                root, configs, r = baseline(self, Path(folder))
                targets={'seed':root/'scene1/view-a/seed0.exr','graph':r/'scripts/falcor/reference_graph.py','runtime':r/'build/falcor-reference-runtime/receipt.json','config':configs[1],'asset':r/'asset1.bin'}
                target=targets[kind]
                if kind=='config':
                    data=json.loads(target.read_text());data['unexpected']='modified';write(target,data)
                else:target.write_text('modified')
                with self.assertRaises((ValueError,KeyError,json.JSONDecodeError)):
                    p.verify_baseline(root,configs)

    def test_bistro_scene_migration_difference_is_rejected(self):
        tmp_path = Path(self.enterContext(tempfile.TemporaryDirectory()))
        root=tmp_path/'runs/falcor-pt-spatial-comparison';base=root/'scene-assets/bistro';p1=base/'provenance/frozen-scene-06';p2=base/'frozen-scene';p1.mkdir(parents=True);p2.mkdir(parents=True)
        old={'camera':{'position':[1,2,3]},'expected_material_counts':[],'expected_texture_slots':[],'expected_light_count':0,'expected_environment_present':False,'runtime_receipt_sha256':'x'}
        write(p1/'reference-config.json',old);write(p1/'scene-plan.json',{'models':[],'scene':{}});write(p2/'scene-plan.json',{'models':[],'scene':{}})
        new=dict(old);new['camera']={'position':[1,2,4]};seed={'config_sha256':sha(p1/'reference-config.json')}
        with self.assertRaisesRegex(ValueError, 'camera'):p._bistro_equivalent(old,new,root,seed)

if __name__ == '__main__': unittest.main()
