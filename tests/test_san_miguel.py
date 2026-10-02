"""Regression for San Miguel's missing MTL alpha declarations."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/assets'))
from convert_scene import convert_scene


class SanMiguelTests(unittest.TestCase):
    def test_cutouts_keep_transparency_without_changing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new('RGBA', (2, 2), (20, 80, 20, 0)).save(root / 'leaf.png')
            Image.new('RGBA', (2, 2), (80, 80, 80, 255)).save(root / 'wall.png')
            data = {
                'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': []}], 'nodes': [],
                'images': [{'uri': 'leaf.png'}, {'uri': 'wall.png'}],
                'textures': [{'source': 0}, {'source': 1}],
                'materials': [
                    {'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}},
                    {'pbrMetallicRoughness': {'baseColorTexture': {'index': 1}}},
                    {'alphaMode': 'BLEND', 'pbrMetallicRoughness': {
                        'baseColorFactor': [1, 1, 1, 0.3]}}
                ]
            }
            raw, output = root / 'raw.gltf', root / 'converted/scene.gltf'
            raw.write_text(json.dumps(data), encoding='utf-8')
            before = raw.read_bytes()
            record = convert_scene(raw, output, "san-miguel")
            result = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(raw.read_bytes(), before)
            self.assertEqual(record['cutout_materials'], [0])
            self.assertEqual(result['materials'][0]['alphaMode'], 'MASK')
            self.assertEqual(result['materials'][1].get('alphaMode', 'OPAQUE'), 'OPAQUE')
            self.assertEqual(result['materials'][2]['alphaMode'], 'BLEND')
            self.assertNotIn('KHR_lights_punctual', result.get('extensions', {}))
            self.assertEqual(result['nodes'], data['nodes'])



if __name__ == '__main__':
    unittest.main()
