import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.falcor.reference_catalog import load_catalog


class ReferenceCatalogTest(unittest.TestCase):
    def test_reference_images_are_optional_until_requested(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / 'assets/ref.exr'
            manifest = root / 'catalog.json'
            data = {'schema_version': 1, 'path_base': 'repository_root', 'name': 'test',
                    'resolution': [1920,1080], 'samples_per_pixel': 16384,
                    'views': [{'scene_id': 'x', 'view_id': 'v', 'path': 'assets/ref.exr',
                               'sha256': hashlib.sha256(b'image').hexdigest()}]}
            manifest.write_text(json.dumps(data), encoding='utf-8')
            self.assertEqual(load_catalog(manifest, root)[('x','v')]['path'], 'assets/ref.exr')
            with self.assertRaises(FileNotFoundError):
                load_catalog(manifest, root, require_images=True)
            image.parent.mkdir(); image.write_bytes(b'image')
            self.assertEqual(load_catalog(manifest, root, require_images=True)[('x','v')]['path'], 'assets/ref.exr')
            image.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                load_catalog(manifest, root, require_images=True)

    def test_rejects_paths_that_escape_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); manifest = root / 'catalog.json'
            manifest.write_text(json.dumps({'schema_version': 1, 'path_base': 'repository_root',
                'name': 'test', 'resolution': [1920,1080], 'samples_per_pixel': 16384,
                'views': [{'scene_id': 'x', 'view_id': 'v', 'path': '../outside.exr', 'sha256': '0'*64}]}))
            with self.assertRaises(ValueError):
                load_catalog(manifest, root)
