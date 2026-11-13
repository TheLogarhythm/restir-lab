"""Shared safety contracts and controlled temporal contrast campaigns."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import OpenEXR
from scripts.falcor import cgns_paper_campaign as paper, cgns_temporal_campaign as temporal
from scripts.falcor import spatial_campaign as campaign


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_artifact(path, frame):
    OpenEXR.File({}, {"RGB": np.ones((2, 3, 3), dtype=np.float32) * frame}).write(str(path))
    return {
        "frame": frame,
        "seed": frame - 1,
        "reuse_seed": max(0, frame - 2),
        "hdr": path.name,
        "sha256": digest(path),
    }


class CampaignContracts(unittest.TestCase):

    def test_artifacts_bind_exact_frames_seeds_dimensions_and_hashes(self):
        for api in (paper, temporal):
            with self.subTest(mode=api.__name__):
                validate_artifacts = api.validate_artifacts
                with tempfile.TemporaryDirectory() as d:
                    root = Path(d)
                    artifacts = [
                        make_artifact(root / f"capture.PathTracer.color.{n}.exr", n)
                        for n in (41, 42)
                    ]
                    self.assertEqual(
                        [x["frame"] for x in validate_artifacts(root, artifacts, [41, 42], 3, 2)],
                        [41, 42],
                    )
                    bad = [dict(x) for x in artifacts]
                    bad[1]["seed"] = 1
                    with self.assertRaises(ValueError):
                        validate_artifacts(root, bad, [41, 42], 3, 2)
                    bad = [dict(x) for x in artifacts]
                    bad[1]["sha256"] = "0" * 64
                    with self.assertRaises(ValueError):
                        validate_artifacts(root, bad, [41, 42], 3, 2)
                    with self.assertRaises(ValueError):
                        validate_artifacts(root, artifacts, [41, 42], 4, 2)
                    bad = [dict(x) for x in artifacts]
                    bad[1]["hdr"] = "../escape.exr"
                    with self.assertRaises(ValueError):
                        validate_artifacts(root, bad, [41, 42], 3, 2)

    def test_completed_attempt_reused_failed_requires_explicit_new_attempt(self):
        for api in (paper, temporal):
            with self.subTest(mode=api.__name__):
                choose_attempt = api.choose_attempt
                with tempfile.TemporaryDirectory() as d:
                    root = Path(d)
                    path, reused = choose_attempt(root)
                    self.assertEqual(path.name, "attempt-001")
                    self.assertFalse(reused)
                    path.mkdir()
                    (path / "manifest.json").write_text(
                        json.dumps({"status": "failed"}), encoding="utf8"
                    )
                    with self.assertRaises(ValueError):
                        choose_attempt(root)
                    path2, reused = choose_attempt(root, retry_failed=True)
                    self.assertEqual(path2.name, "attempt-002")
                    self.assertFalse(reused)
                    path2.mkdir()
                    (path2 / "manifest.json").write_text(
                        json.dumps({"status": "completed"}), encoding="utf8"
                    )
                    self.assertEqual(choose_attempt(root), (path2, True))
                    self.assertTrue(path.exists())

    def test_unfinished_attempt_does_not_get_overwritten(self):
        for api in (paper, temporal):
            with self.subTest(mode=api.__name__):
                choose_attempt = api.choose_attempt
                with tempfile.TemporaryDirectory() as d:
                    root = Path(d)
                    a = root / "attempt-001"
                    a.mkdir()
                    (a / "manifest.json").write_text('{"status":"running"}', encoding="utf8")
                    with self.assertRaises(ValueError):
                        choose_attempt(root)
                    self.assertEqual(
                        choose_attempt(root, retry_failed=True), (root / "attempt-002", False)
                    )

    def test_pair_requires_matching_graph_camera_state_and_frame_seed(self):
        for api in (paper, temporal):
            with self.subTest(mode=api.__name__):
                validate_pair = api.validate_pair
                with tempfile.TemporaryDirectory() as d:
                    root = Path(d)
                    a = root / "baseline"
                    b = root / "cgns"
                    a.mkdir()
                    b.mkdir()
                    for x in (a, b):
                        (x / "resolved.py").write_text("same graph", encoding="utf8")
                        (x / "resolved-camera.json").write_text(
                            '{"camera":[1,2,3]}', encoding="utf8"
                        )
                        (x / "scene-state.json").write_text('{"light":2}', encoding="utf8")
                    base = {
                        "scene_id": "x",
                        "view_id": "view-a",
                        "scene_config_sha256": "a",
                        "reference_baseline_sha256": "b",
                        "resolution": [3, 2],
                        "warmup_frames": 40,
                        "capture_frames": [41, 42],
                        "spp_per_frame": 1,
                        "image_accumulation": False,
                        "requested_graph_options": {"x": 1},
                        "temporal_reuse": True,
                        "clock_policy": {"paused": True, "framerate": 0, "time": 0},
                        "seed_policy": "lag-one",
                        "build_commit": "c",
                        "gpu_driver": "g",
                    }
                    x = {
                        **base,
                        "requested_method": "baseline",
                        "artifacts": [
                            {"frame": 41, "seed": 40, "reuse_seed": 39},
                            {"frame": 42, "seed": 41, "reuse_seed": 40},
                        ],
                    }
                    y = {
                        **base,
                        "requested_method": "cgns",
                        "artifacts": [
                            {"frame": 41, "seed": 40, "reuse_seed": 39},
                            {"frame": 42, "seed": 41, "reuse_seed": 40},
                        ],
                    }
                    validate_pair(a, x, b, y)
                    (b / "scene-state.json").write_text('{"light":3}', encoding="utf8")
                    with self.assertRaises(ValueError):
                        validate_pair(a, x, b, y)
                    (b / "scene-state.json").write_text('{"light":2}', encoding="utf8")
                    y["artifacts"][1]["seed"] = 2
                    with self.assertRaises(ValueError):
                        validate_pair(a, x, b, y)

    def test_recorded_dependency_hashes_must_be_complete_and_current(self):
        for api in (paper, temporal):
            with self.subTest(mode=api.__name__):
                validate_code_inputs = api.validate_code_inputs
                with tempfile.TemporaryDirectory() as d:
                    root = Path(d)
                    (root / "driver.py").write_text("driver")
                    (root / "dependency.py").write_text("dependency")
                    (root / "render.py").write_text("render")
                    meta = {
                        "driver_sha256": digest(root / "driver.py"),
                        "render_script_sha256": digest(root / "render.py"),
                        "dependency_sha256": {"dependency.py": digest(root / "dependency.py")},
                    }
                    validate_code_inputs(
                        meta, root / "render.py", root / "driver.py", root, {"dependency.py"}
                    )
                    with self.assertRaises(ValueError):
                        validate_code_inputs(
                            meta,
                            root / "render.py",
                            root / "driver.py",
                            root,
                            {"dependency.py", "missing.py"},
                        )
                    (root / "dependency.py").write_text("changed")
                    with self.assertRaises(ValueError):
                        validate_code_inputs(
                            meta, root / "render.py", root / "driver.py", root, {"dependency.py"}
                        )

    def test_saved_validation_receipt_cannot_silently_change(self):
        for api in (paper, temporal):
            with self.subTest(mode=api.__name__):
                _bind_receipt = campaign._bind_receipt
                with tempfile.TemporaryDirectory() as d:
                    path = Path(d) / "receipt.json"
                    original = {"files": {"manifest.json": "abc"}}
                    first = _bind_receipt(path, original)
                    self.assertEqual(_bind_receipt(path, original), first)
                    with self.assertRaises(ValueError):
                        _bind_receipt(path, {"files": {"manifest.json": "changed"}})

    def test_interrupted_analysis_input_is_preserved_on_retry(self):
        for api in (paper, temporal):
            with self.subTest(mode=api.__name__):
                _next_analysis = campaign._next_analysis
                with tempfile.TemporaryDirectory() as d:
                    root = Path(d)
                    inp, out = _next_analysis(root, False)
                    inp.write_text("prior input")
                    with self.assertRaises(ValueError):
                        _next_analysis(root, False)
                    new_input, new_output = _next_analysis(root, True)
                    self.assertNotEqual(inp, new_input)
                    self.assertEqual(inp.read_text(), "prior input")
                    self.assertFalse(new_output.exists())


class TemporalContrastCampaignTests(unittest.TestCase):
    def fixture(self, root, view_count=1, fail_label=None):
        from contextlib import ExitStack, nullcontext
        from unittest.mock import patch

        stack = ExitStack()
        self.addCleanup(stack.close)
        config = root / "scene.json"
        config.write_text("{}")
        reference = root / "reference.exr"
        make_artifact(reference, 1)
        baseline, cgns = root / "baseline-runtime", root / "cgns-runtime"
        baseline.mkdir()
        cgns.mkdir()
        paths = {("baseline", False): baseline, ("cgns", False): cgns}
        catalog = {}
        for index in range(view_count):
            key = ("classroom" if index == 0 else f"scene-{index}", "view-a")
            catalog[key] = {
                "entry": {
                    "adapted": False,
                    "config_sha256": digest(config),
                    "asset_sha256": {},
                    "source_sha256": {},
                },
                "config": {},
                "config_path": config,
                "reference": {"path": str(reference), "sha256": digest(reference)},
            }
        calls = []
        failed = []
        self.reference_image_scopes = []

        def reference_catalog(*args, **kwargs):
            if kwargs.get("require_images"):
                self.reference_image_scopes.append(kwargs.get("image_views"))
            return catalog

        def launch(cfg, path, runtime, *, method, temporal_reuse, **kwargs):
            label = "on" if temporal_reuse else "off"
            calls.append((method, temporal_reuse, path.name))
            path.mkdir(parents=True)
            if label == fail_label and not failed:
                failed.append(True)
                (path / "manifest.json").write_text('{"status":"failed"}')
                raise RuntimeError("renderer failed")
            options = campaign.capture.graph_options(
                method, kwargs["experiment"], temporal_reuse=temporal_reuse
            )
            (path / "resolved.py").write_text("options = " + repr(options))
            (path / "resolved-camera.json").write_text('{"camera":1}')
            (path / "scene-state.json").write_text('{"light":1}')
            artifacts = [
                make_artifact(path / f"capture.PathTracer.color.{frame}.exr", frame)
                for frame in range(41, 49)
            ]
            if not temporal_reuse:
                for artifact in artifacts:
                    artifact.pop("reuse_seed")
            meta = {
                "status": "completed",
                "requested_method": method,
                "temporal_reuse": temporal_reuse,
                "clock_policy": {"paused": True, "framerate": 0, "time": 0},
                "seed_policy": campaign.seed_policy(temporal_reuse),
                "requested_graph_options": options,
                "capture_frames": list(range(41, 49)),
                "warmup_frames": 40,
                "artifacts": artifacts,
            }
            (path / "manifest.json").write_text(json.dumps(meta))

        def verify(path, *args, temporal_reuse, **kwargs):
            meta = json.loads((path / "manifest.json").read_text())
            campaign.validate_artifacts(
                path, meta["artifacts"], list(range(41, 49)), 3, 2, temporal_reuse=temporal_reuse
            )
            return meta, {
                "files": {"manifest.json": digest(path / "manifest.json")},
                "artifacts": meta["artifacts"],
            }

        for name, value in (
            ("ROOT", root),
            ("RUNTIME", paths),
            ("_code_identity", lambda: {"code": "constant"}),
            ("_reference_catalog", reference_catalog),
            (
                "_runtime_snapshots",
                lambda experiment, paths: {key: {"id": str(value)} for key, value in paths.items()},
            ),
            ("exclusive_operation", lambda *a, **k: nullcontext()),
            ("check_renderer_idle", lambda: None),
            ("_validate_job", verify),
        ):
            stack.enter_context(patch.object(campaign, name, value))
        prepare = stack.enter_context(
            patch.object(campaign, "_prepare_runtimes", return_value=paths)
        )
        stack.enter_context(
            patch.object(campaign.build, "verify_build", return_value={"commit": "c"})
        )
        stack.enter_context(patch.object(campaign.reference_extension_batch, "recheck_view"))
        stack.enter_context(patch.object(campaign.capture, "launch", side_effect=launch))
        return calls, prepare

    def test_default_launches_all_six_views_with_temporal_on(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls, prepare = self.fixture(root, view_count=6)
            report = campaign.run_campaign(root / "campaign")
            self.assertTrue((report / "summary.json").is_file())
            self.assertEqual(len(calls), 12)
            self.assertEqual(
                self.reference_image_scopes,
                [
                    {
                        ("classroom" if index == 0 else f"scene-{index}", "view-a")
                        for index in range(6)
                    }
                ],
            )
            self.assertEqual(
                {(method, mode) for method, mode, _ in calls}, {("baseline", True), ("cgns", True)}
            )
            prepare.assert_called_once()
            saved = json.loads((root / "campaign/campaign.json").read_text())
            self.assertEqual(saved["status"], "completed")
            self.assertEqual(len(saved["jobs"]), 12)
            self.assertTrue(all(job["status"] == "completed" for job in saved["jobs"].values()))

    def test_contrast_selects_one_view_skips_cgns_and_preserves_failed_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls, prepare = self.fixture(root, view_count=6, fail_label="off")
            output = root / "campaign"
            with self.assertRaisesRegex(RuntimeError, "renderer failed"):
                campaign.run_campaign(output, temporal_contrast=True, view="classroom/view-a")
            saved = json.loads((output / "campaign.json").read_text())
            self.assertEqual(saved["status"], "failed")
            self.assertEqual(saved["jobs"]["classroom/view-a/temporal-on"]["status"], "completed")
            self.assertEqual(saved["jobs"]["classroom/view-a/temporal-off"]["status"], "failed")
            with self.assertRaisesRegex(ValueError, "retry-failed"):
                campaign.run_campaign(output, temporal_contrast=True, view="classroom/view-a")
            report = campaign.run_campaign(
                output, retry_failed=True, temporal_contrast=True, view="classroom/view-a"
            )
            self.assertTrue((report / "summary.json").is_file())
            self.assertEqual(
                calls,
                [
                    ("baseline", True, "attempt-001"),
                    ("baseline", False, "attempt-001"),
                    ("baseline", False, "attempt-002"),
                ],
            )
            prepare.assert_not_called()
            saved = json.loads((output / "campaign.json").read_text())
            self.assertEqual(len(saved["identity"]["runtimes"]), 1)
            self.assertEqual(len(saved["identity"]["views"]), 1)
            self.assertEqual(saved["status"], "completed")
            self.assertTrue(self.reference_image_scopes)
            self.assertTrue(
                all(scope == {("classroom", "view-a")} for scope in self.reference_image_scopes)
            )
            self.assertEqual(
                (
                    output / "jobs/classroom/view-a/temporal-off/attempt-001/manifest.json"
                ).read_text(),
                '{"status":"failed"}',
            )
            self.assertEqual(
                campaign.run_campaign(output, temporal_contrast=True, view="classroom/view-a"),
                report,
            )
            self.assertEqual(len(calls), 3)
            payload = json.loads((output / saved["report"]["analysis_input"]).read_text())
            self.assertEqual(payload["settings"]["comparison_kind"], "baseline-temporal-on-off")
            self.assertEqual(
                set(payload["views"][0]["pairs"][0]), {"id", "temporal_on", "temporal_off"}
            )
            frame = next(
                (output / "jobs/classroom/view-a/temporal-on/attempt-001").glob("capture*.exr")
            )
            frame.write_bytes(b"tamper")
            with self.assertRaises(ValueError):
                campaign.run_campaign(output, temporal_contrast=True, view="classroom/view-a")
            self.assertEqual(len(calls), 3)

    def test_invalid_selection_is_rejected_before_runtime_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls, prepare = self.fixture(root)
            for kwargs in (
                {"temporal_contrast": True},
                {"view": "classroom/view-a"},
                {"temporal_contrast": True, "view": "classroom/view-a,view-b"},
                {"temporal_contrast": True, "view": "unknown/view-a"},
            ):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    campaign.run_campaign(root / "campaign", **kwargs)
            prepare.assert_not_called()
            self.assertEqual(calls, [])
            self.assertFalse((root / "campaign").exists())

    def test_contrast_rejects_uncontrolled_graph_state_and_schedule(self):
        from copy import deepcopy

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            campaign.run_campaign(
                root / "campaign", temporal_contrast=True, view="classroom/view-a"
            )
            on = root / "campaign/jobs/classroom/view-a/temporal-on/attempt-001"
            off = root / "campaign/jobs/classroom/view-a/temporal-off/attempt-001"
            ma, mb = json.loads((on / "manifest.json").read_text()), json.loads(
                (off / "manifest.json").read_text()
            )
            for mutate in (
                lambda meta: meta["requested_graph_options"].__setitem__("samplesPerPixel", 2),
                lambda meta: meta["clock_policy"].__setitem__("time", 1),
                lambda meta: meta["artifacts"][0].__setitem__("seed", 99),
                lambda meta: meta.__setitem__("runtime", "different"),
            ):
                altered = deepcopy(mb)
                mutate(altered)
                with self.assertRaises(ValueError):
                    campaign.validate_temporal_contrast(on, ma, off, altered)
            (off / "scene-state.json").write_text('{"light":2}')
            with self.assertRaises(ValueError):
                campaign.validate_temporal_contrast(on, ma, off, mb)

    def test_failure_before_output_still_requires_a_new_attempt(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls, prepare = self.fixture(root)
            output = root / "campaign"
            with patch.object(
                campaign.capture, "launch", side_effect=RuntimeError("preflight failed")
            ):
                with self.assertRaisesRegex(RuntimeError, "preflight failed"):
                    campaign.run_campaign(output, temporal_contrast=True, view="classroom/view-a")
            failure = output / "jobs/classroom/view-a/temporal-on/attempt-001/campaign-failure.json"
            self.assertEqual(json.loads(failure.read_text())["status"], "failed")
            with self.assertRaisesRegex(ValueError, "retry-failed"):
                campaign.run_campaign(output, temporal_contrast=True, view="classroom/view-a")
            campaign.run_campaign(
                output, retry_failed=True, temporal_contrast=True, view="classroom/view-a"
            )
            self.assertEqual(
                calls, [("baseline", True, "attempt-002"), ("baseline", False, "attempt-001")]
            )
            self.assertTrue(failure.is_file())
            prepare.assert_not_called()

    def test_analysis_failure_reuses_captures_and_preserves_input(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls, _ = self.fixture(root)
            output = root / "campaign"
            with patch.object(
                campaign.analysis, "analyze", side_effect=RuntimeError("analysis failed")
            ):
                with self.assertRaisesRegex(RuntimeError, "analysis failed"):
                    campaign.run_campaign(output, temporal_contrast=True, view="classroom/view-a")
            saved = json.loads((output / "campaign.json").read_text())
            self.assertEqual(saved["status"], "failed")
            self.assertTrue(all(job["status"] == "completed" for job in saved["jobs"].values()))
            first = (output / "analysis/input-001.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "retry-failed"):
                campaign.run_campaign(output, temporal_contrast=True, view="classroom/view-a")
            report = campaign.run_campaign(
                output, retry_failed=True, temporal_contrast=True, view="classroom/view-a"
            )
            self.assertEqual(report.name, "attempt-002")
            self.assertEqual((output / "analysis/input-001.json").read_bytes(), first)
            self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
