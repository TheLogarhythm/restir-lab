"""Lossless compressed HDR storage, without reference or analysis dependencies."""
import gzip
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment import images


class ImageIOTests(unittest.TestCase):
    def test_gzip_pfm_preserves_bytes_pixels_and_has_no_plain_copy(self):
        rgb = np.array([[[0, -2, 100000], [.125, 1.5, 4]],
                        [[3, .25, -0.], [1e-10, 7, 2]]], dtype=np.float32)
        expected = b"PF\n2 2\n-1.0\n" + rgb[::-1].tobytes()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "image.pfm.gz"
            images.write_pfm(path, rgb)
            self.assertEqual(gzip.decompress(path.read_bytes()), expected)
            np.testing.assert_array_equal(images.read_pfm(path), rgb)
            self.assertEqual(list(Path(folder).iterdir()), [path])
            path.write_bytes(path.read_bytes()[:-4])
            with self.assertRaises((EOFError, OSError, ValueError)):
                images.read_pfm(path)


if __name__ == "__main__":
    unittest.main()
