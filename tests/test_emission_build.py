"""Verify the temporary Donut emission adapter restores source after build errors."""
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/run'))
from rtxdi_emission import emission_support

class EmissionBuildTests(unittest.TestCase):
    def test_extension_applied_and_source_restored_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'GltfImporter.cpp'
            original = b'        matinfo->emissiveColor = material.emissive_factor;\r\n'
            source.write_bytes(original)
            with self.assertRaisesRegex(RuntimeError, 'compile failed'):
                with emission_support(source):
                    self.assertIn('material.emissive_strength.emissive_strength', source.read_text())
                    raise RuntimeError('compile failed')
            self.assertEqual(source.read_bytes(), original)

    def test_unknown_source_is_not_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'GltfImporter.cpp'
            source.write_bytes(b'unknown version')
            with self.assertRaisesRegex(RuntimeError, 'Unexpected'):
                with emission_support(source): pass
            self.assertEqual(source.read_bytes(), b'unknown version')
