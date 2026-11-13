import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.falcor import prepare_gltf_composite_runtime_v2 as runtime

class QuarantineTests(unittest.TestCase):
    def test_moves_only_known_transients(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runtime, 'DEST', Path(tmp)):
            root = Path(tmp) / 'runtime'; root.mkdir()
            (Path(tmp)/'receipt.json').write_text(json.dumps({'runtime_files_sha256': {'Mogwai.exe.0.log': 'fixed'}}))
            (root/'Mogwai.exe.0.log').write_text('baseline')
            cache = root / '.shadercache'; cache.mkdir(); (cache / 'entry').write_text('cache')
            (root / 'Mogwai.exe.42.log').write_text('log')
            (root / 'unrecognized.dll').write_text('preserve')
            dest = runtime.quarantine_transients()
            self.assertEqual((dest / '.shadercache/entry').read_text(), 'cache')
            self.assertEqual((dest / 'Mogwai.exe.42.log').read_text(), 'log')
            self.assertEqual((root / 'unrecognized.dll').read_text(), 'preserve')
            self.assertEqual((root / 'Mogwai.exe.0.log').read_text(), 'baseline')
            self.assertIsNone(runtime.quarantine_transients())

    def test_rejects_unexpected_cache_directory(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runtime, 'DEST', Path(tmp)):
            cache = Path(tmp) / 'runtime/.shadercache'; cache.mkdir(parents=True)
            (Path(tmp)/'receipt.json').write_text(json.dumps({'runtime_files_sha256': {}}))
            (cache / 'unexpected_directory').mkdir()
            with self.assertRaises(RuntimeError): runtime.quarantine_transients()
            self.assertTrue(cache.exists())

    def test_recorded_shader_cache_is_never_moved(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runtime, 'DEST', Path(tmp)):
            cache = Path(tmp) / 'runtime/.shadercache'; cache.mkdir(parents=True)
            (cache/'entry').write_text('recorded')
            (Path(tmp)/'receipt.json').write_text(json.dumps({'runtime_files_sha256': {'.shadercache/entry': 'fixed'}}))
            with self.assertRaisesRegex(RuntimeError, 'recorded shader cache'): runtime.quarantine_transients()
            self.assertTrue((cache/'entry').exists())

    def test_verify_rejects_unlisted_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); dest = base/'dest'; source = base/'source'
            (dest/'runtime/plugins').mkdir(parents=True); source.mkdir()
            (source/'receipt.json').write_text('{}')
            (dest/'runtime/plugins/unknown.dll').write_text('unlisted')
            record={'baseline_receipt_sha256':runtime.digest(source/'receipt.json'), 'input_sha256':{}, 'runtime_files_sha256':{}}
            (dest/'receipt.json').write_text(json.dumps(record))
            with patch.object(runtime,'DEST',dest), patch.object(runtime,'SOURCE',source):
                with self.assertRaisesRegex(RuntimeError,'inventory mismatch'): runtime.verify()

if __name__ == '__main__': unittest.main()
