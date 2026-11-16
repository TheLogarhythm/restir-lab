"""PDF reuse uses the ordinary capture/campaign path without changing defaults."""

import ast
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.falcor import spatial_capture as capture
from scripts.falcor import spatial_campaign as campaign
from scripts.falcor import spatial_experiment_config as settings


class PdfConfigTests(unittest.TestCase):
    def test_pdf_parameters_are_strict_and_baseline_graph_is_unchanged(self):
        value = settings.load_config()
        self.assertEqual(value['methods']['pdf-similarity'], {
            'kind': 'pdf-similarity', 'shader': {'history_limit': 20, 'history_decay': 0.95}})
        self.assertEqual(settings.graph_options(value, 'temporal-on', 'pdf-similarity'),
                         settings.graph_options(value, 'temporal-on', 'baseline'))
        for key, invalid in [('history_limit', 0), ('history_limit', True),
                             ('history_limit', 101), ('history_decay', -0.01),
                             ('history_decay', float('nan')), ('history_decay', 1.1)]:
            with self.subTest(key=key, invalid=invalid):
                changed = deepcopy(value)
                changed['methods']['pdf-similarity']['shader'][key] = invalid
                with self.assertRaises(ValueError):
                    settings.validate_config(changed)
        no_history = deepcopy(value)
        no_history['methods']['pdf-similarity']['shader']['history_decay'] = 0
        self.assertEqual(settings.validate_config(no_history)['methods']['pdf-similarity']['shader']
                         ['history_decay'], 0)
        historical = deepcopy(value)
        del historical['methods']['pdf-similarity']
        self.assertEqual(settings.validate_config(historical), historical)
        with self.assertRaises(ValueError):
            settings.graph_options(historical, 'temporal-on', 'pdf-similarity')


