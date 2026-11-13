import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.falcor import adapted_reference_batch as batch

PROVENANCE={'asset_sha256':{'asset':'asset-hash'}, 'source_sha256':{'src':'source-hash'},
            'graph_sha256':'graph','runner_sha256':'runner','runtime_receipt_sha256':'receipt',
            'runtime_kind':'factor','build_commit':'commit','gpu_driver':'GPU, driver'}

class AdaptedBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.out=self.root/'out'
        self.config=self.root/'config.json'
        self.config.write_text(json.dumps({'scene_id':'bistro','view_id':'view-a','ready_for_reference':True}))
        patches=[patch.object(batch,'BATCH_LOCK',self.root/'lock'),
                 patch.object(batch,'current_provenance',return_value=PROVENANCE),
                 patch.object(batch,'_pipeline_hashes',return_value={'pipeline':'hash'})]
        for p in patches:p.start();self.addCleanup(p.stop)
    def launch(self,config,output,seed,count,width,height,timeout):
        self.assertEqual((count,width,height),(1024,1920,1080))
        output.mkdir(parents=True)
        image=output/'output.exr';image.write_bytes(('seed'+str(seed)).encode())
        audit=output/'scene-audit.json';audit.write_text('{\"nodes\":3}')
        d={'status':'completed','kind':'reference_seed','seed_index':seed,'samples_per_pixel':count,
           'sample_seed_first':seed*1024,'sample_seed_last':seed*1024+1023,'resolution':[width,height],
           'scene_config':json.loads(config.read_text()),'config_sha256':batch.runner.file_sha256(config),
           'artifacts':[{'file':image.name,'sha256':batch.runner.file_sha256(image)},
                        {'file':audit.name,'sha256':batch.runner.file_sha256(audit)}],**PROVENANCE}
        p=output/'manifest.json';p.write_text(json.dumps(d));return p
    def mean(self,images,dest):
        self.assertEqual(len(images),8);self.assertFalse(dest.exists());dest.write_bytes(b'average')
    def interrupted(self,config,output,seed,*args):
        if seed==2:
            output.mkdir(parents=True);(output/'manifest.json').write_text('{"status":"failed"}')
            raise RuntimeError('interrupted')
        return self.launch(config,output,seed,*args)
    def fail_at_two(self):
        with patch.object(batch.runner,'launch',side_effect=self.interrupted):
            with self.assertRaisesRegex(RuntimeError,'interrupted'):
                batch.run_batch([self.config],self.out)
    def test_complete_calls_8_independent_seeds_and_average(self):
        with patch.object(batch.runner,'launch',side_effect=self.launch) as launch, patch.object(batch,'average_seed_exrs',side_effect=self.mean) as mean:
            batch.run_batch([self.config],self.out)
        self.assertEqual(launch.call_count,8);mean.assert_called_once()
        status=json.loads((self.out/'manifest.json').read_text())
        self.assertEqual(status['status'],'completed');self.assertEqual(len(status['views'][0]['seeds']),8)
        self.assertEqual((self.out/'bistro/view-a/reference.exr').read_bytes(),b'average')
        with self.assertRaises(ValueError):batch.run_batch([self.config],self.out,resume=True)
    def test_resume_preserves_attempts_and_reuses_completed(self):
        self.fail_at_two()
        with patch.object(batch.runner,'launch',side_effect=self.launch) as launch, patch.object(batch,'average_seed_exrs',side_effect=self.mean):
            batch.run_batch([self.config],self.out,resume=True)
        self.assertEqual(launch.call_count,6)
        self.assertTrue((self.out/'bistro/view-a/seeds/seed-03/attempt-01/manifest.json').is_file())
        self.assertTrue((self.out/'bistro/view-a/seeds/seed-03/attempt-02/manifest.json').is_file())
    def test_rejects_changed_seed_before_launch(self):
        self.fail_at_two();(self.out/'bistro/view-a/seeds/seed-02/attempt-01/output.exr').write_bytes(b'tamper')
        with patch.object(batch.runner,'launch') as launch:
            with self.assertRaisesRegex(ValueError,'hash mismatch'):batch.run_batch([self.config],self.out,resume=True)
            launch.assert_not_called()
    def test_rejects_config_runtime_and_source_changes(self):
        self.fail_at_two()
        for field,value in [('asset_sha256',{'asset':'other'}),('source_sha256',{'src':'other'}),('runtime_receipt_sha256','other')]:
            with self.subTest(field=field),patch.object(batch,'current_provenance',return_value=dict(PROVENANCE,**{field:value})),patch.object(batch.runner,'launch') as launch:
                with self.assertRaisesRegex(ValueError,'provenance'):batch.run_batch([self.config],self.out,resume=True)
                launch.assert_not_called()
        self.config.write_text(self.config.read_text()+' ')
        with self.assertRaisesRegex(ValueError,'configuration'):batch.run_batch([self.config],self.out,resume=True)
    def test_never_overwrites_existing_reference_after_interruption(self):
        self.fail_at_two();dest=self.out/'bistro/view-a/reference.exr';dest.write_bytes(b'orphan')
        with patch.object(batch.runner,'launch',side_effect=self.launch),patch.object(batch,'average_seed_exrs',side_effect=self.mean):
            batch.run_batch([self.config],self.out,resume=True)
        self.assertEqual(dest.read_bytes(),b'orphan')
        self.assertEqual((dest.parent/'reference-attempt-02.exr').read_bytes(),b'average')
    def test_manifest_sample_range_rejected(self):
        def malformed(*args):
            p=self.launch(*args);d=json.loads(p.read_text());d['sample_seed_first']=0;p.write_text(json.dumps(d));return p
        with patch.object(batch.runner,'launch',side_effect=malformed),patch.object(batch,'average_seed_exrs') as avg:
            with self.assertRaisesRegex(ValueError,'formal configuration'):batch.run_batch([self.config],self.out)
            avg.assert_not_called()
    def test_existing_output_directory_is_never_overwritten(self):
        self.out.mkdir();marker=self.out/'data';marker.write_text('old')
        with self.assertRaises(FileExistsError):batch.run_batch([self.config],self.out)
        self.assertEqual(marker.read_text(),'old')

    def test_resume_rejects_changed_audit_and_manifest(self):
        self.fail_at_two()
        attempt=self.out/'bistro/view-a/seeds/seed-01/attempt-01'
        audit=attempt/'scene-audit.json';original=audit.read_bytes();audit.write_text('changed')
        with patch.object(batch.runner,'launch') as launch:
            with self.assertRaisesRegex(ValueError,'hash mismatch'):batch.run_batch([self.config],self.out,resume=True)
            launch.assert_not_called()
        audit.write_bytes(original)
        manifest=attempt/'manifest.json';manifest.write_text(manifest.read_text()+' ')
        with patch.object(batch.runner,'launch') as launch:
            with self.assertRaisesRegex(ValueError,'provenance mismatch'):batch.run_batch([self.config],self.out,resume=True)
            launch.assert_not_called()
    def test_rechecks_seed_after_average_before_recording_success(self):
        def changed(images,dest):
            dest.write_bytes(b'average');images[0].write_bytes(b'changed during mean')
        with patch.object(batch.runner,'launch',side_effect=self.launch),patch.object(batch,'average_seed_exrs',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'hash mismatch'):
                batch.run_batch([self.config],self.out)
        self.assertEqual(json.loads((self.out/'manifest.json').read_text())['status'],'failed')
        self.assertEqual((self.out/'bistro/view-a/reference.exr').read_bytes(),b'average')
    def test_other_completed_views_revalidated_before_new_work(self):
        other=self.root/'other.json'
        other.write_text(json.dumps({'scene_id':'classroom','view_id':'view-a','ready_for_reference':True}))
        def fail_next(config,output,seed,*args):
            if config==other:raise RuntimeError('next view interrupted')
            return self.launch(config,output,seed,*args)
        with patch.object(batch.runner,'launch',side_effect=fail_next),patch.object(batch,'average_seed_exrs',side_effect=self.mean):
            with self.assertRaisesRegex(RuntimeError,'interrupted'):
                batch.run_batch([self.config,other],self.out)
        dest=self.out/'bistro/view-a/reference.exr';dest.write_bytes(b'changed')
        with patch.object(batch.runner,'launch') as launch:
            with self.assertRaisesRegex(ValueError,'Reference output provenance'):
                batch.run_batch([self.config,other],self.out,resume=True)
            launch.assert_not_called()
if __name__=='__main__':unittest.main()
