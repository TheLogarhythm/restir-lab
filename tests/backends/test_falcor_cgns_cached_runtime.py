"""Exercise cached runtime packages with tiny files and a native compiler fixture."""
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.falcor import cgns_cached_runtime as runtime

ROOT = Path(__file__).resolve().parents[2]
PARAMETERS = {'candidate_count': 32, 'position_scale': 0.05, 'normal_exponent': 8.0,
              'early_stop_score': 0.5, 'early_stop_count': 1}
SHADER = 'shaders/ReSTIRPathTracing/SpatialResampling.cs.slang'
EXTRA = 'shaders/ReSTIRPathTracing/cgns_cached_select.cs.slang'
LINK_NAMES = ('Falcor.lib', 'fmt.lib', 'LightTileResampling.lib', 'python310.lib',
              'slang.lib', 'gfx.lib', 'cuda.lib', 'cudart_static.lib')


def digest(data):
    return hashlib.sha256(data).hexdigest()


class CachedRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root / 'build/falcor').mkdir(parents=True)
        (self.root / 'build/falcor/build.json').write_text('{"commit":"fixture"}', encoding='utf8')
        self.scripts = self.root / 'scripts/falcor'
        self.scripts.mkdir(parents=True)
        # Keep the real dependency enumeration and hashing. Only source locations
        # move into the fixture; changing a live helper must change the package ID.
        modules = [runtime, runtime.overlay, runtime.compiler, runtime.original,
                   runtime.original.legacy, runtime.build]
        from scripts.falcor import process_utils, spatial_experiment_config
        modules.extend((process_utils, spatial_experiment_config))
        from scripts.falcor import runtime_common
        modules.append(runtime_common)
        files = set(runtime.implementation_files())
        files.update(Path(module.__file__) for module in modules)
        for source in files:
            target = self.root / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        self.common_source = self.scripts / 'runtime_common.py'
        for module in modules:
            self.enterContext(patch.object(module, '__file__', str(self.scripts / Path(module.__file__).name)))
        self.enterContext(patch.object(runtime, 'ROOT', self.root))
        self.enterContext(patch.object(runtime.overlay, 'HERE', self.scripts))
        self.enterContext(patch.object(runtime.overlay, 'HOST_IMPLEMENTATION', self.scripts / 'cgns_cached_dispatch.inl'))
        for name in ('SELECTOR', 'CORE'):
            self.enterContext(patch.object(runtime.original, name, self.scripts / getattr(runtime.original, name).name))
        source_dest = self.root / 'build/base-reference'
        base = source_dest / 'runtime'
        content = {SHADER: b'original shader', 'Mogwai.exe': b'executable',
                   'Falcor.dll': b'library', runtime.PLUGIN: b'original plugin',
                   'Falcor.pdb': b'debug symbols'}
        for name, data in content.items():
            target = base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.base_receipt = {'runtime_files_sha256': {name: digest(data) for name, data in content.items()}}
        (source_dest / 'receipt.json').write_text(json.dumps(self.base_receipt), encoding='utf8')
        self.source = SimpleNamespace(DEST=source_dest, verify=lambda: self.base_receipt)
        self.enterContext(patch.object(runtime, 'SOURCES', {'reference': self.source}))
        self.enterContext(patch.object(runtime, 'exclusive_operation', return_value=nullcontext()))
        self.enterContext(patch.object(runtime, 'check_renderer_idle'))
        self.enterContext(patch.object(runtime.build, 'verify_build', return_value={'commit': 'fixture'}))
        self.enterContext(patch.object(runtime.overlay, 'shader_outputs', side_effect=self.shaders))
        self.enterContext(patch.object(runtime, '_compile_plugin', side_effect=self.compile_plugin))

    def shaders(self, source, parameters):
        return {SHADER: (source / SHADER).read_text(encoding='utf8') + '// cached',
                EXTRA: '// new selector'}

    def compile_plugin(self, folder, record):
        module = folder / 'ReSTIRPathTracing'
        module.mkdir()
        for name in ('ReSTIRPathTracing.h', 'ReSTIRPathTracing.cpp'):
            (module / name).write_text('// generated ' + name, encoding='utf8')
        (folder / 'PathTracer.dll').write_bytes(b'private plugin')
        return {'plugin_sha256': digest(b'private plugin'), 'falcor_commit': record['commit'],
                'generated_host_sha256': {p.name: runtime.sha(p) for p in module.iterdir()},
                'link_inputs_sha256': {name: digest(name.encode()) for name in LINK_NAMES}}

    def ensure(self):
        return runtime.ensure_variant('reference', PARAMETERS)

    def test_shared_helper_bytes_change_the_current_variant_identity(self):
        before = runtime.variant_destination('reference', PARAMETERS)
        self.common_source.write_bytes(self.common_source.read_bytes() + b'\n# changed safety policy')
        self.assertNotEqual(before, runtime.variant_destination('reference', PARAMETERS))

    def test_host_source_tampering_and_missing_files_are_rejected(self):
        prepared = self.ensure()
        source = prepared.parent / 'host/ReSTIRPathTracing/ReSTIRPathTracing.cpp'
        original = source.read_bytes()
        source.write_bytes(b'changed generated host')
        with self.assertRaisesRegex(ValueError, 'host source'):
            runtime.verify_prepared(prepared, expected_parameters=PARAMETERS)
        source.write_bytes(original)
        source.unlink()
        with self.assertRaisesRegex(ValueError, 'host source'):
            runtime.verify_prepared(prepared, expected_parameters=PARAMETERS)

    def test_link_receipt_is_recorded_hashes_not_a_requirement_for_local_build_inputs(self):
        prepared = self.ensure()
        self.assertEqual((prepared / runtime.PLUGIN).read_bytes(), b'private plugin')
        # There are deliberately no .lib files in this fixture. A deployed
        # package verifies recorded link provenance without reopening build inputs.
        runtime.verify_prepared(prepared, expected_parameters=PARAMETERS)
        path = prepared.parent / 'receipt.json'
        receipt = json.loads(path.read_text(encoding='utf8'))
        for invalid in ({}, {'../outside.lib': 'a' * 64},
                        {**receipt['link_inputs_sha256'], 'Falcor.lib': 'not-a-hash'}):
            with self.subTest(invalid=invalid):
                path.write_text(json.dumps({**receipt, 'link_inputs_sha256': invalid}), encoding='utf8')
                with self.assertRaisesRegex(ValueError, 'link input'):
                    runtime.verify_prepared(prepared, expected_parameters=PARAMETERS)
        path.write_text(json.dumps(receipt), encoding='utf8')

    def test_package_copies_are_private_and_reuse_rejects_changed_runtime_bytes(self):
        base = self.source.DEST / 'runtime'
        original = {p.relative_to(base).as_posix(): p.read_bytes() for p in base.rglob('*') if p.is_file()}
        prepared = self.ensure()
        self.assertEqual(prepared, self.ensure())
        self.assertFalse((prepared / 'Falcor.pdb').exists())
        self.assertTrue((prepared / '.shadercache').is_dir())
        for name in ('Mogwai.exe', 'Falcor.dll'):
            self.assertNotEqual((prepared / name).stat().st_ino, (base / name).stat().st_ino)
        (prepared / runtime.PLUGIN).write_bytes(b'corrupt plugin')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.ensure()
        self.assertEqual(original, {p.relative_to(base).as_posix(): p.read_bytes()
                                    for p in base.rglob('*') if p.is_file()})

    def test_compiler_failure_does_not_publish_a_variant(self):
        dest = runtime.variant_destination('reference', PARAMETERS)
        with patch.object(runtime, '_compile_plugin', side_effect=RuntimeError('compiler fixture failed')):
            with self.assertRaisesRegex(RuntimeError, 'compiler fixture failed'):
                self.ensure()
        self.assertFalse(dest.exists())
        self.assertEqual((self.source.DEST / 'runtime' / SHADER).read_bytes(), b'original shader')

    def test_legacy_snapshot_requires_a_trusted_receipt_and_cannot_count_as_current(self):
        prepared = self.ensure()
        path = prepared.parent / 'receipt.json'
        receipt = json.loads(path.read_text(encoding='utf8'))
        receipt['schema_version'] = 1
        path.write_text(json.dumps(receipt), encoding='utf8')
        pinned = runtime.sha(path)
        with self.assertRaisesRegex(ValueError, 'current'):
            runtime.verify_prepared(prepared, expected_parameters=PARAMETERS)
        before = {p: p.read_bytes() for p in prepared.parent.rglob('*') if p.is_file()}
        self.common_source.write_bytes(b'# later implementation')
        verified = runtime.verify_snapshot(prepared, expected_receipt_sha256=pinned)
        self.assertFalse(verified['current_implementation'])
        self.assertEqual(verified['verification_scope'], 'recorded-bytes-only')
        self.assertEqual(verified['receipt_sha256'], pinned)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        with self.assertRaisesRegex(ValueError, 'trusted record'):
            runtime.verify_snapshot(prepared, expected_receipt_sha256='0' * 64)
        (prepared / SHADER).write_bytes(b'tampered archived shader')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            runtime.verify_snapshot(prepared, expected_receipt_sha256=pinned)

    def test_snapshot_rejects_missing_build_records_and_escaping_paths(self):
        prepared = self.ensure()
        path = prepared.parent / 'receipt.json'
        receipt = json.loads(path.read_text(encoding='utf8'))
        missing = dict(receipt)
        missing.pop('generated_host_sha256')
        path.write_text(json.dumps(missing), encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'host source'):
            runtime.verify_snapshot(prepared, expected_receipt_sha256=runtime.sha(path))
        invalid = {**receipt, 'shader_sha256': {'../outside.slang': 'a' * 64}}
        path.write_text(json.dumps(invalid), encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'file name'):
            runtime.verify_snapshot(prepared, expected_receipt_sha256=runtime.sha(path))


if __name__ == '__main__':
    unittest.main()
