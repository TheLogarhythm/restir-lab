"""Reference acceptance must cover dark-region SMAPE as well as RGB RMAE."""
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment.images import write_pfm


class ControlledQualityTests(unittest.TestCase):
    def assessment(self, directory, baseline):
        module = importlib.import_module("experiment.controlled_reference")
        path = directory / "baseline.pfm.gz"
        write_pfm(path, baseline)
        captures = [{"image": path, "config": {"preview": {"exposure_ev": 0}}}]
        return module.ControlledAssessment(captures, .1, lambda p: baseline)

    def test_rmae_pass_cannot_hide_large_percentage_error_in_dark_pixels(self):
        with tempfile.TemporaryDirectory() as folder:
            a = np.ones((2, 2, 3))
            b = a.copy()
            a[0, 0] = 1e-5
            b[0, 0] = 1e-3
            reference = (a + b) / 2
            baseline = reference.copy()
            baseline[1, 1] += .2
            assessment = self.assessment(Path(folder), baseline)
            for samples in (16, 32, 64):
                accepted = assessment.add(samples, [a, b])
            self.assertFalse(accepted)
            checks = assessment.rows[-1]["regions"]["full"]
            self.assertTrue(checks["rmae"]["passed"])
            self.assertFalse(checks["smape"]["passed"])

    def test_requires_two_good_changes_and_preserves_quality_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            reference = np.ones((2, 2, 3))
            assessment = self.assessment(directory, reference * 1.2)
            self.assertFalse(assessment.add(16, [reference, reference]))
            self.assertFalse(assessment.add(32, [reference, reference]))
            self.assertTrue(assessment.add(64, [reference, reference]))
            result = assessment.save(directory)
            self.assertTrue(result["converged"])
            self.assertEqual(result["quality_metrics"], ["rmae", "smape"])
            self.assertEqual(result["required_consecutive_passes"], 2)


if __name__ == "__main__":
    unittest.main()
