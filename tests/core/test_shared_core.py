"""Canonical numerical APIs, historical imports and format boundaries."""

import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts/run")]


class SharedCoreTests(unittest.TestCase):
    def test_legacy_exports_are_the_canonical_functions(self):
        modules = {
            "error_metrics": ["smape", "smape_map", "trmae", "luminance"],
            "covariance_metrics": [
                "relative_covariance_map",
                "temporal_relative_covariance_maps",
            ],
            "sequence_metrics": ["Frame", "SequenceRun", "analyze_sequence"],
            "pixel_regions": ["traditional_acceptance", "rank_regions"],
            "neighborhoods": ["disk_offsets", "disk_row_spans"],
        }
        for name, exports in modules.items():
            canonical = importlib.import_module("metrics." + name)
            old = importlib.import_module("experiment." + name)
            for export in exports:
                self.assertIs(getattr(old, export), getattr(canonical, export))
        old = importlib.import_module("experiment.images")
        canonical = importlib.import_module("image_io.images")
        self.assertIs(old.read_pfm, canonical.read_pfm)
        self.assertIs(old.preview_rgb, canonical.preview_rgb)

    def test_canonical_imports_do_not_load_renderer_or_legacy_packages(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        code = "import sys; from metrics import sequence_metrics; from image_io import images; assert not any(n.startswith(('experiment', 'rtxdi_', 'falcor', 'scripts.')) for n in sys.modules)"
        with tempfile.TemporaryDirectory() as d:
            child = subprocess.run(
                [sys.executable, "-B", "-c", code],
                cwd=d,
                env=env,
                capture_output=True,
                text=True,
            )
        self.assertEqual(child.returncode, 0, child.stderr)

    def test_unified_image_loader_preserves_black_and_negative_hdr(self):
        from image_io.images import read_image, write_pfm
        import OpenEXR

        rgb = np.array([[[0.0, 0.0, 0.0], [-1.0, 2.0, 4.0]]], dtype=np.float32)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_pfm(root / "fixture.pfm.gz", rgb)
            OpenEXR.File({}, {"RGB": rgb}).write(str(root / "fixture.exr"))
            for suffix in ("pfm.gz", "exr"):
                np.testing.assert_array_equal(
                    read_image(root / ("fixture." + suffix)), rgb
                )
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                read_image(root / "display.png")

    def test_exr_storage_requirement_is_separate_from_smoke_nonblack_check(self):
        from image_io.exr import read_exr
        import OpenEXR

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "black.exr"
            OpenEXR.File({}, {"RGB": np.zeros((2, 3, 3), dtype=np.float32)}).write(
                str(path)
            )
            self.assertEqual(read_exr(path, require_float32=True).dtype, np.float32)
            OpenEXR.File({}, {"RGB": np.zeros((2, 3, 3), dtype=np.float16)}).write(
                str(path)
            )
            self.assertEqual(read_exr(path).shape, (2, 3, 3))
            with self.assertRaisesRegex(ValueError, "FLOAT32"):
                read_exr(path, require_float32=True)

    def test_new_shared_inputs_participate_in_source_fingerprints(self):
        from records.provenance import shared_source_hashes

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "src/metrics/example.py"
            source.parent.mkdir(parents=True)
            source.write_text("x = 1\n")
            (root / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")
            before = shared_source_hashes(root)
            self.assertEqual(set(before), {"src/metrics/example.py", "pyproject.toml"})
            source.write_text("x = 2\n")
            self.assertNotEqual(shared_source_hashes(root), before)

    def test_installed_source_inventory_excludes_unrelated_packages(self):
        from records import provenance

        with tempfile.TemporaryDirectory() as d:
            site_packages = Path(d)
            expected = {}
            for package in ("analysis", "backends", "image_io", "metrics", "records"):
                source = site_packages / package / "__init__.py"
                source.parent.mkdir()
                source.write_text(f"PACKAGE = {package!r}\n")
                expected[f"{package}/__init__.py"] = provenance.sha256(source)
            nested = site_packages / "backends/rtxdi/records.py"
            nested.parent.mkdir()
            nested.write_text("SCHEMA = 1\n")
            expected["backends/rtxdi/records.py"] = provenance.sha256(nested)
            unrelated = site_packages / "unrelated/library.py"
            unrelated.parent.mkdir()
            unrelated.write_text("VERSION = 1\n")
            (site_packages / "stray.py").write_text("VALUE = 1\n")
            with patch.object(
                provenance, "__file__", str(site_packages / "records/provenance.py")
            ):
                before = provenance.package_source_hashes()
                self.assertEqual(before, expected)
                unrelated.write_text("VERSION = 2\n")
                (site_packages / "new_unrelated.py").write_text("VALUE = 2\n")
                self.assertEqual(provenance.package_source_hashes(), before)
                nested.write_text("SCHEMA = 2\n")
                after = provenance.package_source_hashes()
                self.assertEqual(set(after), set(before))
                self.assertNotEqual(
                    after["backends/rtxdi/records.py"],
                    before["backends/rtxdi/records.py"],
                )


if __name__ == "__main__":
    unittest.main()
