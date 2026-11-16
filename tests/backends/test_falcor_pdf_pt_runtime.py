"""Exercise private runtime provenance with tiny files, never a GPU renderer."""
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.falcor import pdf_pt_overlay as overlay
from scripts.falcor import pdf_pt_runtime as runtime
from scripts.falcor import runtime_common


PARAMETERS = {'history_limit': 20, 'history_decay': 0.95}
SHADER = 'shaders/ReSTIRPathTracing/PathReservoir.slang'
READ_ONLY_INPUT = 'shaders/ReSTIRPathTracing/ReflectTypes.cs.slang'


class PdfPtRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root / 'build').mkdir()
        (self.root / 'scripts/falcor').mkdir(parents=True)
        for name in ('pdf_pt_shader.py', 'pdf_pt_overlay.py', 'pdf_pt_runtime.py', 'pdf_pt_direction.h', 'runtime_common.py'):
            (self.root / 'scripts/falcor' / name).write_text(name, encoding='utf8')
        self.shader_file = self.root / 'scripts/falcor/pdf_pt_shader.py'
        self.helper = self.root / 'scripts/falcor/pdf_pt_direction.h'
        self.shader = SimpleNamespace(
            __file__=str(self.shader_file), FILES=(SHADER, READ_ONLY_INPUT),
            source_files=lambda: (self.shader_file, self.helper),
            build_overlay=lambda sources, parameters, profile='normal': {
                SHADER: sources[SHADER] + '\n// ' + json.dumps(parameters, sort_keys=True) + ' ' + profile})
        self.enterContext(patch.object(overlay, 'ROOT', self.root))
        self.enterContext(patch.object(runtime, 'ROOT', self.root))
        self.enterContext(patch.object(overlay, '__file__', str(self.root / 'scripts/falcor/pdf_pt_overlay.py')))
        self.enterContext(patch.object(runtime, '__file__', str(self.root / 'scripts/falcor/pdf_pt_runtime.py')))
        self.enterContext(patch.object(runtime_common, '__file__', str(self.root / 'scripts/falcor/runtime_common.py')))
        self.enterContext(patch.object(overlay, 'shader_module', return_value=self.shader))
        sources = {}
        self.base_inventories = {}
        for kind in ('reference', 'gltf-v3'):
            destination = self.root / 'build' / ('base-' + kind)
            base = destination / 'runtime'
            base.mkdir(parents=True)
            content = {SHADER: b'original shader', READ_ONLY_INPUT: b'reflection source',
                       'Mogwai.exe': b'executable', 'Falcor.dll': b'library',
                       'plugins/plugins.json': kind.encode('utf8'), 'Falcor.pdb': b'debug symbols'}
            for name, data in content.items():
                target = base / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            receipt = {'runtime_files_sha256': {name: overlay.digest(data) for name, data in content.items()}}
            self.base_inventories[kind] = receipt
            (destination / 'receipt.json').write_text(json.dumps(receipt), encoding='utf8')
            sources[kind] = SimpleNamespace(DEST=destination, verify=lambda receipt=receipt: receipt)
        self.enterContext(patch.dict(runtime.SOURCES, sources))
        self.lock_calls = []
        self.enterContext(patch.object(runtime, 'exclusive_operation',
                                      side_effect=lambda path: self._lock(path)))
        self.enterContext(patch.object(runtime, 'check_renderer_idle',
                                      side_effect=lambda: self.lock_calls.append('idle')))

    def _lock(self, path):
        self.lock_calls.append(path)
        return nullcontext()

    def ensure(self, kind='reference', parameters=None, profile='normal'):
        return runtime.ensure_variant(kind, PARAMETERS if parameters is None else parameters, profile=profile)

    def test_prepare_both_sources_preserves_base_and_read_only_shader_inputs(self):
        for kind in ('reference', 'gltf-v3'):
            with self.subTest(kind=kind):
                base = runtime.SOURCES[kind].DEST / 'runtime'
                before = {p.relative_to(base).as_posix(): p.read_bytes() for p in base.rglob('*') if p.is_file()}
                prepared = self.ensure(kind)
                verified = runtime.verify_prepared(prepared, PARAMETERS)
                self.assertEqual(verified['kind'], 'verified_pdf_pt_overlay_runtime')
                self.assertEqual(verified['source_kind'], kind)
                self.assertEqual(verified['parameters'], PARAMETERS)
                self.assertEqual((prepared / READ_ONLY_INPUT).read_bytes(), before[READ_ONLY_INPUT])
                self.assertFalse((prepared / 'Falcor.pdb').exists())
                self.assertTrue((prepared / '.shadercache').is_dir())
                self.assertEqual((prepared / 'plugins/plugins.json').read_bytes(), kind.encode('utf8'))
                self.assertEqual(before, {p.relative_to(base).as_posix(): p.read_bytes()
                                          for p in base.rglob('*') if p.is_file()})
                for name in ('Mogwai.exe', 'Falcor.dll', SHADER):
                    self.assertNotEqual((base / name).stat().st_ino, (prepared / name).stat().st_ino)
                    self.assertEqual((prepared / name).stat().st_nlink, 1)

    def test_identity_is_order_independent_and_tracks_parameters_profile_and_source(self):
        baseline = runtime.variant_destination('reference', PARAMETERS)
        self.assertEqual(baseline, runtime.variant_destination('reference', dict(reversed(list(PARAMETERS.items())))))
        variants = [runtime.variant_destination('reference', {**PARAMETERS, 'history_limit': 10}),
                    runtime.variant_destination('reference', {**PARAMETERS, 'history_decay': 0.9}),
                    runtime.variant_destination('reference', PARAMETERS, profile='one'),
                    runtime.variant_destination('gltf-v3', PARAMETERS)]
        for variant in variants:
            self.assertNotEqual(baseline, variant)

    def test_identity_tracks_implementation_and_source_receipt_bytes(self):
        baseline = runtime.variant_destination('reference', PARAMETERS)
        for target in (self.shader_file, self.helper, self.root / 'scripts/falcor/pdf_pt_overlay.py',
                       self.root / 'scripts/falcor/pdf_pt_runtime.py',
                       self.root / 'scripts/falcor/runtime_common.py',
                       runtime.SOURCES['reference'].DEST / 'receipt.json'):
            original = target.read_bytes()
            target.write_bytes(original + b'\n')
            with self.subTest(target=target):
                self.assertNotEqual(baseline, runtime.variant_destination('reference', PARAMETERS))
            target.write_bytes(original)

    def test_ensure_reuses_verified_runtime_under_lock_and_checks_idle(self):
        prepared = self.ensure()
        self.lock_calls.clear()
        with patch.object(runtime, '_prepare_locked', side_effect=AssertionError('must not recreate')):
            self.assertEqual(prepared, self.ensure())
        self.assertEqual(self.lock_calls, [self.root / 'build/falcor/.operation.lock', 'idle'])

    def test_incomplete_variant_is_rejected_and_preserved(self):
        dest = runtime.variant_destination('reference', PARAMETERS)
        dest.mkdir()
        (dest / 'incomplete').write_bytes(b'keep for diagnosis')
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.ensure()
        self.assertEqual((dest / 'incomplete').read_bytes(), b'keep for diagnosis')

    def test_ensure_rejects_a_different_source_variant_at_the_requested_destination(self):
        self.ensure()
        with patch.object(runtime, 'verify_prepared', return_value={'source_kind': 'gltf-v3'}):
            with self.assertRaisesRegex(ValueError, 'source kind'):
                self.ensure()

    def test_read_only_source_shader_can_be_patched_without_changing_source(self):
        source = runtime.SOURCES['reference'].DEST / 'runtime' / SHADER
        source.chmod(0o444)
        original = source.read_bytes()
        prepared = self.ensure()
        self.assertEqual(source.read_bytes(), original)
        self.assertNotEqual((prepared / SHADER).read_bytes(), original)
        self.assertTrue((prepared / SHADER).stat().st_mode & 0o200)

    def test_verification_rejects_wrong_parameters_profile_shader_and_extra_file(self):
        prepared = self.ensure()
        with self.assertRaisesRegex(ValueError, 'parameters'):
            runtime.verify_prepared(prepared, {**PARAMETERS, 'history_limit': 10})
        with self.assertRaisesRegex(ValueError, 'profile'):
            runtime.verify_prepared(prepared, PARAMETERS, profile='observe')
        shader = prepared / SHADER
        original = shader.read_bytes()
        shader.write_bytes(original + b'tampered')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            runtime.verify_prepared(prepared, PARAMETERS)
        shader.write_bytes(original)
        (prepared / 'unrecorded.dll').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'inventory differs'):
            runtime.verify_prepared(prepared, PARAMETERS)

    def test_verification_rebuilds_expected_overlay_instead_of_trusting_receipt(self):
        prepared = self.ensure()
        shader = prepared / SHADER
        shader.write_bytes(b'forged shader')
        receipt_path = prepared.parent / 'receipt.json'
        receipt = json.loads(receipt_path.read_text(encoding='utf8'))
        receipt['overlay']['files'][SHADER]['patched_sha256'] = runtime.sha(shader)
        receipt_path.write_text(json.dumps(receipt), encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'overlay source hash'):
            runtime.verify_prepared(prepared, PARAMETERS)

    def test_source_or_implementation_changes_reject_existing_runtime(self):
        prepared = self.ensure()
        self.helper.write_bytes(b'changed implementation')
        with self.assertRaisesRegex(ValueError, 'implementation or source receipt'):
            runtime.verify_prepared(prepared, PARAMETERS)

    def test_profiles_get_distinct_cache_directories_and_shader_bytes(self):
        prepared = [self.ensure(profile=profile) for profile in overlay.PROFILES]
        self.assertEqual(len(set(prepared)), len(overlay.PROFILES))
        self.assertEqual(len({(p / SHADER).read_bytes() for p in prepared}), len(overlay.PROFILES))
        for profile, path in zip(overlay.PROFILES, prepared):
            self.assertEqual(runtime.verify_prepared(path, PARAMETERS, profile=profile)['profile'], profile)
        (prepared[0] / '.shadercache/entry').write_bytes(b'private compiled code')
        self.assertTrue(all(not (p / '.shadercache/entry').exists() for p in prepared[1:]))

    def test_known_transients_are_not_copied_and_runtime_generated_files_are_allowed(self):
        base = runtime.SOURCES['reference'].DEST / 'runtime'
        (base / '.shadercache').mkdir()
        (base / '.shadercache/old').write_bytes(b'old cache')
        (base / 'Mogwai.exe.123.log').write_bytes(b'old log')
        prepared = self.ensure()
        self.assertEqual(list((prepared / '.shadercache').iterdir()), [])
        self.assertFalse((prepared / 'Mogwai.exe.123.log').exists())
        (prepared / 'Mogwai.exe.456.log').write_bytes(b'new log')
        (prepared / '.shadercache/compiled').write_bytes(b'new cache')
        runtime.verify_prepared(prepared, PARAMETERS)

    def test_baseline_mismatch_is_rejected_before_private_destination_creation(self):
        base = runtime.SOURCES['reference'].DEST / 'runtime'
        (base / 'Falcor.dll').write_bytes(b'changed baseline')
        dest = runtime.variant_destination('reference', PARAMETERS)
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.ensure()
        self.assertFalse(dest.exists())

    def test_rejects_frozen_or_outside_destination_and_runtime(self):
        for dest in (self.root / 'build/base-reference', self.root / 'build/base-reference/nested',
                     self.root / 'outside/falcor-pdf-pt-test', self.root / 'build/other-name'):
            with self.subTest(dest=dest), self.assertRaises(ValueError):
                runtime.validate_request('reference', dest)
        with self.assertRaises(ValueError):
            runtime.variant_destination('unknown', PARAMETERS)
        with self.assertRaisesRegex(ValueError, 'private runtime'):
            runtime.verify_prepared(runtime.SOURCES['reference'].DEST / 'runtime', PARAMETERS)
        with self.assertRaisesRegex(ValueError, 'private build'):
            overlay.apply_overlay(runtime.SOURCES['reference'].DEST / 'runtime', PARAMETERS)

    def test_hardlinked_overlay_target_is_rejected_before_any_write(self):
        prepared = self.ensure()
        original = (prepared / SHADER).read_bytes()
        info = (prepared / SHADER).stat()
        real_reject = overlay.reject_link
        def hardlinked(path):
            if Path(path) == prepared / SHADER:
                return SimpleNamespace(st_nlink=2, st_mode=info.st_mode)
            return real_reject(path)
        with patch.object(overlay, 'reject_link', side_effect=hardlinked):
            with self.assertRaisesRegex(ValueError, 'hardlinked'):
                overlay.apply_overlay(prepared, PARAMETERS)
        self.assertEqual((prepared / SHADER).read_bytes(), original)

    def test_windows_reparse_attribute_is_rejected_even_when_not_a_symlink(self):
        path = self.root / 'junction'
        with patch.object(Path, 'lstat', return_value=SimpleNamespace(st_file_attributes=0x400)), \
             patch.object(Path, 'is_symlink', return_value=False):
            with self.assertRaisesRegex(ValueError, 'reparse'):
                overlay.reject_link(path)


    def test_snapshot_accepts_pinned_legacy_bytes_without_authorizing_current_rendering(self):
        prepared = self.ensure()
        path = prepared.parent / 'receipt.json'
        receipt = json.loads(path.read_text(encoding='utf8'))
        receipt['schema_version'] = 1
        path.write_text(json.dumps(receipt), encoding='utf8')
        pinned = runtime.sha(path)
        with self.assertRaisesRegex(ValueError, 'current'):
            runtime.verify_prepared(prepared, PARAMETERS)
        self.helper.write_bytes(b'changed current shader implementation')
        before = {p: p.read_bytes() for p in prepared.parent.rglob('*') if p.is_file()}
        verified = runtime.verify_snapshot(prepared, expected_receipt_sha256=pinned)
        self.assertFalse(verified['current_implementation'])
        self.assertEqual(verified['verification_scope'], 'recorded-bytes-only')
        self.assertEqual(verified['receipt_sha256'], pinned)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        with self.assertRaisesRegex(ValueError, 'trusted record'):
            runtime.verify_snapshot(prepared, expected_receipt_sha256='0' * 64)
        (prepared / SHADER).write_bytes(b'changed frozen shader')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            runtime.verify_snapshot(prepared, expected_receipt_sha256=pinned)

    def test_snapshot_rejects_escaping_overlay_paths_and_changed_source_receipts(self):
        prepared = self.ensure()
        path = prepared.parent / 'receipt.json'
        original = path.read_bytes()
        receipt = json.loads(original)
        receipt['overlay']['files'] = {'../outside': {'original_sha256': 'a' * 64, 'patched_sha256': 'b' * 64}}
        path.write_text(json.dumps(receipt), encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'file name'):
            runtime.verify_snapshot(prepared, expected_receipt_sha256=runtime.sha(path))
        path.write_bytes(original)
        source_receipt = runtime.SOURCES['reference'].DEST / 'receipt.json'
        source_receipt.write_bytes(b'changed source receipt')
        with self.assertRaisesRegex(ValueError, 'source receipt'):
            runtime.verify_snapshot(prepared, expected_receipt_sha256=runtime.sha(path))


