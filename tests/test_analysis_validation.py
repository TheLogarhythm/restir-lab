"""Regression coverage for comparable analysis controls."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))
sys.path.insert(0, str(ROOT))
from experiment.artifacts import save_json, write_pfm
from experiment.config import make_config, load_definition
from experiment.scenes import load_scene
from rtxdi_common import sha


class AnalysisValidationTests(unittest.TestCase):
    def test_pdf_toggle_is_allowed_but_other_controls_stay_matched(self):
        report = importlib.import_module("scripts.analysis.di_reuse")
        from copy import deepcopy
        config = make_config(load_scene("cornell-box"), load_definition(), "combined", "static")
        capture = {"config": config, "manifest": {"gpu": "gpu", "build": {"shader": "same"}},
                   "frame": {"frame": 1}, "key": "same-pose"}
        pdf = deepcopy(capture)
        pdf["config"]["definition"]["pdf_similarity"] = True
        report.validate_comparison([capture, pdf])
        for field in ("budget", "build", "coverage", "pose"):
            changed = deepcopy(pdf)
            if field == "budget":
                changed["config"]["definition"]["spatial_neighbors"] += 1
            elif field == "build":
                changed["manifest"]["build"]["shader"] = "different"
            elif field == "coverage":
                changed["config"]["seed"] += 1
            else:
                changed["key"] = "different-pose"
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "Compared"):
                report.validate_comparison([capture, changed])

    def test_analysis_rejects_cross_mode_budget_or_hardware_changes(self):
        report = importlib.import_module("scripts.analysis.di_reuse")
        for changed in ("budget", "gpu", "shader", "coverage"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                for mode in ("initial", "combined"):
                    directory = root / mode
                    directory.mkdir()
                    config = make_config(load_scene("cornell-box"), load_definition(), mode, "static", resolution=[2, 2])
                    if mode == "combined" and changed == "coverage":
                        config["seed"] = 2
                    config["frames"] = config["frames"][:1]
                    if mode == "combined" and changed == "budget":
                        config["definition"]["initial_local_candidates"] += 1
                    save_json(directory / "config.json", config)
                    save_json(directory / "manifest.json", {"status": "completed", "config_sha256": sha(directory / "config.json"),
                        "scene": {"sha256": "assets"}, "gpu": "other" if mode == "combined" and changed == "gpu" else "gpu",
                        "build": {"executable_sha256": "exe", "shader_sha256": {"shader": "other" if mode == "combined" and changed == "shader" else "shader"}}})
                    write_pfm(directory / "frame-0001.pfm.gz", np.ones((2, 2, 3)))
                with mock.patch.object(sys, "argv", ["analysis", "--baseline", str(root), "--references", str(root / "missing")]):
                    with self.assertRaisesRegex(ValueError, "Compared"):
                        report.main()
                self.assertFalse((root / "analysis").exists())

    def test_timing_validation_rejects_missing_duplicate_and_invalid_values(self):
        report = importlib.import_module("scripts.analysis.di_reuse")
        config = make_config(load_scene("cornell-box"), load_definition(), "initial", "static", resolution=[2, 2])
        config["frames"] = config["frames"][:2]
        invalid = ["1,1\n", "1,1\n1,2\n2,3\n", "1,nan\n2,1\n",
                   "1,-1\n2,1\n", "1,inf\n2,1\n", "1,1\n3,1\n"]
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            for body in invalid:
                with self.subTest(body=body):
                    (directory / "timings.csv").write_text("frame,gpu_ms\n" + body)
                    with self.assertRaises(ValueError):
                        report.read_timings(directory, config)
            (directory / "timings.csv").write_text("frame,gpu_ms\n1,2\n2,4\n")
            frames, phases = report.read_timings(directory, config)
            self.assertEqual(set(frames), {1, 2})
            self.assertEqual(phases[0]["gpu_ms"], 3.)
            self.assertEqual(phases[0]["frames"], 2)

if __name__ == "__main__":
    unittest.main()
