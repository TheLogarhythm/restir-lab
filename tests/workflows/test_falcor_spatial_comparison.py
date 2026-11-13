"""Behavioral tests for paired Falcor comparison analysis."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import OpenEXR

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_rgb(path, value):
    a = np.full((2, 3, 3), value, dtype=np.float32)
    OpenEXR.File({}, {'RGB': a}).write(str(path))
    return {'path': str(path), 'sha256': digest(path)}


class FalcorComparisonTests(unittest.TestCase):
    def make_manifest(self, folder):
        reference = write_rgb(folder/'reference.exr', 1.0)
        baseline1 = write_rgb(folder/'b1.exr', 0.0)
        baseline2 = write_rgb(folder/'b2.exr', 2.0)
        cgns1 = write_rgb(folder/'c1.exr', 0.5)
        cgns2 = write_rgb(folder/'c2.exr', 1.5)
        return {'settings': {'temporal_reuse': False, 'spp_per_frame': 1},
                'views': [{'scene_id': 'classroom', 'view_id': 'view-a',
                           'reference': reference,
                           'pairs': [{'id': 41, 'baseline': baseline1, 'cgns': cgns1},
                                     {'id': 42, 'baseline': baseline2, 'cgns': cgns2}]}]}

    def invoke(self, root, manifest):
        from scripts.analysis.falcor_spatial_comparison import analyze
        input_path = root/'input.json'
        input_path.write_text(json.dumps(manifest), encoding='utf8')
        return analyze(input_path, root/'report')

    def test_per_frame_metrics_are_meaned_before_relative_comparison(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); manifest = self.make_manifest(root); report = self.invoke(root, manifest)
            data = json.loads((report/'summary.json').read_text(encoding='utf8'))
            self.assertEqual(data['settings']['spp_per_frame'], 1)
            self.assertFalse(data['settings']['temporal_reuse'])
            view = data['views'][0]
            expected_a = (100/(1+1e-4) + 100/(3+1e-4))/2
            expected_b = (50/(1.5+1e-4) + 50/(2.5+1e-4))/2
            self.assertAlmostEqual(view['baseline_smape_percent'], expected_a, places=5)
            self.assertAlmostEqual(view['cgns_smape_percent'], expected_b, places=5)
            self.assertAlmostEqual(view['improvement_percentage_points'], expected_a-expected_b, places=5)
            self.assertAlmostEqual(view['relative_improvement_percent'], 100*(expected_a-expected_b)/expected_a, places=5)
            self.assertEqual([p['id'] for p in view['pairs']], [41, 42])
            self.assertEqual(view['reference']['sha256'], manifest['views'][0]['reference']['sha256'])
            for file in ('summary.csv', 'index.html', 'view-001-reference.png', 'view-001-baseline.png', 'view-001-cgns.png'):
                self.assertTrue((report/file).is_file(), file)

    def test_rejects_modified_missing_nonfinite_or_mismatched_sources(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); m=self.make_manifest(root); m['views'][0]['pairs'][0]['cgns']['sha256']='0'*64
            with self.assertRaises(ValueError): self.invoke(root,m)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m=self.make_manifest(root);m['views'][0]['pairs'][0]['cgns']=write_rgb(root/'bad.exr',float('nan'))
            with self.assertRaises(ValueError):self.invoke(root,m)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m=self.make_manifest(root);p=root/'wrong.exr';OpenEXR.File({}, {'RGB':np.ones((1,1,3),dtype=np.float32)}).write(str(p));m['views'][0]['pairs'][0]['baseline']={'path':str(p),'sha256':digest(p)}
            with self.assertRaises(ValueError):self.invoke(root,m)

    def test_rejects_duplicate_pair_ids_and_incorrect_sampling_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m=self.make_manifest(root);m['views'][0]['pairs'][1]['id']=41
            with self.assertRaises(ValueError):self.invoke(root,m)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m=self.make_manifest(root);m['settings']['temporal_reuse']=True
            with self.assertRaises(ValueError):self.invoke(root,m)

    def test_identical_inputs_have_zero_error_and_undefined_relative_improvement(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m=self.make_manifest(root);ref=m['views'][0]['reference']
            m['views'][0]['pairs']=[{'id':41,'baseline':ref,'cgns':ref}]
            report=self.invoke(root,m); view=json.loads((report/'summary.json').read_text(encoding='utf8'))['views'][0]
            self.assertEqual(view['baseline_smape_percent'], 0)
            self.assertEqual(view['cgns_smape_percent'], 0)
            self.assertEqual(view['improvement_percentage_points'], 0)
            self.assertIsNone(view['relative_improvement_percent'])

    def test_never_overwrites_existing_results(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m=self.make_manifest(root);(root/'report').mkdir();(root/'report'/'keep.txt').write_text('keep')
            with self.assertRaises(FileExistsError):self.invoke(root,m)
            self.assertEqual((root/'report'/'keep.txt').read_text(),'keep')


    def test_worse_cgns_gives_negative_improvement_and_relative_paths_work(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m=self.make_manifest(root);v=m['views'][0]
            v['pairs']=[{'id':'frame-41','baseline':v['pairs'][0]['cgns'],'cgns':v['pairs'][0]['baseline']}]
            for record in (v['reference'], v['pairs'][0]['baseline'], v['pairs'][0]['cgns']):
                record['path']=Path(record['path']).name
            report=self.invoke(root,m);view=json.loads((report/'summary.json').read_text(encoding='utf8'))['views'][0]
            self.assertGreater(view['baseline_smape_percent'],0)
            self.assertLess(view['improvement_percentage_points'],0)
            self.assertLess(view['relative_improvement_percent'],0)

    def test_rejects_using_the_same_frame_for_multiple_pair_ids(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m=self.make_manifest(root)
            m['views'][0]['pairs'][1]['cgns']=m['views'][0]['pairs'][0]['cgns']
            with self.assertRaisesRegex(ValueError, 'Frame reused'):self.invoke(root,m)

    def test_temporal_contrast_reports_on_and_off_without_cgns_labels(self):
        from scripts.analysis.falcor_spatial_comparison import analyze_temporal_contrast
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manifest = self.make_manifest(root)
            manifest['settings'] = {'comparison_kind': 'baseline-temporal-on-off', 'spp_per_frame': 1}
            view = manifest['views'][0]
            for pair in view['pairs']:
                pair['temporal_off'] = pair.pop('baseline')
                pair['temporal_on'] = pair.pop('cgns')
            source = root / 'input.json'
            source.write_text(json.dumps(manifest), encoding='utf8')
            output = analyze_temporal_contrast(source, root / 'report')
            data = json.loads((output / 'summary.json').read_text(encoding='utf8'))
            result = data['views'][0]
            self.assertEqual(data['kind'], 'falcor_baseline_temporal_comparison')
            self.assertEqual((result['scene_id'], result['view_id']), ('classroom', 'view-a'))
            self.assertEqual([p['id'] for p in result['pairs']], [41, 42])
            self.assertGreater(result['improvement_percentage_points'], 0)
            self.assertAlmostEqual(result['improvement_percentage_points'],
                                   result['temporal_off_smape_percent'] - result['temporal_on_smape_percent'])
            self.assertAlmostEqual(result['relative_improvement_percent'],
                                   100 * result['improvement_percentage_points'] / result['temporal_off_smape_percent'])
            self.assertEqual(set(result['previews']), {'reference', 'temporal_on', 'temporal_off'})
            self.assertNotIn('CGNS', (output / 'index.html').read_text(encoding='utf8'))
            self.assertIn('temporal_on_smape_percent', (output / 'summary.csv').read_text())
            with self.assertRaises(FileExistsError):
                analyze_temporal_contrast(source, output)

    def test_shared_default_matches_temporal_on_and_explicit_legacy_wrappers(self):
        from scripts.analysis import falcor_comparison as shared
        from scripts.analysis import falcor_spatial_comparison, falcor_temporal_comparison
        for temporal, wrapper in ((True, falcor_temporal_comparison), (False, falcor_spatial_comparison)):
            with self.subTest(temporal=temporal), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                manifest = self.make_manifest(root)
                manifest['settings']['temporal_reuse'] = temporal
                source = root / 'input.json'
                source.write_text(json.dumps(manifest), encoding='utf8')
                options = {} if temporal else {'temporal_required': False}
                direct = shared.analyze(source, root / 'direct', **options)
                legacy = wrapper.analyze(source, root / 'legacy')
                self.assertEqual({p.name for p in direct.iterdir()}, {p.name for p in legacy.iterdir()})
                for path in direct.iterdir():
                    self.assertEqual(path.read_bytes(), (legacy / path.name).read_bytes(), path.name)
                data = json.loads((direct / 'summary.json').read_text(encoding='utf8'))
                self.assertIs(data['settings']['temporal_reuse'], temporal)
                self.assertEqual(data['kind'], 'falcor_temporal_spatial_comparison' if temporal else 'falcor_spatial_comparison')

    def test_temporal_wrapper_preserves_sampling_guard_and_report_identity(self):
        from scripts.analysis import falcor_temporal_comparison as analyzer
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manifest = self.make_manifest(root)
            manifest['settings']['temporal_reuse'] = True
            manifest['views'][0].update(
                scene_id='Falcor ReSTIR PT：spatial reuse 与 CGNS',
                view_id='每帧 1 spp，关闭 temporal reuse；',
            )
            source = root / 'input.json'
            source.write_text(json.dumps(manifest), encoding='utf8')
            output = analyzer.analyze(source, root / 'report')
            data = json.loads((output / 'summary.json').read_text(encoding='utf8'))
            self.assertEqual(data['kind'], 'falcor_temporal_spatial_comparison')
            self.assertTrue(data['settings']['temporal_reuse'])
            page = (output / 'index.html').read_text(encoding='utf8')
            self.assertIn('启用 temporal reuse', page)
            self.assertIn(
                '<h2>Falcor ReSTIR PT：spatial reuse 与 CGNS / 每帧 1 spp，关闭 temporal reuse；</h2>',
                page,
            )



if __name__ == '__main__': unittest.main()