class PdfPtOverlayContractTests(unittest.TestCase):
    def test_bad_parameters_and_profile_fail_before_loading_implementation(self):
        invalid = [None, {}, {**PARAMETERS, 'extra': 1},
                   {**PARAMETERS, 'history_limit': True}, {**PARAMETERS, 'history_limit': 0},
                   {**PARAMETERS, 'history_limit': 101}, {**PARAMETERS, 'history_decay': True},
                   {**PARAMETERS, 'history_decay': -0.1}, {**PARAMETERS, 'history_decay': 1.1},
                   {**PARAMETERS, 'history_decay': float('nan')},
                   {**PARAMETERS, 'history_decay': float('inf')}, {**PARAMETERS, 'history_decay': 1e-100}]
        with patch.object(overlay, 'shader_module', side_effect=AssertionError('must validate first')):
            for parameters in invalid:
                with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                    overlay.build_overlay({}, parameters)
            with self.assertRaises(ValueError):
                overlay.build_overlay({}, PARAMETERS, profile='unknown')

    def test_input_mapping_is_detached_and_outputs_are_existing_changes_only(self):
        sources = {'shaders/a.slang': 'original'}
        def mutate(sources, parameters, profile='normal'):
            sources['shaders/a.slang'] += ' modified'
            return sources
        shader = SimpleNamespace(FILES=('shaders/a.slang',), build_overlay=mutate)
        with patch.object(overlay, 'shader_module', return_value=shader):
            self.assertEqual(overlay.build_overlay(sources, PARAMETERS), {'shaders/a.slang': 'original modified'})
            self.assertEqual(sources, {'shaders/a.slang': 'original'})
            for output in ({}, {'shaders/new.slang': 'new'}, {'shaders/a.slang': 'original'},
                           {'shaders/a.slang': b'bytes'}):
                shader.build_overlay = lambda *args, output=output, **kwargs: output
                with self.subTest(output=output), self.assertRaises(ValueError):
                    overlay.build_overlay(sources, PARAMETERS)

    def test_runtime_file_names_are_relative_and_canonical(self):
        for name in ('../outside', '/absolute', 'C:/absolute', 'shaders\\wrong.slang',
                     'shaders/../outside', 'shaders//double', './dot', '', 'shaders/a:stream', '\x00'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                overlay.safe_name(name)
        self.assertEqual(overlay.safe_name(SHADER), SHADER)


if __name__ == '__main__':
    unittest.main()
