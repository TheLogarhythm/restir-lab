import os
import sys
from pathlib import Path
import tempfile
import unittest

import numpy as np
import OpenEXR

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from image_io.exr import read_exr
from image_io.reference_average import average_seed_exrs
from image_io.reference_average_16 import average_sixteen_seed_exrs


class ReferenceAverageTests(unittest.TestCase):
    AVERAGERS = ((8, average_seed_exrs), (16, average_sixteen_seed_exrs))

    def write(self, path, array):
        OpenEXR.File({}, {'RGB': array}).write(str(path))

    def test_independent_images_are_averaged_without_modifying_inputs(self):
        for count, average in self.AVERAGERS:
            with self.subTest(seed_count=count):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    inputs = [root / f'{i}.exr' for i in range(count)]
                    for i, path in enumerate(inputs):
                        self.write(path, np.full((2, 3, 3), i - 2, dtype=np.float32))
                    before = [p.read_bytes() for p in inputs]
                    output = root / 'mean.exr'
                    average(inputs, output)
                    result = read_exr(output, require_float32=True)
                    np.testing.assert_array_equal(result, np.full((2, 3, 3), (count - 1) / 2 - 2, dtype=np.float32))
                    self.assertEqual(before, [p.read_bytes() for p in inputs])

    def test_requires_distinct_inputs_and_never_overwrites(self):
        for count, average in self.AVERAGERS:
            with self.subTest(seed_count=count):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    inputs = [root / f'{i}.exr' for i in range(count)]
                    for path in inputs:
                        self.write(path, np.zeros((2, 2, 3), dtype=np.float32))
                    with self.assertRaises(ValueError):
                        average(inputs[:-1], root / 'out.exr')
                    with self.assertRaises(ValueError):
                        average(inputs[:-1] + inputs[:1], root / 'out.exr')
                    with self.assertRaises((ValueError, FileExistsError)):
                        average(inputs, inputs[0])
                    out = root / 'out.exr'
                    out.write_bytes(b'preserve')
                    with self.assertRaises(FileExistsError):
                        average(inputs, out)
                    self.assertEqual(out.read_bytes(), b'preserve')

    def test_accumulates_in_float64_before_rounding_the_mean(self):
        for count, average in self.AVERAGERS:
            with self.subTest(seed_count=count), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                values = [2**30, 1, -(2**30)] + [0] * (count - 3)
                inputs = [root / f'{index}.exr' for index in range(count)]
                for path, value in zip(inputs, values):
                    self.write(path, np.full((1,1,3), value, dtype=np.float32))
                output = average(inputs, root / 'mean.exr')
                np.testing.assert_array_equal(read_exr(output), np.full((1,1,3), 1/count, dtype=np.float32))

    def test_rejects_hardlinked_seed_aliases(self):
        for count, average in self.AVERAGERS:
            with self.subTest(seed_count=count), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                original, alias = root / 'seed.exr', root / 'alias.exr'
                self.write(original, np.zeros((1,1,3), dtype=np.float32))
                os.link(original, alias)
                with self.assertRaises(ValueError):
                    average([original, alias] + [original] * (count - 2), root / 'mean.exr')
                self.assertFalse((root / 'mean.exr').exists())

    def test_rejects_mismatched_shapes_and_nonfinite_or_half_input(self):
        for count, average in self.AVERAGERS:
            with self.subTest(seed_count=count):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    inputs = [root / f'{i}.exr' for i in range(count)]
                    for path in inputs:
                        self.write(path, np.zeros((2, 2, 3), dtype=np.float32))
                    for array in (np.zeros((1, 2, 3), dtype=np.float32),
                                  np.full((2, 2, 3), np.nan, dtype=np.float32),
                                  np.zeros((2, 2, 3), dtype=np.float16)):
                        self.write(inputs[-1], array)
                        with self.assertRaises(ValueError):
                            average(inputs, root / 'out.exr')
                        self.assertFalse((root / 'out.exr').exists())


if __name__ == '__main__':
    unittest.main()