class PdfCaptureTests(unittest.TestCase):
    def test_launch_records_profile_seed_and_aov_capture_without_a_renderer(self):
        camera = dict(position=[0, 0, 0], direction=[0, 0, 1], up=[0, 1, 0], vertical_fov=45)
        with tempfile.TemporaryDirectory(dir=capture.ROOT / 'tmp') as directory:
            root = Path(directory)
            view = root / 'view.json'
            view.write_text('{}')
            scene = root / 'scene.pyscene'
            scene.write_text('# fixture')
            runtime = root / 'runtime'
            shader = runtime / 'shaders/ReSTIRPathTracing/SpatialResampling.cs.slang'
            shader.parent.mkdir(parents=True)
            shader.write_text('// fixture')
            (runtime / 'Mogwai.exe').write_bytes(b'fixture')
            config = {'scene_id': 'classroom', 'view_id': 'view-a', 'camera': camera,
                      'scene_source': scene.relative_to(capture.ROOT).as_posix()}
            entry = {'adapted': False, 'config_path': str(view),
                     'config_sha256': capture.run.sha(view), 'asset_sha256': {}, 'source_sha256': {}}

            verify_empty_outputs = False
            def execute(command, output, timeout, *, prepare, verify, metadata):
                output.mkdir()
                prepare(output)
                if verify_empty_outputs:
                    with patch.object(capture, '_verify_captures', return_value=[]):
                        verify(output)
                return metadata

            with (
                patch.object(capture.views, 'load_config', return_value=config),
                patch.object(capture.views, 'frozen_views', return_value={('classroom', 'view-a'): entry}),
                patch.object(capture.views, 'validate_reference_for_view'),
                patch.object(capture.reference_runner, 'validate_scene_qualification'),
                patch.object(capture.process_utils, 'exclusive_operation', return_value=nullcontext()),
                patch.object(capture.process_utils, 'check_renderer_idle'),
                patch.object(capture.build, 'verify_build', return_value={'commit': 'fixture'}),
                patch.object(capture.reference_extension_batch, 'recheck_view'),
                patch.object(capture, 'validate_runtime', return_value={'source_kind': 'reference'}) as runtime_check,
                patch.object(capture.subprocess, 'check_output', return_value='fixture GPU'),
                patch.object(capture.run, 'execute', side_effect=execute),
            ):
                from scripts.falcor import fixed_view_suite
                experiment = root / 'quality.json'
                experiment.write_text(json.dumps(fixed_view_suite.plan()['experiments']['quality']))
                formal = capture.launch(view, root / 'formal', runtime, method='pdf-similarity',
                                        experiment_path=experiment, seed_offset=100000)
                self.assertEqual(formal['seed_offset'], 100000)
                self.assertEqual(formal['capture_frames'], list(range(41, 57)))
                self.assertTrue(formal['temporal_reuse'])
                self.assertEqual(formal['pdf_profile'], 'normal')
                from types import SimpleNamespace
                formal_source = (root / 'formal/render.py').read_text(encoding='utf8')
                assignment = next(node for node in ast.walk(ast.parse(formal_source))
                                  if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Attribute)
                                  and node.targets[0].attr == 'fixedSeed')
                tracer = SimpleNamespace()
                values = []
                for frame in (1, 41, 56):
                    exec(compile(ast.Module(body=[assignment], type_ignores=[]), '<seed>', 'exec'),
                         {'tracer': tracer, 'frame': frame})
                    values.append(tracer.fixedSeed)
                self.assertEqual(values, [100000, 100040, 100055])
                metadata = capture.launch(view, root / 'output', runtime, method='pdf-similarity',
                                          width=32, height=18, warmup=0, count=2, scout=True,
                                          temporal_reuse=False, seed_offset=100, pdf_profile='observe')
                verify_empty_outputs = True
                with self.assertRaisesRegex(ValueError, 'PDF diagnostic frames'):
                    capture.launch(view, root / 'missing-aovs', runtime, method='pdf-similarity',
                                   width=32, height=18, warmup=0, count=2, scout=True,
                                   temporal_reuse=False, pdf_profile='observe')
            self.assertEqual(metadata['requested_method'], 'pdf-similarity')
            self.assertEqual(metadata['pdf_profile'], 'observe')
            self.assertEqual(metadata['pdf_shader_parameters'], {'history_limit': 20, 'history_decay': 0.95})
            self.assertEqual(metadata['seed_offset'], 100)
            self.assertEqual(metadata['capture_frames'], [1, 2])
            self.assertEqual(runtime_check.call_args.kwargs, {'pdf_profile': 'observe'})
            source = (root / 'output/render.py').read_text(encoding='utf8')
            self.assertIn('tracer.fixedSeed = 100 + frame - 1', source)
            self.assertIn("g.markOutput('PathTracer.nrdResidualRadianceHitDist', TextureChannelFlags.RGBA)", source)
            self.assertEqual(metadata['render_script_sha256'], capture.run.sha(root / 'output/render.py'))

    def test_color_verification_preserves_separate_diagnostic_exrs(self):
        import numpy as np
        import OpenEXR
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for filename in ('resolved-camera.json', 'scene-state.json'):
                (output / filename).write_text('{}')
            (output / 'resolved.py').write_text('# fixture')
            for frame in (1, 2):
                for name in ('color', 'nrdEmission', 'nrdDiffuseRadianceHitDist'):
                    image = np.full((2, 3, 3), frame, dtype=np.float32)
                    OpenEXR.File({}, {'RGB': image}).write(str(output / f'capture.PathTracer.{name}.{frame}.exr'))
            before = {path: path.read_bytes() for path in output.glob('*.exr')}
            with (
                patch.object(capture.reference_runner, 'validate_camera_records'),
                patch.object(capture.cgns_pt_smoke, 'validate_resolved_graph'),
                patch.object(capture.views, 'validate_current_scene_state'),
            ):
                records = capture._verify_captures(output, {'camera': {}}, {}, [1, 2], 3, 2,
                                                   True, False, seed_offset=100)
            self.assertEqual([record['seed'] for record in records], [100, 101])
            self.assertEqual([record['reuse_seed'] for record in records], [0, 100])
            self.assertTrue(all('.color.' in record['hdr'] for record in records))
            self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_pdf_scout_profiles_mark_only_their_diagnostic_outputs(self):
        camera = dict(position=[0, 0, 0], direction=[0, 0, 1], up=[0, 1, 0], vertical_fov=45)
        outputs = ('nrdEmission', 'nrdDiffuseRadianceHitDist',
                   'nrdSpecularRadianceHitDist', 'nrdResidualRadianceHitDist')
        for profile in ('normal', 'observe', 'one', 'zero', 'center', 'native'):
            with self.subTest(profile=profile):
                source = capture.render_script(Path('scene'), camera, Path('out'), 0, 2,
                                               'pdf-similarity', adapted=False, pdf_profile=profile)
                ast.parse(source)
                self.assertIn("g.markOutput('PathTracer.color')", source)
                self.assertIn('m.frameCapture.captureAllOutputs = False', source)
                expected = () if profile == 'normal' else outputs[:2] if profile == 'native' else outputs
                for output in outputs:
                    marker = "g.markOutput('PathTracer." + output + "', TextureChannelFlags.RGBA)"
                    self.assertEqual(marker in source, output in expected)

    def test_diagnostic_verification_requires_exact_frames_and_finite_float32_rgba(self):
        import numpy as np
        import OpenEXR
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def write(name, frame, *, alpha=True, dtype=np.float32, value=1):
                channels = {channel: np.full((2, 3), value, dtype=dtype)
                            for channel in ('RGBA' if alpha else 'RGB')}
                path = root / f'capture.PathTracer.{name}.{frame}.exr'
                OpenEXR.File({}, channels).write(str(path))
                return path
            for frame in (1, 2):
                for output in capture.PDF_DIAGNOSTIC_OUTPUTS:
                    write(output.split('.')[-1], frame)
            before = {path: path.read_bytes() for path in root.glob('*.exr')}
            records = capture.verify_pdf_diagnostics(root, [1, 2], 3, 2, 'observe')
            self.assertEqual(len(records), 8)
            self.assertEqual({path: path.read_bytes() for path in before}, before)
            for options in ({'alpha': False}, {'dtype': np.float16}, {'value': float('nan')}):
                with self.subTest(options=options):
                    write('nrdEmission', 1, **options)
                    with self.assertRaises(ValueError):
                        capture.verify_pdf_diagnostics(root, [1, 2], 3, 2, 'observe')
            write('nrdEmission', 1)
            extra = write('nrdEmission', 3)
            with self.assertRaises(ValueError):
                capture.verify_pdf_diagnostics(root, [1, 2], 3, 2, 'observe')
            extra.unlink()
            (root / 'capture.PathTracer.nrdEmission.2.exr').unlink()
            with self.assertRaises(ValueError):
                capture.verify_pdf_diagnostics(root, [1, 2], 3, 2, 'observe')
            self.assertEqual(capture.verify_pdf_diagnostics(root, [1, 2], 3, 2, 'normal'), [])

    def test_pdf_dependency_snapshot_includes_shader_sources_without_expanding_baseline(self):
        from scripts.falcor import pdf_pt_shader
        baseline = set(capture.dependency_files())
        pdf = set(capture.dependency_files('pdf-similarity'))
        self.assertTrue(baseline.issubset(pdf))
        self.assertTrue(set(pdf_pt_shader.source_files()).issubset(pdf))
        self.assertTrue(set(pdf_pt_shader.source_files()).difference(baseline))
        self.assertEqual(campaign._dependency_names('pdf-similarity'),
                         {path.relative_to(campaign.ROOT).as_posix() for path in pdf})

    def test_capture_kind_distinguishes_pdf_from_historical_cgns(self):
        self.assertEqual(capture.capture_kind('baseline', True), 'cgns_pt_temporal_single_frame')
        self.assertEqual(capture.capture_kind('pdf-similarity', True),
                         'pdf_similarity_pt_temporal_single_frame')
        self.assertEqual(capture.capture_kind('pdf-similarity', False),
                         'pdf_similarity_pt_paper_setting_single_frame')

    def test_scout_seed_offset_is_used_by_real_script_and_artifact_records(self):
        camera = dict(position=[0, 0, 0], direction=[0, 0, 1], up=[0, 1, 0], vertical_fov=45)
        script = capture.render_script(Path('scene'), camera, Path('out'), 2, 2,
                                       'pdf-similarity', adapted=False, seed_offset=100)
        ast.parse(script)
        self.assertIn('tracer.fixedSeed = 100 + frame - 1', script)
        self.assertEqual(capture.seed_record(3, seed_offset=100),
                         {'frame': 3, 'seed': 102, 'reuse_seed': 101})
        self.assertEqual(capture.seed_record(1, seed_offset=100),
                         {'frame': 1, 'seed': 100, 'reuse_seed': 0})

    def test_nondefault_profiles_are_scout_only_and_formal_offsets_are_validated(self):
        capture.validate_capture_controls('pdf-similarity', seed_offset=100000)
        for kwargs in ({'pdf_profile': 'zero'},):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                capture.validate_capture_controls('pdf-similarity', scout=False, **kwargs)
        capture.validate_capture_controls('pdf-similarity', scout=True,
                                          seed_offset=100, pdf_profile='observe')
        for kwargs in ({'seed_offset': -1}, {'seed_offset': True}, {'seed_offset': 2**32},
                       {'pdf_profile': 'typo'}, {'pdf_profile': 'center'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                capture.validate_capture_controls('baseline', scout=True, **kwargs)


class PdfCampaignTests(unittest.TestCase):
    def test_method_selection_preserves_legacy_defaults(self):
        self.assertEqual(campaign._job_specs(True, False),
                         (('baseline', 'baseline', True), ('cgns', 'cgns', True)))
        self.assertEqual(campaign._job_specs(False, False, compare_method='pdf-similarity'),
                         (('baseline', 'baseline', False),
                          ('pdf-similarity', 'pdf-similarity', False)))
        with self.assertRaises(ValueError):
            campaign._job_specs(True, True, compare_method='pdf-similarity')

    def test_pdf_payload_is_named_for_the_actual_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = [{'frame': 41, 'hdr': 'frame.exr', 'sha256': 'a' * 64}]
            done = {('classroom', 'view-a'): {
                method: (root / method, {'artifacts': artifacts})
                for method in ('baseline', 'pdf-similarity')}}
            catalog = {('classroom', 'view-a'): {
                'reference': {'path': str(root / 'reference.exr'), 'sha256': 'b' * 64}}}
            payload = campaign._analysis_payload(catalog, done, root / 'input.json',
                                                 'c' * 64, 40, 1, True, False,
                                                 compare_method='pdf-similarity')
            self.assertEqual(payload['settings']['comparison_kind'], 'spatial-pdf-similarity')
            self.assertEqual(set(payload['views'][0]['pairs'][0]),
                             {'id', 'baseline', 'pdf-similarity'})
            self.assertIn('PDF', payload['settings']['provenance'])
            self.assertNotIn('CGNS', payload['settings']['provenance'])

    def test_cli_dispatches_pdf_without_preparing_or_rendering(self):
        with patch.object(campaign, 'run_campaign', return_value=Path('report')) as launch:
            campaign.main(['--output', 'out', '--compare-method', 'pdf-similarity'])
        self.assertEqual(launch.call_args.kwargs['compare_method'], 'pdf-similarity')


class PdfCampaignFlowTests(unittest.TestCase):
    from tests.backends.test_falcor_spatial_campaign import TemporalContrastCampaignTests
    fixture = TemporalContrastCampaignTests.fixture

    def test_pdf_campaign_writes_an_honestly_named_report_and_retains_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls, prepare = self.fixture(root, view_count=6)
            identity = patch.object(campaign, '_campaign_code_identity', return_value={'code': 'constant'})
            identity.start()
            self.addCleanup(identity.stop)
            paths = prepare.return_value
            paths['pdf-similarity', False] = paths.pop(('cgns', False))
            output = root / 'campaign'
            report = campaign.run_campaign(output, compare_method='pdf-similarity')
            summary = json.loads((report / 'summary.json').read_text(encoding='utf8'))
            self.assertEqual(len(calls), 12)
            self.assertEqual({method for method, _, _ in calls}, {'baseline', 'pdf-similarity'})
            self.assertEqual(summary['settings']['comparison_kind'], 'spatial-pdf-similarity')
            self.assertIn('pdf-similarity_smape_percent', summary['views'][0])
            self.assertNotIn('CGNS', summary['metric']['relative_improvement'])
            html = (report / 'index.html').read_text(encoding='utf8')
            self.assertIn('PDF similarity', html)
            self.assertNotIn('CGNS', html)
            artifacts = {path: path.read_bytes() for path in output.rglob('*.exr')}
            self.assertEqual(len(artifacts), 96)
            self.assertEqual(campaign.run_campaign(output, compare_method='pdf-similarity'), report)
            with self.assertRaises(ValueError):
                campaign.run_campaign(output)
            self.assertEqual({path: path.read_bytes() for path in artifacts}, artifacts)


if __name__ == '__main__':
    unittest.main()
