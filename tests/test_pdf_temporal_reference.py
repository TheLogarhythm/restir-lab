"""Reference uncertainty must be small in the temporal metric actually reported."""
import copy
import gzip
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment.images import write_pfm
from experiment.reference import rmae


class TemporalReferenceTests(unittest.TestCase):
    def gate(self, captures, references, **kwargs):
        spec = importlib.util.find_spec("experiment.controlled_temporal")
        self.assertIsNotNone(spec, "the temporal reference gate must exist")
        from experiment.controlled_temporal import check_temporal_references
        return check_temporal_references(captures, references, **kwargs)

    def static_assessment(self, captures, references, **kwargs):
        from experiment import controlled_temporal
        self.assertTrue(hasattr(controlled_temporal, "assess_static_reference_differences"),
                        "static paired reference sensitivity must be assessed")
        return controlled_temporal.assess_static_reference_differences(captures, references, **kwargs)

    def static_suite(self, directory, *, shifted=False):
        references = {}
        for name, shift in (("image", 0.), ("previous_image", 0.),
                            ("a", -.125 if shifted else 0.), ("b", .125 if shifted else 0.)):
            path = directory / f"static-{name}.pfm.gz"
            write_pfm(path, np.full((2, 2, 3), 64. + shift))
            references[name] = path
        references = {"static": {"image": references["image"],
            "previous_image": references["previous_image"], "streams": [references["a"], references["b"]]}}
        captures = []
        for seed in (1, 2, 3):
            for method in (False, True):
                path = directory / f"static-{seed}-{method}.pfm.gz"
                level = (63. if method else 65.) if shifted else 62. + 2 * seed + int(method) + 1.
                write_pfm(path, np.full((2, 2, 3), level))
                captures.append({"image": path, "key": "static", "frame": {"frame": 128},
                    "config": {"seed": seed, "definition": {"pdf_similarity": method}}})
        return captures, references

    def test_static_reference_receipt_marks_reference_sensitive_difference_inconclusive(self):
        with tempfile.TemporaryDirectory() as folder:
            captures, references = self.static_suite(Path(folder), shifted=True)
            result = self.static_assessment(captures, references,
                rois=[{"name": "receiver", "x": 0, "y": 0, "width": 1, "height": 1}])
            self.assertTrue(result["passed"])
            for region in ("full", "receiver"):
                metrics = result["regions"][region]["static"]["metrics"]
                self.assertEqual(set(metrics), {"smape", "rmae", "nrmse"})
                difference = metrics["smape"]["paired_difference"]
                self.assertGreater(difference["current"], 0.)
                self.assertLess(difference["variants"]["half_a"], 0.)
                self.assertFalse(difference["direction_resolved"])
                self.assertEqual(difference["state"], "inconclusive")
            json.dumps(result, allow_nan=False)

    def test_static_differences_average_three_matched_seeds_and_use_frame_128(self):
        with tempfile.TemporaryDirectory() as folder:
            captures, references = self.static_suite(Path(folder))
            startup = copy.deepcopy(captures[0])
            startup["frame"]["frame"] = 1
            startup["image"] = Path(folder) / "unused-startup.pfm.gz"
            result = self.static_assessment([startup, *captures], references)
            metrics = result["regions"]["full"]["static"]["metrics"]
            self.assertAlmostEqual(metrics["rmae"]["methods"]["False"]["current"], 3. / 64.)
            self.assertAlmostEqual(metrics["rmae"]["methods"]["True"]["current"], 4. / 64.)
            self.assertAlmostEqual(metrics["rmae"]["paired_difference"]["current"], 1. / 64.)
            self.assertAlmostEqual(metrics["nrmse"]["paired_difference"]["current"], 1. / 64.)
            self.assertTrue(metrics["smape"]["paired_difference"]["direction_resolved"])
            self.assertEqual(metrics["smape"]["paired_difference"]["state"], "resolved")

    def test_static_missing_duplicate_or_unmatched_seeds_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            captures, references = self.static_suite(Path(folder))
            unmatched = copy.deepcopy(captures)
            unmatched[-1]["config"]["seed"] = 4
            for invalid in ([], captures[1:], captures + [captures[0]], unmatched):
                with self.subTest(count=len(invalid)), self.assertRaises(ValueError):
                    self.static_assessment(invalid, references)

    def suite(self, directory, *, seeds=(1,), motion=False, noise=0., previous_shift=0.,
              slopes=None, unique_states=True):
        """Small real PFM sequences with hand-computable RGB gradients."""
        captures, references = [], {}
        slopes = slopes or {seed: (1., 2.) for seed in seeds}
        for frame in range(1, 97):
            state = frame if unique_states else 1
            key = f"state-{state:03d}"
            true = 64. + (frame / 8. if motion else 0.)
            mean = np.full((2, 2, 3), true)
            if key not in references:
                paths = {}
                for name, image in (
                        ("image", mean), ("previous_image", mean + previous_shift * state),
                        ("a", mean + noise * (-1) ** state),
                        ("b", mean - noise * (-1) ** state)):
                    path = directory / f"{key}-{name}.pfm.gz"
                    write_pfm(path, image)
                    paths[name] = path
                references[key] = {"image": paths["image"],
                    "previous_image": paths["previous_image"], "streams": [paths["a"], paths["b"]]}
            for seed in seeds:
                for method in (False, True):
                    path = directory / f"seed-{seed}-{method}-{frame:03d}.pfm.gz"
                    write_pfm(path, mean + slopes[seed][int(method)] * frame / 8.)
                    captures.append({"image": path, "key": key, "frame": {"frame": frame},
                        "config": {"seed": seed, "definition": {"pdf_similarity": method}}})
        return captures, references

    def test_exact_moving_reference_passes_without_treating_motion_as_error(self):
        with tempfile.TemporaryDirectory() as folder:
            captures, references = self.suite(Path(folder), motion=True)
            result = self.gate(captures, references,
                rois=[{"name": "receiver", "x": 0, "y": 1, "width": 1, "height": 1}])
            self.assertTrue(result["passed"])
            self.assertEqual(result["refine_keys"], [])
            self.assertEqual(set(result["regions"]), {"full", "receiver"})
            for phases in result["regions"].values():
                for phase in phases.values():
                    self.assertEqual(phase["reference_gradient_noise"], 0.)
                    self.assertEqual(phase["checkpoint_gradient_change"], 0.)
                    self.assertEqual(phase["method_metric_change"], 0.)
                    self.assertAlmostEqual(phase["methods"]["False"]["current"], .125 / .385)
                    self.assertAlmostEqual(phase["threshold"], .1 * .125 / .385)
            json.dumps(result, allow_nan=False)

    def test_noisy_reference_gradients_fail_even_when_framewise_rmae_is_small(self):
        with tempfile.TemporaryDirectory() as folder:
            captures, references = self.suite(Path(folder), noise=.03125)
            self.assertLess(rmae(np.full((1, 1, 3), 64.03125), np.full((1, 1, 3), 64.)), .001)
            result = self.gate(captures, references)
            phase = result["regions"]["full"]["1-32"]
            self.assertFalse(result["passed"])
            self.assertAlmostEqual(phase["reference_gradient_noise"], 6.25)
            self.assertGreater(phase["reference_gradient_noise"], phase["threshold"])
            self.assertTrue(result["refine_keys"])

    def test_precise_reference_can_still_leave_paired_method_direction_inconclusive(self):
        with tempfile.TemporaryDirectory() as folder:
            captures, references = self.suite(Path(folder), slopes={1: (1., -.9990234375)})
            for frame in range(1, 97):
                for index, path in enumerate(references[f"state-{frame:03d}"]["streams"]):
                    shift = frame / 8192. * (1 if index == 0 else -1)
                    write_pfm(path, np.full((2, 2, 3), 64. + shift))
            result = self.gate(captures, references)
            self.assertTrue(result["passed"])
            difference = result["regions"]["full"]["33-64"]["paired_difference"]
            self.assertLess(difference["current"], 0.)
            self.assertGreater(difference["variants"]["half_a"], 0.)
            self.assertGreater(difference["max_reference_change"], abs(difference["current"]))
            self.assertFalse(difference["direction_resolved"])
            self.assertEqual(difference["state"], "inconclusive")

    def test_exact_method_equality_is_distinguished_from_an_unresolved_direction(self):
        with tempfile.TemporaryDirectory() as folder:
            captures, references = self.suite(Path(folder), slopes={1: (1., 1.)})
            result = self.gate(captures, references)
            difference = result["regions"]["full"]["1-32"]["paired_difference"]
            self.assertEqual(difference["current"], 0.)
            self.assertEqual(difference["max_reference_change"], 0.)
            self.assertFalse(difference["direction_resolved"])
            self.assertEqual(difference["state"], "equal")

    def test_checkpoint_gradient_instability_fails_independently_of_half_stream_noise(self):
        with tempfile.TemporaryDirectory() as folder:
            captures, references = self.suite(Path(folder), previous_shift=.0625)
            result = self.gate(captures, references)
            phase = result["regions"]["full"]["33-64"]
            self.assertFalse(result["passed"])
            self.assertEqual(phase["reference_gradient_noise"], 0.)
            self.assertAlmostEqual(phase["checkpoint_gradient_change"], 6.25)
            self.assertGreater(phase["method_metric_change"], phase["threshold"])

    def test_pairs_are_assigned_to_later_frame_including_both_phase_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            captures, references = self.suite(Path(folder))
            for capture in captures:
                frame = capture["frame"]["frame"]
                # Jumps are confined to pairs 32->33 and 64->65.
                write_pfm(capture["image"], np.full((2, 2, 3), 64. + (frame >= 33) + 2 * (frame >= 65)))
            result = self.gate(list(reversed(captures)), references)
            phases = result["regions"]["full"]
            self.assertEqual([phases[name]["pair_count"] for name in ("1-32", "33-64", "65-96")], [31, 32, 32])
            self.assertEqual(phases["1-32"]["methods"]["False"]["current"], 0.)
            self.assertAlmostEqual(phases["33-64"]["methods"]["False"]["current"], 100. / 32.)
            self.assertAlmostEqual(phases["65-96"]["methods"]["False"]["current"], 200. / 32.)

    def test_independent_seeds_are_summarized_with_equal_weight_per_method(self):
        with tempfile.TemporaryDirectory() as folder:
            captures, references = self.suite(Path(folder), seeds=(1, 2, 3),
                slopes={1: (1., 2.), 2: (3., 4.), 3: (5., 6.)})
            result = self.gate(captures, references)
            phase = result["regions"]["full"]["65-96"]
            self.assertEqual(phase["seed_count"], 3)
            self.assertAlmostEqual(phase["methods"]["False"]["current"], 37.5)
            self.assertAlmostEqual(phase["methods"]["True"]["current"], 50.)
            self.assertEqual([phase["methods"]["False"]["per_seed"][str(seed)]["current"]
                              for seed in (1, 2, 3)], [12.5, 37.5, 62.5])
            self.assertAlmostEqual(phase["threshold"], 3.75)

    def test_temporal_spatial_differences_include_all_32_frames_of_each_phase(self):
        with tempfile.TemporaryDirectory() as folder:
            captures, references = self.suite(Path(folder))
            result = self.gate(captures, references)
            for name, average_frame in (("1-32", 16.5), ("33-64", 48.5), ("65-96", 80.5)):
                phase = result["regions"]["full"][name]
                self.assertEqual(phase.get("frame_count"), 32)
                spatial = phase["metrics"]
                self.assertEqual(set(spatial), {"smape", "rmae", "nrmse"})
                self.assertAlmostEqual(spatial["rmae"]["methods"]["False"]["current"], average_frame / 512.)
                self.assertAlmostEqual(spatial["rmae"]["paired_difference"]["current"], average_frame / 512.)
                self.assertTrue(spatial["smape"]["paired_difference"]["direction_resolved"])

    def test_identical_state_pairs_have_zero_gradient_noise_and_are_not_refined(self):
        with tempfile.TemporaryDirectory() as folder:
            captures, references = self.suite(Path(folder), noise=2., previous_shift=3., unique_states=False)
            result = self.gate(captures, references)
            self.assertTrue(result["passed"])
            self.assertEqual(result["refine_keys"], [])
            for phase in result["regions"]["full"].values():
                self.assertEqual(phase["reference_gradient_noise"], 0.)
                self.assertEqual(phase["checkpoint_gradient_change"], 0.)

    def test_declared_roi_can_fail_even_when_full_image_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            captures, references = self.suite(directory)
            for capture in captures:
                frame = capture["frame"]["frame"]
                method = int(capture["config"]["definition"]["pdf_similarity"])
                write_pfm(capture["image"], np.full((8, 8, 3), 64. + (method + 1) * frame / 8.))
            for frame in range(1, 97):
                ref = references[f"state-{frame:03d}"]
                for path in (ref["image"], ref["previous_image"]):
                    write_pfm(path, np.full((8, 8, 3), 64.))
                for index, path in enumerate(ref["streams"]):
                    image = np.full((8, 8, 3), 64.)
                    image[0, 0] += (.0078125 if index == 0 else -.0078125) * (-1) ** frame
                    write_pfm(path, image)
            result = self.gate(captures, references,
                rois=[{"name": "edge", "x": 0, "y": 0, "width": 1, "height": 1}])
            self.assertFalse(result["passed"])
            self.assertTrue(result["regions"]["full"]["33-64"]["passed"])
            self.assertFalse(result["regions"]["edge"]["33-64"]["passed"])

    def test_frame_zero_missing_duplicate_and_misaligned_frames_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            captures, references = self.suite(Path(folder))
            variants = []
            zero = copy.deepcopy(captures)
            zero[0]["frame"]["frame"] = 0
            variants.extend((zero, captures[1:], captures + [captures[0]]))
            wrong_key = copy.deepcopy(captures)
            wrong_key[1]["key"] = "state-002"
            variants.append(wrong_key)
            for invalid in variants:
                with self.subTest(frames=len(invalid)), self.assertRaises(ValueError):
                    self.gate(invalid, references)

    def test_missing_reference_checkpoint_and_stream_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            captures, references = self.suite(Path(folder))
            missing = copy.deepcopy(references)
            del missing["state-001"]
            checkpoint = copy.deepcopy(references)
            del checkpoint["state-001"]["previous_image"]
            streams = copy.deepcopy(references)
            streams["state-001"]["streams"] = streams["state-001"]["streams"][:1]
            for invalid in (missing, checkpoint, streams):
                with self.assertRaises(ValueError):
                    self.gate(captures, invalid)

    def test_invalid_ratio_roi_shape_and_nonfinite_images_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            captures, references = self.suite(Path(folder))
            for ratio in (0., 1., -1., float("nan"), float("inf"), True):
                with self.subTest(ratio=ratio), self.assertRaises(ValueError):
                    self.gate(captures, references, ratio=ratio)
            for roi in ({"name": "full", "x": 0, "y": 0, "width": 1, "height": 1},
                        {"name": "outside", "x": 1, "y": 0, "width": 2, "height": 1},
                        {"name": "fraction", "x": 0., "y": 0, "width": 1, "height": 1}):
                with self.subTest(roi=roi), self.assertRaises(ValueError):
                    self.gate(captures, references, rois=[roi])
            write_pfm(captures[0]["image"], np.ones((1, 2, 3)))
            with self.assertRaises(ValueError):
                self.gate(captures, references)
            path = captures[0]["image"]
            with gzip.open(path, "wb") as stream:
                stream.write(b"PF\n2 2\n-1.0\n" + np.full((2, 2, 3), np.nan, dtype="<f4").tobytes())
            with self.assertRaises(ValueError):
                self.gate(captures, references)


if __name__ == "__main__":
    unittest.main()
