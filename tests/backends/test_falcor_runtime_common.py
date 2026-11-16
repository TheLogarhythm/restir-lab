"""Validate neutral runtime inventory boundaries with real small files."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from scripts.falcor import runtime_common as common


class RuntimeCommonTests(unittest.TestCase):
    def test_expected_inventory_cannot_escape_before_the_baseline_verifier_runs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'runtime').mkdir()
            (root / 'outside').write_bytes(b'preserve')
            (root / 'receipt.json').write_text(json.dumps({
                'runtime_files_sha256': {'../outside': hashlib.sha256(b'preserve').hexdigest()}}))
            def must_not_read_unvalidated_paths():
                raise RuntimeError('legacy verifier saw an unsafe filename')
            module = SimpleNamespace(DEST=root, verify=must_not_read_unvalidated_paths)
            with self.assertRaisesRegex(ValueError, 'file name'):
                common.read_baseline(module)
            self.assertEqual((root / 'outside').read_bytes(), b'preserve')

    def test_only_known_generated_files_are_ignored_by_inventory_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Mogwai.exe').write_bytes(b'executable')
            expected = {'Mogwai.exe': hashlib.sha256(b'executable').hexdigest()}
            (root / '.shadercache').mkdir()
            (root / '.shadercache/cache').write_bytes(b'generated')
            (root / 'Mogwai.exe.123.log').write_bytes(b'log')
            common.validate_runtime_inventory(root, expected)
            (root / 'unexpected.log').write_bytes(b'extra')
            with self.assertRaisesRegex(ValueError, 'extra=.*unexpected.log'):
                common.validate_runtime_inventory(root, expected)
            (root / 'unexpected.log').unlink()
            (root / 'Mogwai.exe').unlink()
            with self.assertRaisesRegex(ValueError, 'missing=.*Mogwai.exe'):
                common.validate_runtime_inventory(root, expected)

    def test_snapshot_paths_cannot_alias_a_baseline_or_escape_the_build_namespace(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for runtime in (root / 'build/base/runtime', root / 'outside/falcor-pdf-pt-private/runtime',
                            root / 'build/falcor-pdf-pt-private/nested/runtime'):
                with self.subTest(runtime=runtime), self.assertRaisesRegex(ValueError, 'private runtime'):
                    common.private_runtime_path(runtime, root=root, prefix='falcor-pdf-pt-')


if __name__ == '__main__':
    unittest.main()
