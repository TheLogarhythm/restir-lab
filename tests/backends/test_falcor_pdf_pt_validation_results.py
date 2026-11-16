"""Saved FLOAT32 EXRs exercise GPU-result validation without running a renderer."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import OpenEXR

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ("baseline", "normal", "one", "zero", "center", "observe", "native")
DIAGNOSTICS = ("nrdEmission", "nrdDiffuseRadianceHitDist", "nrdSpecularRadianceHitDist", "nrdResidualRadianceHitDist")


def tool(test):
    path = ROOT / "scripts/falcor/pdf_pt_validation_results.py"
    test.assertTrue(path.is_file(), "Saved GPU result validator is missing")
    spec = importlib.util.spec_from_file_location("pdf_pt_results_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_exr(path, pixels):
    pixels = np.asarray(pixels, dtype=np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    OpenEXR.File({}, {"RGBA" if pixels.shape[-1] == 4 else "RGB": pixels}).write(str(path))


def fixture_case(root, profile, seed, *, suffix="", ended="2026-11-14T02:00:00Z"):
    case = Path(root) / "cases" / f"classroom-{profile}-{seed}{suffix}"
    case.mkdir(parents=True)
    artifacts = []
    for frame in (1, 2):
        color = np.ones((2, 3, 3), dtype=np.float32) * (1 + seed / 1000)
        if profile in ("normal", "observe") and frame == 2:
            color += .1
        path = case / f"capture.PathTracer.color.{frame}.exr"
        write_exr(path, color)
        artifacts.append({"frame": frame, "seed": seed + frame - 1,
                          "hdr": path.name, "sha256": sha(path)})
        if profile in ("normal", "baseline"):
            continue
        h = 0 if profile in ("zero", "center") else .5 if profile == "observe" and frame == 2 else 1
        m = 1 + h
        count = 0 if profile == "native" else frame
        emission = np.tile([m, 1, 1, count], (2, 3, 1))
        write_exr(case / f"capture.PathTracer.nrdEmission.{frame}.RGBA.exr", emission)
        if profile == "native":
            continue
        energy = 1 if frame == 1 else 1.5
        moment = np.tile([.25 * energy, 0, 0, energy], (2, 3, 1))
        pair = np.tile([h, h, m, 1], (2, 3, 1))
        audit = np.tile([.2, .3, .5, 1], (2, 3, 1))
        for aov, data in (("nrdDiffuseRadianceHitDist", moment),
                          ("nrdSpecularRadianceHitDist", pair),
                          ("nrdResidualRadianceHitDist", audit)):
            write_exr(case / f"capture.PathTracer.{aov}.{frame}.RGBA.exr", data)
    manifest = {"status": "completed", "scene_id": "classroom", "view_id": "view-a",
                "requested_method": "baseline" if profile == "baseline" else "pdf-similarity",
                "resolution": [3, 2], "capture_frames": [1, 2], "seed_offset": seed,
                "temporal_reuse": True, "ended_utc": ended, "artifacts": artifacts,
                "scene_config_sha256": "scene", "experiment_config_sha256": "experiment",
                "requested_graph_options": {"test": "shared"},
                "pdf_shader_parameters": {"history_limit": 8, "history_decay": .9}}
    if profile != "baseline":
        manifest["pdf_profile"] = profile
    (case / "manifest.json").write_text(json.dumps(manifest), encoding="utf8")
    return case


def fixture(root, seeds=(0, 101), profiles=PROFILES):
    return {(profile, seed): fixture_case(root, profile, seed) for seed in seeds for profile in profiles}


def diagnostic_sidecar(case, profile="observe"):
    artifacts = []
    for output in DIAGNOSTICS:
        for path in sorted(case.glob("capture.PathTracer." + output + ".*.exr")):
            artifacts.append({"frame": int(path.name.split(".")[3]), "output": "PathTracer." + output,
                              "hdr": path.name, "sha256": sha(path)})
    (case / "pdf-diagnostics.json").write_text(json.dumps({"profile": profile, "artifacts": artifacts}))


def change_color_by_one_ulp(case, frame=2):
    path = case / f"capture.PathTracer.color.{frame}.exr"
    with OpenEXR.File(str(path), separate_channels=True) as image:
        pixels = np.stack([image.channels()[name].pixels for name in "RGB"], axis=-1)
    pixels[0, 1, 2] = np.nextafter(pixels[0, 1, 2], np.float32(np.inf))
    write_exr(path, pixels)
    record = json.loads((case / "manifest.json").read_text())
    next(value for value in record["artifacts"] if value["frame"] == frame)["sha256"] = sha(path)
    (case / "manifest.json").write_text(json.dumps(record))


class FalcorPdfPtValidationResultsTests(unittest.TestCase):
    def test_complete_suite_keeps_alpha_and_seed_as_unit_of_replication(self):
        module = tool(self)
        with tempfile.TemporaryDirectory() as temp:
            fixture(temp)
            result = module.analyze(temp)
            self.assertEqual(result["status"], "passed", result)
            self.assertEqual(len(result["comparisons"]), 10)
            self.assertTrue(all(row["status"] == "passed" for row in result["comparisons"]))
            observe = next(row for row in result["cases"] if row["profile"] == "observe")
            self.assertEqual(observe["diagnostics"]["status"], "passed")
            self.assertGreater(observe["diagnostics"]["natural_h"]["fractional_pixels"], 0)
            self.assertGreater(observe["diagnostics"]["history"]["accumulated_pixels"], 0)
            for category in ("primary_nee", "indirect_nee", "bsdf_hit"):
                self.assertGreater(observe["diagnostics"]["initial_contributions"][category]["positive_pixels"], 0)
            natural = next(row for row in result["brightness"] if row["profile"] == "normal")
            self.assertEqual(natural["independent_seed_count"], 2)
            self.assertEqual(natural["captured_frame_count"], 4)
            self.assertAlmostEqual(natural["mean_luminance"], 1.1005, places=6)
            self.assertEqual(result["seed_unit"], "seed_offset; captured frames within each seed are averaged first")

    def test_exact_equality_failure_reports_actual_pixel_and_channel(self):
        module = tool(self)
        with tempfile.TemporaryDirectory() as temp:
            cases = fixture(temp)
            path = cases[("one", 0)] / "capture.PathTracer.color.2.exr"
            color = np.ones((2, 3, 3), dtype=np.float32)
            color[0, 1, 2] = 2
            write_exr(path, color)
            record = json.loads((cases[("one", 0)] / "manifest.json").read_text())
            record["artifacts"][1]["sha256"] = sha(path)
            (cases[("one", 0)] / "manifest.json").write_text(json.dumps(record))
            result = module.analyze(temp)
            pair = next(row for row in result["comparisons"] if row["pair"] == "one_vs_baseline" and row["seed_offset"] == 0)
            self.assertEqual(pair["status"], "failed")
            frame = next(row for row in pair["frames"] if row["frame"] == 2)
            self.assertEqual(frame["color"]["max_abs_location"], {"x": 1, "y": 0, "channel": "B"})
            self.assertEqual(frame["color"]["mismatch_pixels"], 1)
            self.assertEqual(result["status"], "failed")

    def test_missing_rgba_and_missing_case_are_incomplete(self):
        module = tool(self)
        with tempfile.TemporaryDirectory() as temp:
            cases = fixture(temp, profiles=tuple(p for p in PROFILES if p != "center"))
            path = cases[("observe", 0)] / "capture.PathTracer.nrdSpecularRadianceHitDist.2.RGBA.exr"
            write_exr(path, np.ones((2, 3, 3)))
            result = module.analyze(temp)
            self.assertEqual(result["status"], "incomplete")
            self.assertTrue(any("A channel" in issue["detail"] for issue in result["issues"]))
            pair = next(row for row in result["comparisons"] if row["pair"] == "zero_vs_center")
            self.assertEqual(pair["status"], "missing")

    def test_tampering_and_confidence_invariant_failures_are_not_hidden(self):
        module = tool(self)
        with tempfile.TemporaryDirectory() as temp:
            cases = fixture(temp)
            color = cases[("normal", 0)] / "capture.PathTracer.color.1.exr"
            write_exr(color, np.full((2, 3, 3), 4))
            pair = np.tile([.5, .5, 2.5, 1], (2, 3, 1))
            write_exr(cases[("observe", 101)] / "capture.PathTracer.nrdSpecularRadianceHitDist.2.RGBA.exr", pair)
            result = module.analyze(temp)
            self.assertEqual(result["status"], "failed")
            json.dumps(result, allow_nan=False)
            self.assertTrue(any("SHA256" in issue["detail"] for issue in result["issues"]))
            diagnostic = next(row["diagnostics"] for row in result["cases"] if row["profile"] == "observe" and row["seed_offset"] == 101)
            self.assertGreater(diagnostic["invariants"]["confidence_sum"]["violations"], 0)
            self.assertEqual(diagnostic["invariants"]["confidence_sum"]["first_location"], {"frame": 2, "x": 0, "y": 0})

    def test_single_seed_is_descriptive_and_latest_success_supersedes_failure(self):
        module = tool(self)
        with tempfile.TemporaryDirectory() as temp:
            cases = fixture(temp, seeds=(0,))
            old = fixture_case(temp, "one", 0, suffix="-failed", ended="2026-11-14T01:00:00Z")
            record = json.loads((old / "manifest.json").read_text())
            record["status"] = "failed"
            (old / "manifest.json").write_text(json.dumps(record))
            result = module.analyze(temp)
            self.assertEqual(result["status"], "incomplete")
            self.assertEqual(len(result["cases"]), 7)
            self.assertTrue(any(row["reason"] == "superseded_failed_attempt" for row in result["excluded_attempts"]))
            self.assertTrue(any("independent seeds" in row["detail"] for row in result["issues"]))

    def test_empty_root_cli_reports_missing_with_exit_two(self):
        tool(self)
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp) / "report.json"
            run = subprocess.run([sys.executable, "-B", "-m", "scripts.falcor.pdf_pt_validation_results", temp,
                                  "--output", str(report)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
            result = json.loads(report.read_text())
            self.assertEqual(result["status"], "incomplete")
            self.assertEqual(result["cases"], [])

    def test_explicit_plan_requires_diagnostics_only_for_the_planned_seed(self):
        module = tool(self)
        with tempfile.TemporaryDirectory() as temp:
            fixture(temp, seeds=(0,))
            for seed in (64, 128, 192):
                fixture(temp, seeds=(seed,), profiles=("baseline", "normal"))
            bistro = fixture_case(temp, "normal", 0, suffix="-bistro")
            manifest = json.loads((bistro / "manifest.json").read_text())
            manifest["scene_id"] = "bistro-interior"
            (bistro / "manifest.json").write_text(json.dumps(manifest))
            plan = [{"scene_id": "classroom", "view_id": "view-a", "profile": profile, "seed_offset": seed}
                    for seed in (0, 64, 128, 192)
                    for profile in (PROFILES if seed == 0 else ("baseline", "normal"))]
            plan.append({"scene_id": "bistro-interior", "view_id": "view-a", "profile": "normal", "seed_offset": 0})
            result = module.analyze(temp, plan=plan)
            self.assertEqual(result["status"], "passed", result["issues"])
            self.assertEqual(len(result["comparisons"]), 5)
            self.assertEqual(next(row for row in result["brightness"] if row["profile"] == "normal" and row["scene_id"] == "classroom")["independent_seed_count"], 4)

    def test_nonfinite_and_invalid_direction_history_have_locations(self):
        module = tool(self)
        with tempfile.TemporaryDirectory() as temp:
            cases = fixture(temp)
            moment = np.tile([4, 0, 0, 1.5], (2, 3, 1))
            write_exr(cases[("observe", 0)] / "capture.PathTracer.nrdDiffuseRadianceHitDist.2.RGBA.exr", moment)
            color = np.ones((2, 3, 3), dtype=np.float32)
            color[1, 2, 0] = np.inf
            path = cases[("normal", 101)] / "capture.PathTracer.color.2.exr"
            write_exr(path, color)
            manifest = json.loads((cases[("normal", 101)] / "manifest.json").read_text())
            manifest["artifacts"][1]["sha256"] = sha(path)
            (cases[("normal", 101)] / "manifest.json").write_text(json.dumps(manifest))
            result = module.analyze(temp)
            self.assertEqual(result["status"], "failed")
            json.dumps(result, allow_nan=False)
            self.assertTrue(any("Nonfinite EXR" in issue["detail"] and "x=2,y=1" in issue["detail"] for issue in result["issues"]))
            diagnostic = next(row["diagnostics"] for row in result["cases"] if row["profile"] == "observe" and row["seed_offset"] == 0)
            self.assertEqual(diagnostic["invariants"]["moment_vector_bound"]["violations"], 6)

    def test_brightness_refuses_different_seed_sets_and_overlapping_streams(self):
        module = tool(self)
        with tempfile.TemporaryDirectory() as temp:
            fixture_case(temp, "normal", 0)
            fixture_case(temp, "baseline", 101)
            plan = [{"scene_id": "classroom", "view_id": "view-a", "profile": "normal", "seed_offset": 0},
                    {"scene_id": "classroom", "view_id": "view-a", "profile": "baseline", "seed_offset": 101}]
            result = module.analyze(temp, plan=plan, min_seeds=1)
            json.dumps(result, allow_nan=False)
            difference = result["descriptive_method_differences"][0]
            self.assertEqual(difference["status"], "incomplete")
            self.assertIsNone(difference["mean_image_difference"])
            self.assertIsNone(difference["paired_mean_luminance_difference"])
        with tempfile.TemporaryDirectory() as temp:
            fixture(temp, seeds=(0, 1))
            result = module.analyze(temp)
            self.assertEqual(result["status"], "incomplete")
            self.assertTrue(any("Overlapping path seed ranges" in row["detail"] for row in result["issues"]))

    def test_scout_plan_reads_scene_and_view_from_real_view_json(self):
        module = tool(self)
        plan = module.load_plan("scouts")
        bistro = next(row for row in plan if row.get("case_label") == "bistro-interior")
        self.assertEqual((bistro["scene_id"], bistro["view_id"]), ("bistro", "view-a"))
        self.assertEqual(bistro["capture_frames"], [1, 2, 3])
        for row in plan:
            config = ROOT / row["view_config"]
            source = json.loads(config.read_text())
            self.assertEqual((row["scene_id"], row["view_id"]), (source["scene_id"], source["view_id"]))
            self.assertEqual(row["view_config_sha256"], sha(config))

    def test_plan_does_not_substitute_another_view_with_the_same_scene_and_seed(self):
        module = tool(self)
        with tempfile.TemporaryDirectory() as temp:
            case = fixture_case(temp, "normal", 0)
            manifest = json.loads((case / "manifest.json").read_text())
            manifest["view_id"] = "view-b"
            (case / "manifest.json").write_text(json.dumps(manifest))
            plan = [{"scene_id": "classroom", "view_id": "view-a", "profile": "normal", "seed_offset": 0}]
            result = module.analyze(temp, plan=plan)
            self.assertEqual(result["status"], "incomplete")
            self.assertEqual(result["cases"], [])
            self.assertTrue(any(row["reason"] == "outside_explicit_plan" for row in result["excluded_attempts"]))
            self.assertTrue(any(row.get("view_id") == "view-a" and row["detail"] == "Missing completed planned case" for row in result["issues"]))

    def test_sidecar_checksums_are_verified_before_diagnostic_values_are_used(self):
        module = tool(self)
        with tempfile.TemporaryDirectory() as temp:
            cases = fixture(temp)
            case = cases[("observe", 0)]
            diagnostic_sidecar(case)
            good = module.analyze(temp)
            self.assertEqual(good["status"], "passed", good["issues"])
            inspected = next(row for row in good["cases"] if row["profile"] == "observe" and row["seed_offset"] == 0)
            self.assertEqual(inspected["diagnostic_sidecar"]["status"], "passed")
            self.assertTrue(all(row["checksum_source"] == "pdf-diagnostics.json" for row in inspected["artifacts"] if "nrd" in row["path"]))
            path = case / "capture.PathTracer.nrdSpecularRadianceHitDist.2.RGBA.exr"
            write_exr(path, np.tile([.25, .5, 1.5, 1], (2, 3, 1)))
            bad = module.analyze(temp)
            self.assertEqual(bad["status"], "failed")
            self.assertTrue(any("SHA256" in row["detail"] and "nrdSpecular" in row["detail"] for row in bad["issues"]))

    def test_sidecar_profile_and_inventory_mismatch_are_failures(self):
        module = tool(self)
        with tempfile.TemporaryDirectory() as temp:
            cases = fixture(temp)
            case = cases[("observe", 0)]
            diagnostic_sidecar(case)
            path = case / "pdf-diagnostics.json"
            record = json.loads(path.read_text())
            record["profile"] = "one"
            record["artifacts"].pop()
            path.write_text(json.dumps(record))
            result = module.analyze(temp)
            self.assertEqual(result["status"], "failed")
            self.assertTrue(any("sidecar profile" in row["detail"] for row in result["issues"]))
            self.assertTrue(any("sidecar inventory" in row["detail"] for row in result["issues"]))

    def test_optional_aov_tolerance_only_relaxes_diagnostic_vs_color_only_pairs(self):
        module = tool(self)
        with tempfile.TemporaryDirectory() as temp:
            cases = fixture(temp)
            for profile in ("one", "native", "observe"):
                change_color_by_one_ulp(cases[(profile, 0)])
            strict = module.analyze(temp)
            self.assertEqual(strict["status"], "failed")
            allowed = module.analyze(temp, aov_atol=1e-6)
            self.assertEqual(allowed["status"], "passed", allowed["issues"])
            self.assertEqual(allowed["comparison_tolerance"]["aov_atol"], 1e-6)
            for pair in ("one_vs_baseline", "native_vs_baseline", "normal_vs_observe"):
                strict_row = next(row for row in strict["comparisons"] if row["pair"] == pair and row["seed_offset"] == 0)
                allowed_row = next(row for row in allowed["comparisons"] if row["pair"] == pair and row["seed_offset"] == 0)
                self.assertEqual(strict_row["status"], "failed")
                self.assertEqual(allowed_row["color_tolerance"], {"atol": 1e-6, "rtol": 0., "aov_atol_applies": True})
                frame = next(row for row in allowed_row["frames"] if row["frame"] == 2)
                self.assertFalse(frame["color"]["bitwise_equal"])
                self.assertEqual(frame["color"]["mismatch_pixels"], 1)
                self.assertGreater(frame["color"]["max_abs"], 0)
                self.assertEqual(frame["color"]["status"], "passed")
            matched = next(row for row in allowed["comparisons"] if row["pair"] == "one_vs_native" and row["seed_offset"] == 0)
            self.assertEqual(matched["color_tolerance"], {"atol": 0., "rtol": 0., "aov_atol_applies": False})
            self.assertTrue(all(frame["color"]["bitwise_equal"] for frame in matched["frames"]))

    def test_aov_tolerance_never_relaxes_matching_aov_profiles(self):
        module = tool(self)
        for profile, pair in (("one", "one_vs_native"), ("zero", "zero_vs_center")):
            with self.subTest(pair=pair), tempfile.TemporaryDirectory() as temp:
                cases = fixture(temp)
                change_color_by_one_ulp(cases[(profile, 0)])
                result = module.analyze(temp, aov_atol=1.)
                comparison = next(row for row in result["comparisons"] if row["pair"] == pair and row["seed_offset"] == 0)
                self.assertEqual(comparison["status"], "failed")
                self.assertEqual(comparison["color_tolerance"]["atol"], 0.)
                self.assertFalse(comparison["color_tolerance"]["aov_atol_applies"])

    def test_cli_records_optional_aov_tolerance(self):
        tool(self)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "report.json"
            run = subprocess.run([sys.executable, "-B", "-m", "scripts.falcor.pdf_pt_validation_results", temp,
                                  "--aov-atol", "1e-6", "--output", str(path)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
            self.assertEqual(json.loads(path.read_text())["comparison_tolerance"]["aov_atol"], 1e-6)


if __name__ == "__main__":
    unittest.main()
