"""Behavioral tests for migrated Falcor comparison catalog."""
import hashlib
import json
import shutil
from pathlib import Path
import tempfile
import unittest

import numpy as np
import OpenEXR


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    OpenEXR.File({}, {'RGB': np.full((2, 3, 3), value, dtype=np.float32)}).write(str(path))
    return {'path': relative, 'sha256': digest(path)}


def fixture(root):
    ref = image(root, 'classroom/view-a/reference/reference-16384.exr', 1.)
    comparisons = {}
    for mode in ('temporal-on', 'temporal-off'):
        methods = {}
        for method, value in (('spatial', 0.), ('cgns', .5)):
            frames = []
            for frame in range(41, 49):
                record = image(root, f'classroom/view-a/{mode}/{method}/frames/{frame}.exr', value)
                frames.append({'frame': frame, **record})
            metadata = root / f'classroom/view-a/{mode}/{method}/manifest.json'
            metadata.write_text(json.dumps({
                'status': 'completed', 'scene_id': 'classroom', 'view_id': 'view-a',
                'requested_method': 'baseline' if method == 'spatial' else 'cgns',
                'spp_per_frame': 1, 'capture_frames': list(range(41, 49)),
                'requested_graph_options': {'reSTIRPathTracingOptions':
                    {'useTemporalResampling': mode == 'temporal-on'}},
            }), encoding='utf8')
            methods[method] = {'frames': frames, 'manifest': str(metadata.relative_to(root)),
                               'manifest_sha256': digest(metadata)}
        comparisons[mode] = methods
    data = {'schema_version': 1, 'kind': 'falcor_pt_spatial_view_catalog',
            'views': [{'scene_id': 'classroom', 'view_id': 'view-a',
                       'reference': ref, 'comparisons': comparisons}]}
    p = root / 'manifest.json'
    p.write_text(json.dumps(data), encoding='utf8')
    return p, data


class ViewCatalogTests(unittest.TestCase):
    def test_analysis_uses_each_paired_frame_and_existing_smape(self):
        from scripts.analysis.falcor_view_catalog import analyze_catalog
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manifest, _ = fixture(root)
            for mode in ('temporal-on', 'temporal-off'):
                report = analyze_catalog(manifest, mode, root / ('report-' + mode))
                data = json.loads((report / 'summary.json').read_text(encoding='utf8'))
                v = data['views'][0]
                self.assertEqual([p['id'] for p in v['pairs']], list(range(41, 49)))
                self.assertEqual(data['settings']['temporal_reuse'], mode == 'temporal-on')
                self.assertAlmostEqual(v['baseline_smape_percent'], 100 / 1.0001, places=5)
                self.assertAlmostEqual(v['cgns_smape_percent'], 50 / 1.5001, places=5)
                self.assertEqual(v['pair_count'], 8)
                self.assertTrue((report/data['input_manifest']['path']).is_file())

    def test_input_and_summary_are_relative_and_work_after_relocation(self):
        from scripts.analysis.falcor_view_catalog import analyze_catalog
        from scripts.analysis import falcor_spatial_comparison, falcor_temporal_comparison
        with tempfile.TemporaryDirectory() as d:
            first=Path(d)/'first';first.mkdir();manifest,_=fixture(first)
            analysis=first/'analysis';analysis.mkdir()
            for mode in ('temporal-on','temporal-off'):
                report=analyze_catalog(manifest,mode,analysis/mode)
                input_path=analysis/(mode+'-input.json')
                data=json.loads(input_path.read_text(encoding='utf8'))
                v=data['views'][0]
                records=[v['reference'],data['settings']['source_catalog']]
                records.extend(p[k] for p in v['pairs'] for k in ('baseline','cgns'))
                for record in records:
                    self.assertFalse(Path(record['path']).is_absolute(),record['path'])
                    self.assertTrue((input_path.parent/record['path']).is_file(),record['path'])
                    self.assertEqual(digest(input_path.parent/record['path']),record['sha256'])
                summary=json.loads((report/'summary.json').read_text(encoding='utf8'))
                records=[summary['input_manifest'],summary['settings']['source_catalog'],summary['views'][0]['reference']]
                records.extend(p[k] for p in summary['views'][0]['pairs'] for k in ('baseline','cgns'))
                for record in records:
                    self.assertFalse(Path(record['path']).is_absolute(),record['path'])
                    self.assertTrue((report/record['path']).is_file(),record['path'])
                    self.assertEqual(digest(report/record['path']),record['sha256'])
            second=Path(d)/'second';shutil.copytree(first,second)
            first.rename(Path(d)/'original-unavailable')
            for mode,api in (('temporal-on',falcor_temporal_comparison),('temporal-off',falcor_spatial_comparison)):
                old=second/'analysis'/mode/'summary.json'
                expected=json.loads(old.read_text(encoding='utf8'))['views'][0]['relative_improvement_percent']
                new=api.analyze(second/'analysis'/(mode+'-input.json'),second/'analysis'/(mode+'-reanalysis'))
                summary=json.loads((new/'summary.json').read_text(encoding='utf8'))
                actual=summary['views'][0]['relative_improvement_percent']
                self.assertAlmostEqual(expected,actual,places=10)
                records=[summary['input_manifest'],summary['settings']['source_catalog'],summary['views'][0]['reference']]
                records.extend(p[k] for p in summary['views'][0]['pairs'] for k in ('baseline','cgns'))
                for record in records:
                    self.assertFalse(Path(record['path']).is_absolute(),record['path'])
                    self.assertEqual(digest(new/record['path']),record['sha256'])

    def test_rejects_a_validly_rehashed_but_mismatched_render_manifest(self):
        from scripts.analysis.falcor_view_catalog import build_analysis_input
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path, catalog = fixture(root)
            method = catalog['views'][0]['comparisons']['temporal-on']['spatial']
            metadata_path = root / method['manifest']
            metadata = json.loads(metadata_path.read_text(encoding='utf8'))
            metadata['requested_graph_options']['reSTIRPathTracingOptions']['useTemporalResampling'] = False
            metadata_path.write_text(json.dumps(metadata), encoding='utf8')
            method['manifest_sha256'] = digest(metadata_path)
            path.write_text(json.dumps(catalog), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'settings'):
                build_analysis_input(path, 'temporal-on')
    def test_rejects_unsafe_paths_mutated_files_and_missing_frames(self):
        from scripts.analysis.falcor_view_catalog import build_analysis_input
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path, catalog = fixture(root)
            f = catalog['views'][0]['comparisons']['temporal-on']['spatial']['frames'][0]
            original = f.copy()
            f['path'] = '../outside.exr'
            path.write_text(json.dumps(catalog), encoding='utf8')
            with self.assertRaises(ValueError):
                build_analysis_input(path, 'temporal-on')
            f.update(original)
            f['sha256'] = '0' * 64
            path.write_text(json.dumps(catalog), encoding='utf8')
            with self.assertRaises(ValueError):
                build_analysis_input(path, 'temporal-on')
            f.update(original)
            catalog['views'][0]['comparisons']['temporal-on']['cgns']['frames'].pop()
            path.write_text(json.dumps(catalog), encoding='utf8')
            with self.assertRaises(ValueError):
                build_analysis_input(path, 'temporal-on')


if __name__ == '__main__':
    unittest.main()
