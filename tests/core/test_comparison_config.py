"""Selected groups, protocol boundaries, display configuration and explicit reuse."""
import copy
import unittest
from tests.fixtures.comparison import ROOT
from experiment.comparison_config import load_spec, resolve_configs, validate_spec, validate_approved_budget


def select_groups(spec, selected):
    result = copy.deepcopy(spec)
    result["groups"] = {a:g for a,g in result["groups"].items() if a in selected}
    result["methods"] = {n:m for n,m in result["methods"].items() if m["algorithm"] in selected}
    components = {g["reference"] for g in result["groups"].values()}
    result["references"] = {c:r for c,r in result["references"].items() if c in components}
    return result


class ComparisonConfigTests(unittest.TestCase):
    def test_individual_and_selected_algorithm_groups(self):
        for algorithms in (("DI",),("GI",),("PT",),("GI","PT"),("DI","GI","PT")):
            spec = select_groups(load_spec(),algorithms)
            jobs = resolve_configs(spec)
            self.assertEqual(len(jobs),len(algorithms)*10)
            self.assertEqual({j["algorithm"] for j in jobs},set(algorithms))
            validate_approved_budget(spec)

    def test_general_config_can_change_budget_but_formal_gate_cannot(self):
        spec = select_groups(load_spec(),("GI",))
        spec.update(seeds=[2,3],preview_seed=2,resolution=[32,32])
        spec["acquisition"] = {"protocol":"static","warmup_frames":2,"capture_frames":[3]}
        jobs = resolve_configs(spec)
        self.assertEqual(len(jobs),20)
        for job in jobs:
            self.assertEqual([f["sampling_frame"] for f in job["config"]["frames"]],
                             [job["seed"]*1048576+n for n in range(3)])
        with self.assertRaisesRegex(ValueError,"Unapproved"): validate_approved_budget(spec)

    def test_sequence_is_never_silently_static(self):
        spec = load_spec();spec["acquisition"]["protocol"] = "sequence"
        with self.assertRaisesRegex(ValueError,"not implemented"): resolve_configs(spec)
        spec = load_spec();spec["acquisition"]["capture_frames"] = [40,41]
        with self.assertRaisesRegex(ValueError,"Static"): resolve_configs(spec)

    def test_reference_target_seed_and_coverage_are_explicit(self):
        for mutate in (lambda s:s["groups"]["GI"].update(reference="direct"),
                       lambda s:s["references"].pop("full"),
                       lambda s:s.update(seeds=[1001],preview_seed=1001),
                       lambda s:s["references"]["direct"]["policy"].update(component="full")):
            spec = load_spec();mutate(spec)
            with self.assertRaises(ValueError): validate_spec(spec)

    def test_sources_are_configured_not_coded(self):
        spec = load_spec()
        for row in spec["methods"].values(): row["source"] = {"kind":"render"}
        self.assertEqual(len(resolve_configs(spec)),30)
        for name in ("comparison.py","comparison_config.py","comparison_batch.py"):
            self.assertNotIn("cgns-rejection-1080p",(ROOT / "scripts/run/experiment" / name).read_text())
        self.assertNotIn("legacy_spec",(ROOT / "scripts/run/experiment/comparison_config.py").read_text())

    def test_exposure_does_not_enter_render_config(self):
        spec = load_spec();before = resolve_configs(spec)
        self.assertEqual(spec["display"]["exposure_ev"]["bistro-interior"],5)
        self.assertEqual(spec["display"]["exposure_ev"]["bistro-exterior"],3)
        self.assertEqual(spec["display"]["exposure_ev"]["emerald-square"],6)
        spec["display"]["exposure_ev"] = {v:-2 for v in spec["views"]}
        self.assertEqual(resolve_configs(spec),before)

    def test_invalid_display_or_pair_controls_fail(self):
        for mutate in (lambda s:s["display"]["exposure_ev"].pop("cornell-box"),
                       lambda s:s["display"]["exposure_ev"].update({"cornell-box":float("nan")}),
                       lambda s:s["methods"]["gi-cgns"]["settings"].update(cgns_candidates=16),
                       lambda s:s["methods"]["gi-cgns"]["settings"].update(spatial_radius=64)):
            spec = load_spec();mutate(spec)
            with self.assertRaises(ValueError): validate_spec(spec)

    def test_cgns_constraints_are_not_bypassed_by_algorithm_adaptation(self):
        for algorithm in ("DI","GI","PT"):
            spec = select_groups(load_spec(),(algorithm,))
            spec["reuse_mode"] = "temporal"
            with self.assertRaisesRegex(ValueError,"spatial"): resolve_configs(spec)
            spec["reuse_mode"] = "combined"
            for method in spec["methods"].values(): method["settings"]["cgns_candidates"] = 1
            with self.assertRaisesRegex(ValueError,"at least spatial_neighbors"): resolve_configs(spec)
