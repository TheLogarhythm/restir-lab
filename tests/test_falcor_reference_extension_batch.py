import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.falcor import reference_extension_batch as batch
from scripts.falcor import cgns_pt_six_view_smoke as six


class ExtensionBatchTests(unittest.TestCase):
    def test_code_identity_binds_portable_path_helper(self):
        identity=batch.code_identity()
        self.assertEqual(identity['scripts/falcor/project_paths.py'],
                         batch.sha(batch.ROOT/'scripts/falcor/project_paths.py'))

    def test_portable_extension_resume_after_workspace_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=Path(tmp)/'first';old=first/'runs/refs';old.mkdir(parents=True)
            out=old/'reference-16384-test';keys=sorted(batch.EXPECTED)
            (old/'manifest.json').write_text(json.dumps({'views':[{'scene_id':a,'view_id':b} for a,b in keys]}))
            configs=[]
            for a,b in keys:
                path=first/f'{a}-{b}.json';path.write_text(json.dumps({'scene_id':a,'view_id':b}));configs.append(path)
            def baseline(old_root,paths):
                views=[]
                for path in paths:
                    config=json.loads(path.read_text());a,b=config['scene_id'],config['view_id']
                    views.append({'scene_id':a,'view_id':b,'config_path':str(path),'config_sha256':batch.sha(path),
                                  'old_reference':str(old_root/'old.exr'),'old_seeds':[],
                                  'adapted':(a,b)==('bistro','view-a')})
                return {'schema_version':1,'old_root':str(old_root),'views':views}
            def find(view_dir,config,entry,identity):
                attempt=view_dir/'attempts'/'attempt-01'
                if not attempt.exists():return {}
                return {i:(attempt,{'block':i,'file':f'{i}.exr','sha256':str(i),'camera_sha256':'camera',
                                   'progress_sha256':'progress','scene_state_sha256':'state','scene_audit_sha256':None},
                           {'status':'completed'}) for i in range(8)}
            def launch(cfg,attempt,blocks,*args,**kwargs):
                attempt.mkdir(parents=True);(attempt/'manifest.json').write_text('{}')
            with patch.object(batch,'ROOT',first),patch.object(batch,'verify_runtimes'), \
                 patch.object(batch.provenance,'verify_baseline',side_effect=baseline), \
                 patch.object(batch,'code_identity',return_value={'code':'fixed'}), \
                 patch.object(batch,'old_images',return_value=[first/'old' for _ in range(8)]), \
                 patch.object(batch,'find_blocks',side_effect=find),patch.object(batch,'recheck_view'), \
                 patch.object(batch.extension,'launch',side_effect=RuntimeError('interrupted')):
                with self.assertRaisesRegex(RuntimeError,'interrupted'):batch._run_batch(old,configs,out)
            data=json.loads((out/'baseline.json').read_text())
            self.assertEqual(data['schema_version'],2)
            self.assertEqual(data['old_root'],'runs/refs')
            baseline_file=out/'baseline.json';status_file=out/'manifest.json'
            portable_bytes=baseline_file.read_bytes();status_bytes=status_file.read_bytes()
            baseline_file.write_text(json.dumps(baseline(old,configs)))
            legacy_status=json.loads(status_bytes);legacy_status['schema_version']=1
            legacy_status.pop('path_base');legacy_status['old_root']=str(old)
            legacy_status['baseline_sha256']=batch.sha(baseline_file)
            status_file.write_text(json.dumps(legacy_status))
            with patch.object(batch,'ROOT',first),patch.object(batch,'verify_runtimes'), \
                 patch.object(batch.provenance,'verify_baseline',side_effect=baseline), \
                 patch.object(batch,'code_identity',return_value={'code':'fixed'}), \
                 patch.object(batch,'old_images',return_value=[first/'old' for _ in range(8)]), \
                 patch.object(batch,'find_blocks',side_effect=find),patch.object(batch,'recheck_view'), \
                 patch.object(batch.extension,'launch',side_effect=RuntimeError('legacy reached renderer')):
                with self.assertRaisesRegex(RuntimeError,'legacy reached renderer'):
                    batch._run_batch(old,configs,out,resume=True)
            baseline_file.write_bytes(portable_bytes);status_file.write_bytes(status_bytes)
            second=Path(tmp)/'second';shutil.copytree(first,second);first.rename(Path(tmp)/'unavailable')
            newold=second/'runs/refs';newout=newold/'reference-16384-test'
            with patch.object(batch,'ROOT',second),patch.object(batch,'verify_runtimes'), \
                 patch.object(batch.provenance,'verify_baseline',side_effect=baseline), \
                 patch.object(batch,'code_identity',return_value={'code':'fixed'}), \
                 patch.object(batch,'old_images',return_value=[second/'old' for _ in range(8)]), \
                 patch.object(batch,'find_blocks',side_effect=find),patch.object(batch,'recheck_view'), \
                 patch.object(batch.extension,'launch',side_effect=launch), \
                 patch.object(batch,'average_sixteen_seed_exrs',side_effect=lambda paths,dest:dest.write_bytes(b'new-reference')):
                batch._run_batch(newold,[second/p.name for p in configs],newout,resume=True)
            self.assertEqual(json.loads((newout/'manifest.json').read_text())['status'],'completed')

    def test_portable_baseline_is_resolved_by_six_view_reader_after_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=Path(tmp)/'first';old=first/'runs/refs';extension=old/'reference-16384-test'
            extension.mkdir(parents=True)
            (old/'manifest.json').write_text('{}')
            config=first/'config.json';config.write_text('{}')
            ref=old/'reference.exr';ref.write_bytes(b'reference')
            seed=old/'seed.exr';seed.write_bytes(b'seed')
            manifest=old/'seed.json';manifest.write_text('{}')
            entry={'scene_id':'classroom','view_id':'view-a','adapted':False,
                   'config_path':str(config),'config_sha256':batch.sha(config),
                   'old_reference':str(ref),'old_reference_sha256':batch.sha(ref),
                   'old_seeds':[{'index':0,'image':str(seed),'sha256':batch.sha(seed),
                                 'manifest':str(manifest),'manifest_sha256':batch.sha(manifest)}]}
            baseline={'schema_version':1,'kind':'reference_extension_baseline','old_root':str(old),'views':[entry]}
            portable=batch.provenance.portable_baseline(baseline, first)
            self.assertEqual(portable['schema_version'],2)
            self.assertEqual(portable['path_base'],'workspace')
            for value in [portable['old_root'],portable['views'][0]['config_path'],
                          portable['views'][0]['old_reference'],portable['views'][0]['old_seeds'][0]['image'],
                          portable['views'][0]['old_seeds'][0]['manifest']]:
                self.assertFalse(Path(value).is_absolute())
            baseline_path=extension/'baseline.json';baseline_path.write_text(json.dumps(portable))
            (extension/'manifest.json').write_text(json.dumps({'status':'completed','baseline_sha256':batch.sha(baseline_path),
                                                              'old_manifest_sha256':batch.sha(old/'manifest.json')}))
            second=Path(tmp)/'second';shutil.copytree(first,second);first.rename(Path(tmp)/'unavailable')
            with patch.object(six,'ROOT',second),patch.object(six,'REFERENCE',second/'runs/refs'), \
                 patch.object(six,'EXTENSION',second/'runs/refs/reference-16384-test'), \
                 patch.object(six,'KEYS',{('classroom','view-a')}):
                result=six.historical_frozen_views()[('classroom','view-a')]
                self.assertEqual(Path(result['config_path']),second/'config.json')
                self.assertEqual(six.old_seed_manifest(result,0),second/'runs/refs/seed.json')
            invalid=json.loads(json.dumps(portable));invalid['views'][0]['config_path']='../outside.json'
            with self.assertRaises(ValueError):batch.provenance.expand_portable_baseline(invalid,second)

    def test_old_inputs_require_eight_verified_unique_seeds_and_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); view={'scene_id':'bistro','view_id':'view-a','reference':'reference.exr','seed_count':8,'spp_per_seed':1024,'resolution':[1920,1080],'seeds':[]}
            (root/'reference.exr').write_bytes(b'reference');view['reference_sha256']=batch.sha(root/'reference.exr')
            for i in range(8):
                f=root/f'seed-{i}.exr';f.write_bytes(str(i).encode());m=root/f'seed-{i}.json';m.write_text(json.dumps({'status':'completed','kind':'reference_seed','seed_index':i,'samples_per_pixel':1024,'sample_seed_first':i*1024,'sample_seed_last':i*1024+1023,'resolution':[1920,1080],'artifacts':[{'file':f.name,'sha256':batch.sha(f)}]}))
                view['seeds'].append({'index':i,'path':f.name,'sha256':batch.sha(f),'manifest':m.name,'manifest_sha256':batch.sha(m)})
            images=batch.old_images(root,view);self.assertEqual(len(images),8)
            (root/'seed-3.exr').write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'hash'):batch.old_images(root,view)

    def test_completed_block_requires_exact_samples_camera_and_float_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);d=root/'block-01';d.mkdir();(root/'scene-state.json').write_text('{}');(d/'camera.json').write_text('{}');(d/'progress.json').write_text(json.dumps({'block':0,'samples':1024,'seed_first':8192,'seed_last':9215}));(d/'capture.AccumulatePass.output.1024.exr').write_bytes(b'exr')
            image=d/'capture.AccumulatePass.output.1024.exr';(d/'progress.json').write_text(json.dumps({'status':'submitted','block':0,'samples':1024,'seed_first':8192,'seed_last':9215,'exr_file':image.name,'exr_sha256':batch.sha(image),'camera_sha256':batch.sha(d/'camera.json'),'scene_state_sha256':batch.sha(root/'scene-state.json'),'scene_audit_sha256':None}))
            with patch.object(batch.reference_runner,'validate_camera_records'),patch.object(batch.run,'inspect_hdr'):
                result=batch.validate_block(root,0,{'camera':{}},False)
                self.assertEqual(result['seed_first'],8192)
                (d/'progress.json').write_text(json.dumps({'block':0,'samples':1024,'seed_first':8191,'seed_last':9215}))
                with self.assertRaisesRegex(ValueError,'progress'):batch.validate_block(root,0,{'camera':{}},False)

    def test_rejects_paths_outside_old_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): batch.within(Path(tmp),'../outside.exr')

    def test_partial_attempt_reuses_only_valid_completed_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            attempt=Path(tmp); config={'camera':{}}; baseline={'config_sha256':'cfg','asset_sha256':{'a':'a'},'source_sha256':{},'graph_sha256':'graph','runtime_receipt_sha256':'runtime','adapted':False}
            identity={'scripts/falcor/reference_extension_runner.py':'runner','scripts/falcor/reference_runner.py':'dep1','scripts/falcor/adapted_reference_runner.py':'dep2'}
            data={'status':'failed','kind':'reference_extension','scene_config':config,'config_sha256':'cfg','samples_per_block':1024,'resolution':[1920,1080],'asset_sha256':{'a':'a'},'source_sha256':{},'graph_sha256':'graph','runtime_receipt_sha256':'runtime','runner_sha256':'runner','blocks':[0,1,2], 'dependency_sha256':{k:v for k,v in identity.items() if k!='scripts/falcor/reference_extension_runner.py'},'error':'renderer failed with exit code -1'}
            (attempt/'manifest.json').write_text(json.dumps(data))
            def block(_,index,*args):
                if index==2:raise FileNotFoundError('unfinished')
                return {'block':index,'sha256':str(index)}
            with patch.object(batch,'validate_block',side_effect=block):
                _,blocks=batch.attempt_record(attempt,config,baseline,identity)
            self.assertEqual(blocks,[])
            data['error']='Scene inputs changed';(attempt/'manifest.json').write_text(json.dumps(data))
            with patch.object(batch,'validate_block') as validate:
                _,blocks=batch.attempt_record(attempt,config,baseline,identity)
            self.assertEqual(blocks,[]);validate.assert_not_called()

    def test_completed_attempt_rejects_changed_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            attempt=Path(tmp);config={'camera':{}};base={'config_sha256':'cfg','asset_sha256':{'a':'a'},'source_sha256':{},'graph_sha256':'graph','runtime_receipt_sha256':'runtime','adapted':False};identity={'scripts/falcor/reference_extension_runner.py':'runner','scripts/falcor/reference_runner.py':'dep1','scripts/falcor/adapted_reference_runner.py':'dep2'}
            m={'status':'completed','kind':'reference_extension','scene_config':config,'config_sha256':'cfg','samples_per_block':1024,'resolution':[1920,1080],'asset_sha256':{'a':'a'},'source_sha256':{},'graph_sha256':'graph','runtime_receipt_sha256':'runtime','runner_sha256':'runner','blocks':list(range(8)),'dependency_sha256':{k:v for k,v in identity.items() if k!='scripts/falcor/reference_extension_runner.py'},'artifacts':[{'block':0,'sha256':'old'}]}
            (attempt/'manifest.json').write_text(json.dumps(m))
            with patch.object(batch,'validate_block',return_value={'block':0,'sha256':'new'}):
                with self.assertRaisesRegex(ValueError,'artifact hash'):batch.attempt_record(attempt,config,base,identity)

    def test_output_allows_only_named_direct_child_of_old_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();old=root/'original';old.mkdir()
            batch.validate_output(old,old/'reference-16384-20261112')
            batch.validate_output(old,root/'independent-output')
            for target in [old,root,old/'classroom'/'view-a',old/'reference-16384-name'/'nested',old/'reference-16384-']:
                with self.subTest(target=target),self.assertRaises(ValueError): batch.validate_output(old,target)

    def test_recovered_block_requires_persisted_matching_artifact_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);d=root/'block-01';d.mkdir();(root/'scene-state.json').write_text('{}');(d/'camera.json').write_text('{}');im=d/'capture.AccumulatePass.output.1024.exr';im.write_bytes(b'exr')
            progress={'status':'submitted','block':0,'samples':1024,'seed_first':8192,'seed_last':9215,'exr_file':im.name,'exr_sha256':batch.sha(im),'camera_sha256':batch.sha(d/'camera.json'),'scene_state_sha256':batch.sha(root/'scene-state.json'),'scene_audit_sha256':None}
            (d/'progress.json').write_text(json.dumps(progress))
            with patch.object(batch.reference_runner,'validate_camera_records'),patch.object(batch.run,'inspect_hdr'):
                batch.validate_block(root,0,{'camera':{}},False)
                (d/'camera.json').write_text('{\"changed\":true}')
                with self.assertRaisesRegex(ValueError,'hash'):batch.validate_block(root,0,{'camera':{}},False)

    def test_full_six_view_batch_uses_one_attempt_each_and_preserves_old_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'original';old.mkdir();out=old/'reference-16384-test';configs=[];entries=[]
            keys=sorted(batch.EXPECTED)
            (old/'manifest.json').write_text(json.dumps({'views':[{'scene_id':a,'view_id':b} for a,b in keys]}))
            for a,b in keys:
                p=root/f'{a}-{b}.json';p.write_text(json.dumps({'scene_id':a,'view_id':b}));configs.append(p)
                entries.append({'scene_id':a,'view_id':b,'config_path':str(p),'config_sha256':batch.sha(p),
                                'old_reference':str(old/'reference.exr'),'old_seeds':[],
                                'adapted':(a,b)==('bistro','view-a')})
            baseline={'schema_version':1,'old_root':str(old),'views':entries}; identity={'code':'fixed'}
            def fake_launch(cfg,attempt,blocks,*args,**kwargs):
                self.assertEqual(blocks,list(range(8)));attempt.mkdir(parents=True);(attempt/'manifest.json').write_text('{}')
            def fake_find(view_dir,config,entry,identity):
                attempt=view_dir/'attempts'/'attempt-01'
                if not attempt.exists():return {}
                result={}
                for i in range(8):
                    a={'block':i,'file':f'block-{i}.exr','sha256':f'hash-{i}','camera_sha256':'camera','progress_sha256':'progress','scene_state_sha256':'state','scene_audit_sha256':None}
                    result[i]=(attempt,a,{'status':'completed'})
                return result
            def fake_mean(paths,dest):self.assertEqual(len(paths),16);dest.write_bytes(b'new-reference')
            with patch.object(batch,'ROOT',root),patch.object(batch,'verify_runtimes'),patch.object(batch.provenance,'verify_baseline',return_value=baseline), \
                 patch.object(batch,'code_identity',return_value=identity),patch.object(batch,'old_images',return_value=[root/f'old-{i}' for i in range(8)]), \
                 patch.object(batch,'find_blocks',side_effect=fake_find),patch.object(batch,'recheck_view'), \
                 patch.object(batch.extension,'launch',side_effect=fake_launch) as launch, \
                 patch.object(batch,'average_sixteen_seed_exrs',side_effect=fake_mean) as mean:
                batch._run_batch(old,configs,out)
            state=json.loads((out/'manifest.json').read_text());self.assertEqual(state['status'],'completed');self.assertEqual(launch.call_count,6);self.assertEqual(mean.call_count,6)
            self.assertEqual(len(state['views']),6);self.assertEqual(len(json.loads((old/'manifest.json').read_text())['views']),6)
