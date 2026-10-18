"""Protect the pilot gate and the five retained experiment directories."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))


class ControlledWorkerTests(unittest.TestCase):
    def worker(self):
        spec = importlib.util.spec_from_file_location("pdf_worker", ROOT / "scripts/run/rtxdi_pdf_controlled.py")
        self.assertTrue(spec.origin and Path(spec.origin).is_file(), "Controlled worker is missing")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_formal_gate_rejects_missing_failed_or_different_build_pilot(self):
        worker = self.worker()
        build = {"executable_sha256": "exe", "shader_sha256": {"shader": "sha"}}
        reference = {"executable_sha256": "reference"}
        for receipt in ({}, {"passed": False}, {"passed": True, "matrix_sha256": "matrix", "build": {}}):
            with self.subTest(receipt=receipt), self.assertRaises(ValueError):
                worker.validate_pilot_gate(receipt, build, "matrix", reference)
        receipt = {"passed": True, "matrix_sha256": "matrix", "build": build}
        with self.assertRaises(ValueError):
            worker.validate_pilot_gate(receipt, build, "matrix", reference)
        receipt.update(validation_version=2, lighting_influence={"passed": True}, reference_build=reference)
        worker.validate_pilot_gate(receipt, build, "matrix", reference)

    def test_lighting_gate_rejects_reference_noise_and_accepts_receiver_signal(self):
        import numpy as np
        worker = self.worker()
        base = np.ones((2, 2, 3))
        rois = [{"name": "receiver", "x": 0, "y": 0, "width": 2, "height": 2}]
        def record(mean, noise):
            return {"image": mean, "previous_image": mean,
                    "streams": [mean + noise, mean - noise]}
        noisy = worker.lighting_influence(record(base, .1), record(base + .001, .1), rois,
                                          load_image=lambda image: image)
        self.assertFalse(noisy["passed"])
        signal = worker.lighting_influence(record(base, .001), record(base + .2, .001), rois,
                                           load_image=lambda image: image)
        self.assertTrue(signal["passed"])

    def test_pilot_from_previous_reference_estimator_cannot_release_formal_runs(self):
        worker = self.worker()
        build = {"executable_sha256": "pdf"}
        current = {"shader_sha256": {"ShadeSamples": "corrected-support"}}
        receipt = {"passed": True, "matrix_sha256": "matrix", "build": build,
                   "reference_build": {"shader_sha256": {"ShadeSamples": "legacy-support"}},
                   "validation_version": 2, "lighting_influence": {"passed": True}}
        with self.assertRaises(ValueError):
            worker.validate_pilot_gate(receipt, build, "matrix", current)
        receipt["reference_build"] = current
        worker.validate_pilot_gate(receipt, build, "matrix", current)

    def test_output_cannot_target_retained_runs_or_escape_runs(self):
        worker = self.worker()
        for name in ("di-3scenes-reference", "zero-day-di-seed1", "../outside"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                worker.suite_path(name)
        self.assertEqual(worker.suite_path("pdf-controlled-20261018"), ROOT / "runs/pdf-controlled-20261018")

    def test_reference_refinement_regenerates_figures_without_overwriting_previous(self):
        worker = self.worker()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runs = {}
            for method in ("off", "on"):
                directory = root / method
                directory.mkdir()
                for name in ("manifest.json", "config.json", "captures.json", "timings.csv"):
                    (directory / name).write_text("{}")
                runs[method + "_dir"] = directory
            reference = root / "reference.pfm.gz"
            reference.write_bytes(b"first reference")
            reports = [{"runs": [runs], "references": {1: reference}}]
            instance = worker.ControlledExperiment.__new__(worker.ControlledExperiment)
            instance.root, instance.state, instance.state_path = root, {}, root / "state.json"
            from experiment.controlled_budget import ExperimentBudget
            instance.budget = ExperimentBudget(root)
            def generate(path):
                path.mkdir()
                (path / "figure.txt").write_bytes(reference.read_bytes())
            first = instance.product(root / "artifacts", reports, generate)
            reference.write_bytes(b"refined reference")
            second = instance.product(root / "artifacts", reports, generate)
            self.assertNotEqual(first, second)
            self.assertEqual((first / "figure.txt").read_bytes(), b"first reference")
            self.assertEqual((second / "figure.txt").read_bytes(), b"refined reference")
            self.assertEqual(instance.product(root / "artifacts", reports, generate), second)
            saved = json.loads(instance.state_path.read_text())
            self.assertEqual(saved["products"]["artifacts"], second.name)


if __name__ == "__main__":
    unittest.main()
