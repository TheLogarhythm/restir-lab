"""Contracts for controlled configurations and scene-linear export."""
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

class ExperimentArtifactTests(unittest.TestCase):
    def setUp(self):
        self.lab = importlib.import_module("experiment.artifacts")
        self.config = importlib.import_module("experiment.config")
        self.runner = importlib.import_module("experiment.runner")
        self.scene = importlib.import_module("experiment.scenes").load_scene("cornell-box")

    def make_config(self, mode, scenario, seed, resolution=None):
        return self.config.make_config(self.scene, self.config.load_definition(), mode, scenario, seed, resolution)

    def test_initial_mode_matches_upstream_parser(self):
        self.assertEqual(self.config.MODES["initial"], "NONE")

    def test_sampling_budget_reaches_active_nee_mode(self):
        for mode, counter in (("UNIFORM", "numLocalLightUniformSamples"),
                              ("POWER_RIS", "numLocalLightPowerRISSamples")):
            with self.subTest(mode=mode):
                definition = self.config.load_definition()
                definition["initial_local_sampling_mode"] = mode
                definition["initial_local_candidates"] = 17
                config = self.config.make_config(self.scene, definition, "combined", "static")
                args = config["arguments"]
                self.assertEqual(args["restirDI.initialSampling.localLightSamplingMode"], mode)
                self.assertEqual(args["restirDI.initialSampling.numLocalLightSamples"], 17)
                self.assertEqual(args.get("restirDI.neeLocalLightSampling." + counter), 17)

    def test_unsupported_sampling_mode_rejected_before_launch(self):
        definition = self.config.load_definition()
        definition["initial_local_sampling_mode"] = "POWER"
        with self.assertRaisesRegex(ValueError, "initial_local_sampling_mode"):
            self.config.make_config(self.scene, definition, "initial", "static")

    def test_modes_change_only_reuse(self):
        configs = [self.make_config(mode, "static", 7) for mode in self.config.MODES]
        common = []
        for config in configs:
            self.assertEqual(config["width"], 1920)
            self.assertEqual(config["height"], 1080)
            values = dict(config["arguments"])
            values.pop("restirDI.diMode")
            common.append(values)
            self.assertEqual(config["frames"][0]["sampling_frame"], 7 * 1048576)
        self.assertTrue(all(item == common[0] for item in common))

    def test_motion_and_reset_are_frame_driven(self):
        frames = self.make_config("combined", "motion", 1)["frames"]
        self.assertEqual(frames[0]["position"], frames[31]["position"])
        self.assertGreater(frames[32]["position"][0], frames[31]["position"][0])
        self.assertEqual(frames[95]["position"], frames[127]["position"])
        reset = self.make_config("combined", "reset", 1)["frames"]
        self.assertEqual([f["frame"] for f in reset if f["reset"]], [1, 65])
        self.assertEqual(reset[64]["sampling_frame"], 1048576 + 64)

    def test_hdr_preserves_range_orientation_and_preview_is_fixed(self):
        rgb = np.array([[[0, .5, 4], [1, 2, 8]],
                        [[3, .25, 0], [0, 0, 0]]], dtype=np.float32)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.pfm"
            self.lab.write_pfm(path, rgb)
            with path.open("rb") as source:
                self.assertEqual(source.readline(), b"PF\n")
                self.assertEqual(source.readline(), b"2 2\n")
                self.assertEqual(source.readline(), b"-1.0\n")
                actual = np.frombuffer(source.read(), "<f4").reshape(2, 2, 3)[::-1]
            np.testing.assert_array_equal(rgb, actual)
        preview = self.lab.preview_rgb(rgb)
        brighter = np.concatenate((rgb, rgb * 10), axis=0)
        np.testing.assert_array_equal(preview, self.lab.preview_rgb(brighter)[:2])
        self.assertEqual(int(preview[0, 1, 0]), 188)

    def test_reservoir_statistics_exclude_tile_padding(self):
        # Width 17 crosses a 16x16 tile boundary; padding must not count.
        data = np.zeros((512, 6), dtype="<u4")
        data[:, 2] = 100 << 18
        data[:16, 0] = 1
        data[:16, 2] = 2 << 18
        data[256, 0] = 1
        data[256, 2] = 4 << 18
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reservoir.bin"
            data.tofile(path)
            stats = self.lab.reservoir_stats(path, 17, 1)
        self.assertEqual(stats["M_max_valid"], 4)
        self.assertAlmostEqual(stats["M_mean_valid"], 36 / 17)
        self.assertEqual(stats["valid_reservoir_fraction"], 1)

    def test_malformed_output_marks_run_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            config = self.make_config("initial", "static", 1)
            with mock.patch.object(self.runner.platform, "platform", return_value="test"), \
                 mock.patch.object(self.runner, "query", return_value="test"), \
                 mock.patch.object(self.runner.subprocess, "run", return_value=mock.Mock(returncode=0)), \
                 mock.patch.object(self.runner, "finalize_outputs", side_effect=KeyError("missing output field")):
                with self.assertRaises(KeyError):
                    self.runner.run_one(config, output, {}, {})
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["stage"], "finalizing")

    def test_invalid_run_parameters_rejected(self):
        for seed in [-1, 4096]:
            with self.assertRaises(ValueError):
                self.make_config("initial", "static", seed)
        with self.assertRaises(ValueError):
            self.make_config("initial", "static", 1, (0, 1080))

if __name__ == "__main__":
    unittest.main()
