"""Fail-closed saved campaign validation, without a renderer process."""
import copy
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts/run")]
from experiment import comparison as comparison_api
from rtxdi_common import sha

from experiment.images import write_pfm
from experiment.reference import target as legacy_target

from tests.fixtures.legacy_artifacts import write_plane_geometry


def save(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


class SavedIndirectRuntimeTests(unittest.TestCase):
    """Saved target checks must survive removal of temporary capture buffers."""

    def setUp(self):
        import csv
        from experiment.artifacts import spatial_neighbor_stats
        from experiment.geometry_io import GEOMETRY_FORMAT
        from experiment.runner import relative_path
        from experiment.transport import expected_controls, method_config
        from tests.fixtures.cgns import cgns_runtime_record

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        base, resolved, timing = cgns_runtime_record(False)
        base.update(width=2, height=2, diagnostics=True, geometry_export=True)
        base['definition']['geometry_export'] = True
        base['frames'][0]['capture'] = True
        config = method_config(base, 'GI', False)
        self.job = {'config': config, 'algorithm':'GI', 'component':'full'}
        self.build, self.assets = {'fixture': 'transport-build'}, {'sha256': 'fixture-assets'}
        saved = dict(config, output='.', repository_root=relative_path(ROOT, self.directory))
        save(self.directory / 'config.json', saved)
        resolved.update(width=2, height=2, geometry_export=True, geometry_format=GEOMETRY_FORMAT,
                        textures=True, shadingParams={'enableFinalVisibility': 1},
                        source_format='RGBA16_FLOAT; export decoded losslessly to float32 PFM',
                        transport_controls=expected_controls(config))
        self.resolved = resolved
        save(self.directory / 'resolved.json', resolved)
        timing.update(capture=1, gi_neighbor_ms=0, pt_neighbor_ms=0,
                      gi_temporal_ms=1, gi_spatial_ms=1, gi_shading_ms=1,
                      pt_initial_ms=0, pt_temporal_ms=0, pt_spatial_ms=0)
        self.timing = timing
        with (self.directory / 'timings.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=timing)
            writer.writeheader()
            writer.writerow(timing)
        stem = self.directory / 'frame-0001'
        image = stem.with_suffix('.pfm.gz')
        write_pfm(image, np.ones((2, 2, 3), dtype=np.float32))
        capture = write_plane_geometry(stem, 2, 2, config['scene']['camera']['vertical_fov'])
        invalid = stem.with_suffix('.transport-invalid')
        invalid.write_bytes(bytes(4))
        neighbors = stem.with_suffix('.spatial-counts')
        np.array([128, 129, 130, 132], dtype='<u4').tofile(neighbors)
        capture.update(frame=1, image_sha256=sha(image), transport_invalid_contributions=0,
                       transport_invalid_sha256=sha(invalid),
                       **spatial_neighbor_stats(neighbors, 2, 2, 4))
        save(self.directory / 'manifest.json', {'status': 'completed', 'build': self.build,
             'scene': self.assets, 'config_sha256': sha(self.directory / 'config.json'), 'captures': [capture]})
        # Finalization retains the lossless geometry archive and removes these inputs.
        stem.with_suffix('.depth32f').unlink()
        stem.with_suffix('.normals32u').unlink()

    def load(self):
        return comparison_api.observed_run(self.directory, self.job, self.build, self.assets)

    def test_completed_run_reuses_archived_geometry_without_raw_buffers(self):
        item = self.load()
        self.assertEqual(item['record']['frame'], 1)
        self.assertEqual(item['target']['vertical_fov'], self.resolved['vertical_fov_degrees'])
        self.assertFalse((self.directory / 'frame-0001.depth32f').exists())
        self.assertFalse((self.directory / 'frame-0001.normals32u').exists())
        self.assertFalse((self.directory / 'frame-0001.rgba16f').exists())

    def test_saved_runtime_rejects_changed_target_and_direct_controls(self):
        mutations = [
            ('loaded_scene', 'Assets/Experiment/wrong.scene.json'),
            ('scene_id', 'different-scene'),
            ('vertical_fov_degrees', 12.0),
            ('environment_intensity_ev', 99.0),
            ('environment_rotation_degrees', 99.0),
            ('emissive_scale', 99.0),
            ('mode', 0),
            ('textures', False),
            ('shadingParams', {'enableFinalVisibility': 0}),
            ('initialSamplingParams', dict(self.resolved['initialSamplingParams'], numLocalLightSamples=0)),
            ('spatialResamplingParams', {'numSamples': 1}),
        ]
        for field, value in mutations:
            with self.subTest(field=field):
                save(self.directory / 'resolved.json', dict(self.resolved, **{field: value}))
                with self.assertRaises((RuntimeError, ValueError)):
                    self.load()
        save(self.directory / 'resolved.json', self.resolved)

    def test_texture_and_visibility_checks_follow_requested_arguments(self):
        from experiment.runner import relative_path
        config = self.job['config']
        config['arguments'].update({'postProcessing.textures': 0,
                                    'restirDI.shading.enableFinalVisibility': 0})
        save(self.directory / 'config.json', dict(config, output='.',
             repository_root=relative_path(ROOT, self.directory)))
        manifest = comparison_api.read_json(self.directory / 'manifest.json')
        manifest['config_sha256'] = sha(self.directory / 'config.json')
        save(self.directory / 'manifest.json', manifest)
        resolved = dict(self.resolved, textures=False, shadingParams={'enableFinalVisibility': 0})
        save(self.directory / 'resolved.json', resolved)
        self.assertEqual(self.load()['resolved']['shadingParams']['enableFinalVisibility'], 0)
        for field, actual in [('textures', True), ('shadingParams', {'enableFinalVisibility': 1})]:
            with self.subTest(field=field):
                save(self.directory / 'resolved.json', dict(resolved, **{field: actual}))
                with self.assertRaisesRegex(RuntimeError, 'textures|visibility'):
                    self.load()

    def test_saved_runtime_rejects_zero_total_gpu_time(self):
        import csv
        timing = dict(self.timing, gpu_ms=0)
        with (self.directory / 'timings.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=timing)
            writer.writeheader()
            writer.writerow(timing)
        with self.assertRaises((RuntimeError, ValueError)):
            self.load()


if __name__ == "__main__": unittest.main()
