import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.falcor import prepare_bistro_sky_asset as sky


class PrepareBistroSkyTest(unittest.TestCase):
    def test_existing_sky_is_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / 'sky.exr'
            output.write_bytes(b'not the sky')
            with self.assertRaises(ValueError):
                sky.prepare(output, root=root)
            self.assertEqual(output.read_bytes(), b'not the sky')

    def test_existing_verified_sky_is_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / 'sky.exr'
            data = b'prepared sky fixture'
            output.write_bytes(data)
            expected = sky.sha(output)
            with patch.object(sky, 'EXPECTED_SHA256', expected), patch.object(sky.bake_donut_sky, 'bake') as bake:
                self.assertEqual(sky.prepare(output, root=root), output.resolve())
                bake.assert_not_called()
            self.assertEqual(output.read_bytes(), data)
