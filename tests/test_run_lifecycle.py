"""Failure-path contracts for experiment execution and output handling."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment import runner, artifacts
from experiment.config import make_config, load_definition
from experiment.scenes import load_scene


class RunLifecycleTests(unittest.TestCase):
    def config(self):
        return make_config(load_scene("cornell-box"), load_definition(), "initial", "static", resolution=[2, 2])

    def test_preflight_rejects_build_from_another_renderer_revision(self):
        exe = mock.MagicMock(spec=Path)
        exe.is_file.return_value = True
        exe.with_suffix.return_value.read_text.return_value = json.dumps({
            "renderer_commit": "old", "executable_sha256": "binary",
            "integration_sha256": {}, "shader_sha256": {}})
        with mock.patch.object(runner, "sha", return_value="binary"), \
             mock.patch.object(runner, "query", side_effect=["", "current", ""]):
            with self.assertRaisesRegex(RuntimeError, "revision"):
                runner.preflight({"renderer_commit": "current"}, exe)

    def test_metadata_failure_leaves_failed_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "run"
            with mock.patch.object(runner, "query", side_effect=RuntimeError("metadata failed")):
                with self.assertRaisesRegex(RuntimeError, "metadata failed"):
                    runner.run_one(self.config(), output, {}, {})
            record = json.loads((output / "manifest.json").read_text())
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["stage"], "preparing")
            self.assertIn("metadata failed", record["error"])

    def test_invalid_timings_preserve_raw_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            config = self.config()
            config["frames"] = config["frames"][:1]
            config["diagnostics"] = True
            raw = output / "frame-0001.rgba16f"
            reservoir = output / "frame-0001.reservoir"
            np.ones((2, 2, 4), dtype="<f2").tofile(raw)
            np.zeros((256, 6), dtype="<u4").tofile(reservoir)
            (output / "timings.csv").write_text("frame,gpu_ms\n")
            with self.assertRaisesRegex(RuntimeError, "timings"):
                artifacts.finalize_outputs(output, config)
            self.assertTrue(raw.is_file())
            self.assertTrue(reservoir.is_file())

    def test_late_capture_failure_preserves_all_raw_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            config = self.config()
            config["frames"] = config["frames"][:2]
            for frame in config["frames"]:
                frame["capture"] = True
            config["diagnostics"] = True
            for number in (1, 2):
                np.ones((2, 2, 4), dtype="<f2").tofile(output / f"frame-{number:04d}.rgba16f")
                np.zeros((256, 6), dtype="<u4").tofile(output / f"frame-{number:04d}.reservoir")
            # The later capture fails after the first image and diagnostics converted.
            (output / "frame-0002.rgba16f").write_bytes(b"truncated")
            with mock.patch.object(artifacts, "validate_run_outputs"):
                with self.assertRaises(ValueError):
                    artifacts.finalize_outputs(output, config)
            for number in (1, 2):
                self.assertTrue((output / f"frame-{number:04d}.rgba16f").is_file())
                self.assertTrue((output / f"frame-{number:04d}.reservoir").is_file())
            self.assertFalse((output / "captures.json").exists())

    def test_success_removes_raw_files_after_saving_capture_records(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            config = self.config()
            config["frames"] = config["frames"][:1]
            config["frames"][0]["capture"] = True
            config["diagnostics"] = True
            np.ones((2, 2, 4), dtype="<f2").tofile(output / "frame-0001.rgba16f")
            np.zeros((256, 6), dtype="<u4").tofile(output / "frame-0001.reservoir")
            with mock.patch.object(artifacts, "validate_run_outputs"):
                records = artifacts.finalize_outputs(output, config)
            self.assertEqual(json.loads((output / "captures.json").read_text()), records)
            self.assertTrue((output / "frame-0001.pfm.gz").is_file())
            self.assertTrue((output / "frame-0001.png").is_file())
            self.assertFalse((output / "frame-0001.rgba16f").exists())
            self.assertFalse((output / "frame-0001.reservoir").exists())


if __name__ == "__main__":
    unittest.main()
