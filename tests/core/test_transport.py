"""Transport identity and exact path-sample accounting, independent of a GPU."""
import copy
import importlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts/run")]


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module("experiment.transport")
        from experiment.comparison_config import load_spec, resolve_configs, DI_SPEC
        self.config = resolve_configs(load_spec(DI_SPEC))[0]["config"]
        self.frame = self.config["frames"][-1]

    def target(self, component="direct", config=None):
        return self.api.target(config or self.config, self.frame, "a" * 64, component)

    def test_target_separates_transport_from_estimator(self):
        changed = copy.deepcopy(self.config)
        changed["definition"].update(cgns=True, max_history_length=7, renderer_commit="b" * 40)
        changed["arguments"]["restirDI.spatialResampling.numSamples"] = 2
        self.assertEqual(self.target(), self.target(config=changed))
        self.assertNotEqual(self.api.target_key(self.target()), self.api.target_key(self.target("full")))
        self.assertEqual(self.target("full")["transport"]["max_surface_scattering"], 2)

    def test_target_changes_with_actual_scene_and_pixel_controls(self):
        for field, value in (("rendering.pixelJitter", 1), ("gbuffer.transparent", 0)):
            changed = copy.deepcopy(self.config)
            changed["arguments"][field] = value
            with self.subTest(field=field):
                self.assertNotEqual(self.target(), self.target(config=changed))
        with self.assertRaises(ValueError):
            self.target("indirect-only")

    def test_contract_requires_all_semantic_fields_and_no_estimator_fields(self):
        profile = self.api.profile("full")
        self.api.validate_profile(profile)
        for field in ("max_surface_scattering", "delta_paths", "glass", "secondary_material", "pixel_filter"):
            changed = copy.deepcopy(profile)
            del changed[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.api.validate_profile(changed)
        profile["build"] = "anything"
        with self.assertRaises(ValueError):
            self.api.validate_profile(profile)

    def test_exact_sample_indices_resume_without_overlap(self):
        whole = self.api.path_sample_schedule(1001, 8192)
        first = self.api.path_sample_schedule(1001, 4096)
        second = self.api.path_sample_schedule(1001, 8192, completed_spp=4096)
        self.assertEqual(len(whole), 8192)
        self.assertEqual(whole, first + second)
        self.assertEqual(second[0]["sample_index"], 4096)
        self.assertEqual(second[-1]["completed_spp"], 8192)
        self.assertTrue(set(x["sampling_frame"] for x in whole).isdisjoint(
            x["sampling_frame"] for x in self.api.path_sample_schedule(1, 8192)))
        for seed, spp, previous in ((True, 16, 0), (4096, 16, 0), (1, 16, 16),
                                    (1, 16, -1), (1, 16.0, 0), (1, 1048577, 0)):
            with self.subTest(values=(seed, spp, previous)), self.assertRaises(ValueError):
                self.api.path_sample_schedule(seed, spp, completed_spp=previous)

    def test_indirect_pair_has_only_cgns_toggle_difference(self):
        for algorithm, mode in (("GI", "RESTIRGI"), ("PT", "RESTIRPT")):
            a = self.api.method_config(self.config, algorithm, False)
            b = self.api.method_config(self.config, algorithm, True)
            self.assertEqual(a["arguments"]["lighting.indirectMode"], mode)
            self.assertFalse(a["definition"]["cgns"])
            self.assertFalse(b["definition"]["cgns"])
            b["transport_method"]["cgns"] = False
            self.assertEqual(a, b)
            self.assertEqual(a["transport"]["max_surface_scattering"], 2)
            if algorithm == "PT":
                self.assertEqual(a["arguments"]["restirPT.initialSampling.maxBounceDepth"], 3)
                self.assertEqual(a["arguments"]["restirPT.hybridShift.maxBounceDepth"], 3)
        self.assertEqual(self.api.method_config(self.config, "DI", False), self.config)
        with self.assertRaises(ValueError):
            self.api.method_config(self.config, "BDPT", False)

    def test_observed_transport_settings_are_required_and_checked(self):
        for algorithm in ("GI", "PT"):
            config = self.api.method_config(self.config, algorithm, True)
            actual = self.api.expected_controls(config)
            actual["gs"]["samplingRadius"] = 32.0  # Native JSON serializes this as float.
            self.api.validate_controls(config, actual)
            for group, field in (("gs", "pad1"), ("nee", "numLocalLightSamples"),
                                 ("path", "extraMirrorBounceBudget"), ("path", "minimumPathThroughput")):
                broken = copy.deepcopy(actual)
                broken[group][field] += 1
                with self.subTest(algorithm=algorithm, field=field), self.assertRaises(RuntimeError):
                    self.api.validate_controls(config, broken)
            with self.assertRaises(RuntimeError):
                self.api.validate_controls(config, {})
            config["transport_method"]["radiance_clamp"] = True
            with self.assertRaises(ValueError):
                self.api.expected_controls(config)


if __name__ == "__main__":
    unittest.main()
