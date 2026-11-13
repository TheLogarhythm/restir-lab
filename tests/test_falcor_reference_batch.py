import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.falcor import reference_batch


class ReferenceBatchTests(unittest.TestCase):
    def setUp(self):
        lockdir = tempfile.TemporaryDirectory()
        self.addCleanup(lockdir.cleanup)
        lock = patch.object(reference_batch, 'BATCH_LOCK', Path(lockdir.name) / 'batch.lock')
        lock.start()
        self.addCleanup(lock.stop)
        expected = {'asset_sha256': {'asset': 'abc'}, 'graph_sha256': 'graph',
                    'runner_sha256': 'runner', 'isolated_runtime_receipt_sha256': 'runtime'}
        patcher = patch.object(reference_batch, 'current_provenance', return_value=expected, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_retired_filtered_runtime_rejected_before_render(self):
        with self.assertRaisesRegex(ValueError, 'retired'):
            reference_batch.runtime_kind({'scene_id': 'bistro', 'reference_runtime': 'filtered',
                                          'runtime_receipt_sha256': 'f' * 64})

    def make_configs(self, root):
        result = []
        for scene, view in sorted(reference_batch.EXPECTED_VIEWS):
            path = root / f'{scene}-{view}.json'
            path.write_text(json.dumps({'scene_id': scene, 'view_id': view, 'ready_for_reference': True}))
            result.append(path)
        return result

    @staticmethod
    def fake_launch(config_path, output, seed, count, width, height, timeout):
        assert (count, width, height) == (1024, 1920, 1080)
        output.mkdir(parents=True)
        artifact = output / 'seed.exr'
        artifact.write_bytes(f'seed-{seed}'.encode())
        config = json.loads(config_path.read_text())
        manifest = {'status': 'completed', 'kind': 'reference_seed', 'seed_index': seed,
                    'samples_per_pixel': count, 'resolution': [width, height],
                    'sample_seed_first': seed * 1024, 'sample_seed_last': seed * 1024 + 1023,
                    'scene_config': config, 'config_sha256': reference_batch.sha(config_path),
                    'asset_sha256': {'asset': 'abc'}, 'graph_sha256': 'graph',
                    'runner_sha256': 'runner', 'isolated_runtime_receipt_sha256': 'runtime',
                    'artifacts': [{'file': artifact.name, 'sha256': reference_batch.sha(artifact)}]}
        path = output / 'manifest.json'
        path.write_text(json.dumps(manifest))
        return path

    def test_runs_all_seeds_sequentially_and_averages_per_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); configs = self.make_configs(root); out = root / 'batch'
            calls = []
            def fake_mean(paths, output):
                self.assertEqual(len(paths), 8)
                calls.append(paths)
                output.write_bytes(b'average')
                return output
            with patch.object(reference_batch.reference_runner, 'launch', side_effect=self.fake_launch), \
                 patch.object(reference_batch, 'average_seed_exrs', side_effect=fake_mean):
                reference_batch.run_batch(configs, out)
            data = json.loads((out / 'manifest.json').read_text())
            self.assertEqual(data['status'], 'completed')
            self.assertEqual(len(calls), 6)
            self.assertTrue(all(len(v['seeds']) == 8 for v in data['views']))

    def test_failure_stops_and_preserves_status_without_average(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); configs = self.make_configs(root); out = root / 'batch'
            def fail(config, output, seed, *args):
                if seed == 2: raise RuntimeError('deliberate failure')
                return self.fake_launch(config, output, seed, *args)
            with patch.object(reference_batch.reference_runner, 'launch', side_effect=fail) as launch, \
                 patch.object(reference_batch, 'average_seed_exrs') as average:
                with self.assertRaisesRegex(RuntimeError, 'deliberate failure'):
                    reference_batch.run_batch(configs, out)
            self.assertEqual(launch.call_count, 3)
            average.assert_not_called()
            self.assertEqual(json.loads((out/'manifest.json').read_text())['status'], 'failed')

    def test_rejects_unqualified_missing_duplicate_and_existing_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); configs = self.make_configs(root)
            with self.assertRaises(ValueError): reference_batch.run_batch([], root/'missing')
            with self.assertRaises(ValueError): reference_batch.run_batch(configs[:-1]+configs[:1], root/'duplicate')
            obj = json.loads(configs[0].read_text()); obj['ready_for_reference'] = False
            configs[0].write_text(json.dumps(obj))
            with self.assertRaises(ValueError): reference_batch.run_batch(configs, root/'unqualified')
            obj['ready_for_reference'] = True; configs[0].write_text(json.dumps(obj))
            (root/'existing').mkdir()
            with self.assertRaises(FileExistsError): reference_batch.run_batch(configs, root/'existing')

    def test_rejects_changed_provenance_before_average(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); configs = self.make_configs(root); out = root/'batch'
            def altered(config, output, seed, *args):
                path = self.fake_launch(config, output, seed, *args)
                if seed == 3:
                    d = json.loads(path.read_text()); d['asset_sha256']['asset'] = 'changed'; path.write_text(json.dumps(d))
                return path
            with patch.object(reference_batch.reference_runner, 'launch', side_effect=altered), \
                 patch.object(reference_batch, 'average_seed_exrs') as average:
                with self.assertRaisesRegex(ValueError, 'provenance'):
                    reference_batch.run_batch(configs, out)
                average.assert_not_called()

    def test_rejects_incorrect_random_sample_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); configs = self.make_configs(root); out = root/'batch'
            def altered(config, output, seed, *args):
                path = self.fake_launch(config, output, seed, *args)
                if seed == 1:
                    d = json.loads(path.read_text()); d['sample_seed_first'] = 0; path.write_text(json.dumps(d))
                return path
            with patch.object(reference_batch.reference_runner, 'launch', side_effect=altered), \
                 patch.object(reference_batch, 'average_seed_exrs', side_effect=lambda paths, out: out.write_bytes(b'average')) as average:
                with self.assertRaisesRegex(ValueError, 'formal configuration'):
                    reference_batch.run_batch(configs, out)
                average.assert_not_called()

    def test_resume_reuses_valid_seeds_and_preserves_failed_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); configs = self.make_configs(root); out = root/'batch'
            def interrupted(config, output, seed, *args):
                if seed == 2:
                    output.mkdir(parents=True)
                    (output/'manifest.json').write_text('{"status":"failed"}')
                    raise RuntimeError('interrupted')
                return self.fake_launch(config, output, seed, *args)
            expected = {'asset_sha256': {'asset': 'abc'}, 'graph_sha256':'graph',
                        'runner_sha256':'runner', 'isolated_runtime_receipt_sha256':'runtime'}
            with patch.object(reference_batch, 'current_provenance', return_value=expected), \
                 patch.object(reference_batch.reference_runner, 'launch', side_effect=interrupted):
                with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                    reference_batch.run_batch(configs, out)
            with patch.object(reference_batch, 'current_provenance', return_value=expected), \
                 patch.object(reference_batch.reference_runner, 'launch', side_effect=self.fake_launch) as launch, \
                 patch.object(reference_batch, 'average_seed_exrs', side_effect=lambda paths, dest: dest.write_bytes(b'average')):
                reference_batch.run_batch(configs, out, resume=True)
            self.assertEqual(launch.call_count, 46)
            failed = out/'bistro'/'view-a'/'seeds'/'seed-03'/'attempt-01'/'manifest.json'
            self.assertTrue(failed.is_file())
            self.assertEqual(json.loads(failed.read_text())['status'], 'failed')
            self.assertEqual(json.loads((out/'manifest.json').read_text())['status'], 'completed')

    def test_relocated_partial_batch_resumes_with_relative_configuration_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / 'first'; first.mkdir()
            configs = self.make_configs(first); out = first / 'batch'
            def interrupted(config, output, seed, *args):
                if seed == 2:
                    raise RuntimeError('interrupted')
                return self.fake_launch(config, output, seed, *args)
            with patch.object(reference_batch.reference_runner, 'launch', side_effect=interrupted):
                with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                    reference_batch.run_batch(configs, out)
            status = json.loads((out/'manifest.json').read_text())
            self.assertEqual(status['schema_version'], 2)
            self.assertEqual(status['path_base'], 'batch_directory')
            for record in status['configurations']:
                self.assertFalse(Path(record['path']).is_absolute())
                self.assertEqual(reference_batch.sha(out/record['path']), record['sha256'])
            for view in status['views']:
                self.assertFalse(Path(view['config']).is_absolute())
                self.assertEqual(reference_batch.sha(out/view['config']), view['config_sha256'])
            second = Path(tmp) / 'second'; shutil.copytree(first, second)
            first.rename(Path(tmp)/'unavailable')
            copied = [second / p.name for p in configs]
            with patch.object(reference_batch.reference_runner, 'launch', side_effect=self.fake_launch) as launch, \
                 patch.object(reference_batch, 'average_seed_exrs', side_effect=lambda paths, dest: dest.write_bytes(b'average')):
                reference_batch.run_batch(copied, second/'batch', resume=True)
            self.assertEqual(launch.call_count, 46)

    def test_legacy_absolute_batch_status_can_resume_without_rewriting_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); configs=self.make_configs(root);out=root/'batch'
            def interrupted(config,output,seed,*args):
                if seed == 1: raise RuntimeError('interrupted')
                return self.fake_launch(config,output,seed,*args)
            with patch.object(reference_batch.reference_runner,'launch',side_effect=interrupted):
                with self.assertRaises(RuntimeError):reference_batch.run_batch(configs,out)
            status_path=out/'manifest.json';data=json.loads(status_path.read_text())
            data['schema_version']=1;data.pop('path_base')
            for record in data['configurations']:record['path']=str((out/record['path']).resolve())
            for view in data['views']:view['config']=str((out/view['config']).resolve())
            status_path.write_text(json.dumps(data))
            with patch.object(reference_batch.reference_runner,'launch',side_effect=self.fake_launch), \
                 patch.object(reference_batch,'average_seed_exrs',side_effect=lambda paths,dest:dest.write_bytes(b'average')):
                reference_batch.run_batch(configs,out,resume=True)
            final=json.loads(status_path.read_text())
            self.assertEqual(final['schema_version'],1)
            self.assertTrue(all(Path(x['path']).is_absolute() for x in final['configurations']))

    def test_resume_rejects_changed_current_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); configs = self.make_configs(root); out = root/'batch'
            expected = {'asset_sha256': {'asset': 'abc'}, 'graph_sha256':'graph',
                        'runner_sha256':'runner', 'isolated_runtime_receipt_sha256':'runtime'}
            def interrupted(config, output, seed, *args):
                if seed == 1: raise RuntimeError('interrupted')
                return self.fake_launch(config, output, seed, *args)
            with patch.object(reference_batch, 'current_provenance', return_value=expected), \
                 patch.object(reference_batch.reference_runner, 'launch', side_effect=interrupted):
                with self.assertRaises(RuntimeError): reference_batch.run_batch(configs, out)
            changed = dict(expected, asset_sha256={'asset': 'different'})
            with patch.object(reference_batch, 'current_provenance', return_value=changed), \
                 patch.object(reference_batch.reference_runner, 'launch') as launch:
                with self.assertRaisesRegex(ValueError, 'provenance'):
                    reference_batch.run_batch(configs, out, resume=True)
                launch.assert_not_called()

    def test_resume_rejects_modified_completed_seed_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); configs = self.make_configs(root); out = root/'batch'
            def interrupted(config, output, seed, *args):
                if seed == 2: raise RuntimeError('interrupted')
                return self.fake_launch(config, output, seed, *args)
            with patch.object(reference_batch.reference_runner, 'launch', side_effect=interrupted):
                with self.assertRaises(RuntimeError): reference_batch.run_batch(configs, out)
            image = out/'bistro'/'view-a'/'seeds'/'seed-02'/'attempt-01'/'seed.exr'
            image.write_bytes(b'tampered')
            with patch.object(reference_batch.reference_runner, 'launch') as launch:
                with self.assertRaisesRegex(ValueError, 'provenance'):
                    reference_batch.run_batch(configs, out, resume=True)
                launch.assert_not_called()

    def test_resume_revalidates_completed_view_without_rerender(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); configs = self.make_configs(root); out = root/'batch'
            def interrupted(config, output, seed, *args):
                data = json.loads(config.read_text())
                if data['scene_id'] == 'bistro' and data['view_id'] == 'view-b':
                    raise RuntimeError('interrupted next view')
                return self.fake_launch(config, output, seed, *args)
            with patch.object(reference_batch.reference_runner, 'launch', side_effect=interrupted), \
                 patch.object(reference_batch, 'average_seed_exrs', side_effect=lambda paths, dest: dest.write_bytes(b'average')):
                with self.assertRaises(RuntimeError): reference_batch.run_batch(configs, out)
            before = (out/'bistro'/'view-a'/'reference.exr').read_bytes()
            with patch.object(reference_batch.reference_runner, 'launch', side_effect=self.fake_launch) as launch, \
                 patch.object(reference_batch, 'average_seed_exrs', side_effect=lambda paths, dest: dest.write_bytes(b'average')) as average:
                reference_batch.run_batch(configs, out, resume=True)
            self.assertEqual(launch.call_count, 40)
            self.assertEqual(average.call_count, 5)
            self.assertEqual((out/'bistro'/'view-a'/'reference.exr').read_bytes(), before)

    def test_rejects_overlapping_batch_before_creating_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); configs = self.make_configs(root); out = root/'batch'
            with reference_batch.reference_runner.exclusive_operation(reference_batch.BATCH_LOCK):
                with self.assertRaisesRegex(RuntimeError, 'active'):
                    reference_batch.run_batch(configs, out)
            self.assertFalse(out.exists())

    def test_staged_batch_keeps_partial_until_all_six_views_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); configs=self.make_configs(root); out=root/'batch'
            def average(paths,dest): dest.write_bytes(b'average')
            with patch.object(reference_batch.reference_runner,'launch',side_effect=self.fake_launch) as launch, \
                 patch.object(reference_batch,'average_seed_exrs',side_effect=average) as mean:
                reference_batch.run_batch(configs[:4],out)
                self.assertEqual(json.loads((out/'manifest.json').read_text())['status'],'partial')
                self.assertEqual(launch.call_count,32)
                self.assertEqual(mean.call_count,4)
                reference_batch.run_batch(configs[4:],out,resume=True)
                self.assertEqual(launch.call_count,48)
                self.assertEqual(mean.call_count,6)
            result=json.loads((out/'manifest.json').read_text())
            self.assertEqual(result['status'],'completed')
            self.assertEqual(len(result['configurations']),6)
            self.assertEqual(len(result['views']),6)

    def test_staged_resume_refuses_changed_prior_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); configs=self.make_configs(root); out=root/'batch'
            with patch.object(reference_batch.reference_runner,'launch',side_effect=self.fake_launch), \
                 patch.object(reference_batch,'average_seed_exrs',side_effect=lambda paths,dest: dest.write_bytes(b'average')):
                reference_batch.run_batch(configs[:4],out)
            d=json.loads(configs[0].read_text());d['modified']=True;configs[0].write_text(json.dumps(d))
            with patch.object(reference_batch.reference_runner,'launch') as launch:
                with self.assertRaisesRegex(ValueError,'provenance'):
                    reference_batch.run_batch(configs[4:],out,resume=True)
                launch.assert_not_called()
