"""Relocated private runtimes retain their source and shader provenance."""
import json
import shutil
import tempfile
import unittest
from contextlib import ExitStack, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.falcor import cgns_runtime, cgns_single_runtime
from scripts.falcor.run import sha


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / 'renderers/falcor/upstream/Source/Modules/ReSTIRPathTracing'
PARAMETERS = {'candidate_count': 32, 'position_scale': 0.05, 'normal_exponent': 8.0,
              'early_stop_score': 0.5, 'early_stop_count': 1}


class PortableRuntimeReceiptTests(unittest.TestCase):
    def prepare_source(self, root, mod):
        dest = root / 'build/falcor-reference-runtime'
        source = dest / 'runtime'
        upstream = root / 'renderers/falcor/upstream/Source/Modules/ReSTIRPathTracing'
        upstream.mkdir(parents=True)
        module = source / mod.overlay.MODULE
        module.mkdir(parents=True)
        (source / 'Mogwai.exe').write_bytes(b'fake executable')
        for name in mod.overlay.FILES:
            data = (UPSTREAM / name).read_bytes()
            (upstream / name).write_bytes(data)
            (module / name).write_bytes(data)
        (dest / 'receipt.json').write_text('{"frozen":true}\n', encoding='utf8')
        inventory = {p.relative_to(source).as_posix(): sha(p) for p in source.rglob('*') if p.is_file()}
        return SimpleNamespace(DEST=dest, verify=lambda: {'runtime_files_sha256': inventory})

    def contexts(self, stack, root, mod, source):
        stack.enter_context(patch.object(mod, 'ROOT', root))
        stack.enter_context(patch.object(mod, 'SOURCES', {'reference': source}))
        stack.enter_context(patch.object(mod.overlay, 'ROOT', root))
        stack.enter_context(patch.object(mod, 'exclusive_operation', return_value=nullcontext()))
        stack.enter_context(patch.object(mod, 'check_renderer_idle'))

    def test_new_receipts_relocate_and_legacy_receipts_remain_strict(self):
        for mod, params, new_version, old_version in (
                (cgns_runtime, None, 2, 1),
                (cgns_single_runtime, None, 3, 1),
                (cgns_single_runtime, PARAMETERS, 4, 2)):
            with self.subTest(module=mod.__name__, parameters=params), tempfile.TemporaryDirectory() as tmp:
                first = Path(tmp) / 'first'; first.mkdir()
                source = self.prepare_source(first, mod)
                with ExitStack() as stack:
                    self.contexts(stack, first, mod, source)
                    dest = first / 'build/private-cgns'
                    if mod is cgns_runtime:
                        mod.prepare('reference', dest)
                    else:
                        mod._prepare_locked('reference', dest, params)
                    receipt_path = dest / 'receipt.json'
                    receipt = json.loads(receipt_path.read_text(encoding='utf8'))
                    self.assertEqual(receipt['schema_version'], new_version)
                    self.assertEqual(receipt['source_runtime'], 'build/falcor-reference-runtime/runtime')
                    expected = mod.verify_prepared(dest / 'runtime')
                    legacy = {**receipt, 'schema_version': old_version,
                              'source_runtime': str(source.DEST / 'runtime')}
                    receipt_path.write_text(json.dumps(legacy), encoding='utf8')
                    mod.verify_prepared(dest / 'runtime')
                    receipt_path.write_text(json.dumps(receipt), encoding='utf8')
                    expected = mod.verify_prepared(dest / 'runtime')
                second = Path(tmp) / 'second'
                shutil.copytree(first, second)
                first.rename(Path(tmp) / 'unavailable')
                moved_source = SimpleNamespace(DEST=second/'build/falcor-reference-runtime', verify=source.verify)
                with ExitStack() as stack:
                    self.contexts(stack, second, mod, moved_source)
                    moved = second / 'build/private-cgns/runtime'
                    self.assertEqual(mod.verify_prepared(moved), expected)
                    receipt_path = moved.parent / 'receipt.json'
                    source_receipt = moved_source.DEST / 'receipt.json'
                    original = source_receipt.read_bytes()
                    source_receipt.write_bytes(b'changed')
                    with self.assertRaises(ValueError): mod.verify_prepared(moved)
                    source_receipt.write_bytes(original)
                    shader = moved / mod.overlay.MODULE / next(iter(mod.overlay.FILES))
                    original = shader.read_bytes()
                    shader.write_bytes(original + b'\n// tampered\n')
                    with self.assertRaises(ValueError): mod.verify_prepared(moved)
                    shader.write_bytes(original)
                    for invalid in ('../outside', str(source.DEST/'runtime')):
                        receipt_path.write_text(json.dumps({**receipt, 'source_runtime': invalid}), encoding='utf8')
                        with self.assertRaises(ValueError): mod.verify_prepared(moved)
                    receipt_path.write_text(json.dumps(legacy), encoding='utf8')
                    with self.assertRaises(ValueError): mod.verify_prepared(moved)


if __name__ == '__main__':
    unittest.main()
