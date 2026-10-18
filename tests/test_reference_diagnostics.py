"""Safe component probes and independent-stream radiance diagnostics."""
import copy
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment.config import load_definition, make_config
from experiment.scenes import load_scene
from experiment.reference import target
from experiment import reference_diagnostics as diagnostics


class ProbeConfigTests(unittest.TestCase):
    def base(self):
        return make_config(load_scene("bistro"), load_definition(), "combined", "static")

    def test_component_counts_override_renderer_and_nee_consistently(self):
        base = self.base()
        for component, counts in (("zero", (0, 0, 0)), ("local", (64, 0, 0)),
                                  ("local_environment", (64, 64, 0)), ("allocation", (64, 8, 4))):
            with self.subTest(component=component):
                config = diagnostics.make_probe_config(base, base["frames"][0], 8192, 1001, component)
                args, definition = config["arguments"], config["definition"]
                for name, value in zip(("local", "environment", "infinite"), counts):
                    self.assertEqual(definition[f"initial_{name}_candidates"], value)
                for name, value in zip(("LocalLight", "Environment", "InfiniteLight"), counts):
                    self.assertEqual(args[f"restirDI.initialSampling.num{name}Samples"], value)
                self.assertEqual(args["restirDI.neeLocalLightSampling.numLocalLightPowerRISSamples"], counts[0])
                self.assertEqual(args["restirDI.initialSampling.numBrdfSamples"], 0)
                self.assertEqual(args["restirDI.initialSampling.enableInitialVisibility"], 1)
                self.assertEqual(args["restirDI.shading.enableFinalVisibility"], 1)
                self.assertTrue(config["reference"]["diagnostic_only"])
                self.assertEqual(config["reference"]["component"], component)
                self.assertEqual(config["reference"]["class_counts"], dict(zip(("local", "environment", "infinite"), counts)))
                self.assertNotIn("resume_image", config["reference"])
                self.assertNotIn("resume_batches", config["reference"])

    def test_frozen_target_rng_and_input_are_preserved(self):
        base = self.base()
        pose = copy.deepcopy(base["frames"][17])
        pose.update(lighting={"material": "pink", "emissive_intensity_multiplier": 1.5},
                    logical_time_seconds=1.25)
        original = copy.deepcopy(base)
        for component in ("local_environment", "allocation"):
            with self.subTest(component=component):
                config = diagnostics.make_probe_config(base, pose, 8192, 2001, component)
                self.assertEqual((config["width"], config["height"]), (base["width"], base["height"]))
                self.assertEqual(len(config["frames"]), 128)
                self.assertEqual([f["frame"] for f in config["frames"] if f["capture"]], [128])
                self.assertEqual([f["sampling_frame"] for f in config["frames"]],
                                 list(range(2001 * 1048576, 2001 * 1048576 + 128)))
                for frame in config["frames"]:
                    self.assertEqual(frame["logical_time_seconds"], 1.25)
                    self.assertEqual(target(config, frame, "assets"), target(base, pose, "assets"))
        self.assertEqual(base, original)
        self.assertEqual(config["reference"]["checkpoints"], [8192])

    def test_zero_probe_captures_two_batches_without_changing_nominal_schedule(self):
        base = self.base()
        config = diagnostics.make_probe_config(base, base["frames"][0], 8192, 1001, "zero")
        self.assertEqual(config["reference"]["checkpoints"], [64, 128])
        self.assertEqual(config["reference"]["batch_samples_per_light_class"], 64)
        self.assertEqual([f["frame"] for f in config["frames"]], [1, 2])
        self.assertTrue(all(f["capture"] for f in config["frames"]))

    def test_invalid_component_or_sample_count_is_rejected(self):
        base = self.base()
        for component, samples in (("sun", 8192), ("local", 64), ("local", 129),
                                   ("local", True), ("local", 128.0)):
            with self.subTest(component=component, samples=samples), self.assertRaises(ValueError):
                diagnostics.make_probe_config(base, base["frames"][0], samples, 1001, component)


class PrefixDiagnosticsTests(unittest.TestCase):
    def arrays(self):
        constant = np.ones((2, 2, 3), dtype=np.float32)
        return constant, constant.copy(), {1: constant * 3, 2: constant * 5}, {
            1: constant * 6, 2: constant * 10}, {1: constant * 10, 2: constant * 18}

    def test_prefix_residuals_use_shared_full_energy_and_half_stream_difference(self):
        result = diagnostics.analyze_prefixes(*self.arrays())
        self.assertEqual(result["full_reference_mean_absolute_rgb"], 14.)
        self.assertAlmostEqual(result["prefixes"]["local"]["half_stream_rmae"], 1 / 14)
        self.assertAlmostEqual(result["components"]["environment"]["half_stream_rmae"], 1 / 14)
        self.assertAlmostEqual(result["components"]["infinite"]["half_stream_rmae"], 2 / 14)
        self.assertEqual(result["constant"]["max_absolute_batch_difference"], 0.)

    def test_concentration_detects_one_pixel_and_does_not_normalize_components_to_shares(self):
        z = np.ones((10, 10, 3), dtype=np.float32)
        a, b = z.copy(), z.copy()
        a[7, 3] += 2
        local = {1: a, 2: b}
        # Environment residual cancels the local error exactly.
        le = {1: z * 4, 2: z * 4}
        full = {1: z * 8, 2: z * 8}
        result = diagnostics.analyze_prefixes(z, z, local, le, full)
        self.assertEqual(result["components"]["local"]["top_one_percent_error_fraction"], 1.)
        self.assertEqual(result["components"]["local"]["largest_error_pixel_xy"], [3, 7])
        self.assertGreater(result["components"]["local"]["half_stream_rmae"], 0)
        self.assertGreater(result["components"]["environment"]["half_stream_rmae"], 0)
        self.assertEqual(result["prefixes"]["full"]["half_stream_rmae"], 0)

    def test_invalid_arrays_seed_sets_stochastic_constant_and_blue_sentinel_fail(self):
        arrays = self.arrays()
        cases = []
        wrong = list(arrays)
        wrong[1] = wrong[1] * 2
        cases.append(wrong)
        wrong = list(arrays)
        wrong[2] = {1: arrays[0]}
        cases.append(wrong)
        wrong = list(arrays)
        wrong[4] = {1: arrays[0], 3: arrays[0]}
        cases.append(wrong)
        for value in (np.nan, np.inf):
            wrong = copy.deepcopy(arrays)
            wrong[4][1][0, 0, 0] = value
            cases.append(wrong)
        wrong = copy.deepcopy(arrays)
        wrong[2][1][0, 0] = [0, 0, 1]
        cases.append(wrong)
        wrong = list(arrays)
        wrong[3] = {1: np.ones((1, 2, 3)), 2: np.ones((1, 2, 3))}
        cases.append(wrong)
        for index, wrong in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(ValueError):
                diagnostics.analyze_prefixes(*wrong)

    def test_roi_is_applied_consistently(self):
        arrays = self.arrays()
        result = diagnostics.analyze_prefixes(*arrays, roi=(slice(0, 1), slice(0, 1)))
        self.assertEqual(result["pixels"], 1)
        with self.assertRaises(ValueError):
            diagnostics.analyze_prefixes(*arrays, roi=(slice(0, 0), slice(None)))


if __name__ == "__main__":
    unittest.main()
