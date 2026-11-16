"""Approved fixed-view schedules and delayed GPU timestamp boundaries."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.falcor import spatial_measure as measure


class FixedViewSuiteTests(unittest.TestCase):
    def test_prepare_writes_snapshots_and_prepared_runtime_receipts(self):
        from contextlib import ExitStack
        from unittest.mock import patch
        from scripts.falcor import fixed_view_suite as suite
        planned = suite.plan()
        views = {"fixture": {"reference": {"path": "assets/ref.exr", "sha256": "a" * 64}}}
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            output = root / "runs/pt-fixed-view-batches/new"
            paths = {(method, False): root / "build" / method / "runtime"
                     for method in ("baseline", "cgns", "pdf-similarity")}
            receipts = {key: {"verified_method": key[0]} for key in paths}

            def prepared_runtimes(experiment, *, compare_method):
                return {key: path for key, path in paths.items() if key[0] in ("baseline", compare_method)}

            for obj, name, replacement in (
                (suite, "ROOT", root),
                (suite, "plan", lambda _: planned),
                (suite, "check_inputs", lambda _: views),
                (suite, "identity", lambda *a: {"fixture": "prepared-inputs"}),
                (suite, "environment", lambda: {"gpu": "external telemetry replaced"}),
                (suite, "check_renderer_idle", lambda: None),
                (suite.inputs, "prepare_runtimes", prepared_runtimes),
                (suite.inputs, "runtime_snapshots", lambda *a: receipts),
            ):
                stack.enter_context(patch.object(obj, name, replacement))
            try:
                manifest = suite.prepare(suite.DEFAULT_CONFIG, output)
            except AttributeError as error:
                self.fail("Preparation did not reach its output writes: " + str(error))
            state = json.loads(manifest.read_text())
            self.assertEqual(state["status"], "prepared")
            self.assertEqual(state["identity"], {"fixture": "prepared-inputs"})
            self.assertEqual(state["jobs"], {})
            self.assertEqual(set(state["runtimes"]),
                             {"baseline:reference", "cgns:reference", "pdf-similarity:reference"})
            self.assertEqual(state["runtimes"]["cgns:reference"],
                             {"path": "build/cgns/runtime", "verification": {"verified_method": "cgns"}})
            for phase, config in planned["experiments"].items():
                self.assertEqual(json.loads((output / "configs" / (phase + ".json")).read_text()), config)
            self.assertEqual(json.loads((output / "references.json").read_text()),
                             {"fixture": views["fixture"]["reference"]})

    def test_new_batches_are_separate_from_the_frozen_archive(self):
        from scripts.falcor import fixed_view_suite as suite
        output = suite.ROOT / "runs/pt-fixed-view-batches/new-batch"
        try:
            actual = suite.batch_path(output)
        except ValueError as error:
            self.fail("The writable batch namespace was rejected: " + str(error))
        self.assertEqual(actual, output)
        for path in (suite.ROOT / "runs/pt-fixed-view-batches",
                     suite.ROOT / "runs/pt-6-views-spatial-compare",
                     suite.ROOT / "runs/pt-6-views-spatial-compare/new-batch"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                suite.batch_path(path)

    def test_batch_path_rejects_a_nested_stage_archive_in_the_writable_namespace(self):
        from unittest.mock import patch
        from scripts.falcor import fixed_view_suite as suite
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "runs/pt-fixed-view-batches/frozen"
            archive.mkdir(parents=True)
            manifest = archive / "manifest.json"
            manifest.write_text(json.dumps({"kind": "falcor_pt_stage_archive"}))
            original = manifest.read_bytes()
            with patch.object(suite, "ROOT", root), self.assertRaisesRegex(ValueError, "archive"):
                suite.batch_path(archive / "new-batch")
            self.assertEqual(manifest.read_bytes(), original)
            self.assertEqual(list(archive.iterdir()), [manifest])

    def prepared_suite(self, directory, stack):
        from unittest.mock import patch
        from scripts.falcor import fixed_view_suite as suite
        planned = suite.plan()
        job = next(j for j in planned["jobs"] if j["label"] == "temporal-on")
        planned["jobs"] = [job]
        planned["quality_seed_offsets"] = [0]
        root = Path(directory)
        output = root / "runs/pt-fixed-view-batches/test"
        (output / "configs").mkdir(parents=True)
        for phase, config in planned["experiments"].items():
            (output / "configs" / (phase + ".json")).write_text(json.dumps(config))
        view_path = root / job["view_config"]
        view_path.parent.mkdir(parents=True)
        view_path.write_text("{}")
        (root / "runtime").mkdir()
        state = {"status": "prepared", "identity": {"fixture": True}, "jobs": {},
                 "runtimes": {"baseline:reference": {"path": "runtime", "verification": {}}}}
        state_path = output / "manifest.json"
        state_path.write_text(json.dumps(state))
        for obj, name, replacement in (
            (suite, "ROOT", root),
            (suite, "batch_path", lambda path: Path(path).resolve()),
            (suite, "plan", lambda _: planned),
            (suite, "check_inputs", lambda _: {job["view"]: {"adapted": False}}),
            (suite, "identity", lambda *a: {"fixture": True}),
            (suite, "environment", lambda: {"gpu": "external device replaced"}),
            (suite.capture, "validate_runtime", lambda *a: {}),
            (suite.capture, "launch", lambda **k: (_ for _ in ()).throw(RuntimeError("preflight failed"))),
        ):
            stack.enter_context(patch.object(obj, name, replacement))
        return suite, job, output

    def test_prelaunch_failure_is_preserved_and_requires_a_numbered_retry(self):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            suite, job, output = self.prepared_suite(directory, stack)
            state_path = output / "manifest.json"
            with self.assertRaisesRegex(RuntimeError, "preflight failed"):
                suite.execute(suite.DEFAULT_CONFIG, output)
            saved = json.loads(state_path.read_text())
            run_id = job["id"] + "/quality/seed-000000"
            self.assertEqual(saved["jobs"][run_id]["status"], "failed")
            first = output / saved["jobs"][run_id]["attempt"]
            failure = first / "launch-failure.json"
            original = failure.read_bytes()
            self.assertEqual(json.loads(original)["error"], "preflight failed")
            with self.assertRaisesRegex(ValueError, "retry-failed"):
                suite.execute(suite.DEFAULT_CONFIG, output)
            with self.assertRaisesRegex(RuntimeError, "preflight failed"):
                suite.execute(suite.DEFAULT_CONFIG, output, retry_failed=True)
            saved = json.loads(state_path.read_text())
            self.assertTrue(saved["jobs"][run_id]["attempt"].endswith("attempt-002"))
            self.assertEqual(failure.read_bytes(), original)

    def test_telemetry_failure_after_scheduling_preserves_the_attempt(self):
        from contextlib import ExitStack
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            suite, job, output = self.prepared_suite(directory, stack)
            stack.enter_context(patch.object(suite, "environment", side_effect=RuntimeError("telemetry failed")))
            with self.assertRaisesRegex(RuntimeError, "telemetry failed"):
                suite.execute(suite.DEFAULT_CONFIG, output)
            state = json.loads((output / "manifest.json").read_text())
            run_id = job["id"] + "/quality/seed-000000"
            record = state["jobs"].get(run_id, {})
            self.assertEqual(record.get("status"), "failed")
            receipt = output / record["attempt"] / "launch-failure.json"
            self.assertEqual(json.loads(receipt.read_text())["error"], "telemetry failed")

    def test_plan_aligns_four_labels_and_shared_seed_without_gpu(self):
        from scripts.falcor import fixed_view_suite as suite
        plan = suite.plan(suite.DEFAULT_CONFIG)
        self.assertEqual(len(plan["jobs"]), 24)
        self.assertEqual(plan["quality_frames"], list(range(41, 57)))
        self.assertEqual(plan["timing_frames"], list(range(41, 105)))
        self.assertEqual(plan["timing_render_frames"], 105)
        self.assertEqual(plan["quality_seed_offsets"], [0, 100000, 200000, 300000])
        self.assertEqual(plan["timing_seed_offset"], 0)
        methods = {j["label"]: (j["method"], j["temporal_reuse"]) for j in plan["jobs"]}
        self.assertEqual(methods, {
            "temporal-off": ("baseline", False), "temporal-on": ("baseline", True),
            "cgns": ("cgns", True), "pdf": ("pdf-similarity", True)})
        self.assertEqual(len({j["id"] for j in plan["jobs"]}), 24)

    def test_timing_drain_includes_last_gpu_frame_and_rejects_missing_sample(self):
        events = {"/onFrameRender/PathTracer/tracePass/gpu_time": {"value": 1.5},
                  "/onFrameRender/gpu_time": {"value": 2.0}}
        records = [{"rendered_frame": f, "gpu_measured_frame": f - 1,
                    "events_previous_frame": events} for f in range(1, 106)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "timings.json"
            path.write_text(json.dumps(records))
            result = measure.validate_timings(path, list(range(41, 105)), drain_last_frame=True)
            self.assertEqual(result["measured_gpu_frames"], list(range(41, 105)))
            self.assertIsNone(result["unmeasured_last_gpu_frame"])
            path.write_text(json.dumps(records[:-1]))
            with self.assertRaises(ValueError):
                measure.validate_timings(path, list(range(41, 105)), drain_last_frame=True)

    def test_drain_script_updates_seed_clock_and_camera_for_extra_render(self):
        from scripts.falcor import spatial_capture as capture
        source = capture.render_script(Path("scene.pyscene"),
            {"position": [0, 0, 1], "direction": [0, 0, -1],
             "up": [0, 1, 0], "vertical_fov": 45},
            Path("output"), 40, 64, "baseline", adapted=False, temporal_reuse=False)
        source = measure.instrument(source, list(range(41, 105)), False, drain_last_frame=True)
        # Execute the production loop alone: mock only the external Falcor device.
        import ast
        from types import SimpleNamespace
        tree = ast.parse(source)
        loop = next(n for n in tree.body if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == "frame")
        seen = []
        tracer = SimpleNamespace(fixedSeed=None)
        camera = lambda: {}
        device = SimpleNamespace(clock=SimpleNamespace(frame=None, framerate=0, time=0),
                                 profiler=SimpleNamespace(events={}),
                                 renderFrame=lambda: seen.append((tracer.fixedSeed, device.clock.frame)))
        env = {"m": device, "tracer": tracer, "time": __import__("time"),
               "timing_records": [], "records": {}, "camera_state": camera}
        # The scene-state capture is orthogonal to the frame/seed/timing loop.
        loop.body = [n for n in loop.body if not (
            isinstance(n, ast.If) and any(isinstance(v, ast.Attribute) and v.attr == "renderSettings"
                                         for v in ast.walk(n)))]
        exec(compile(ast.Module(body=[loop], type_ignores=[]), "<capture-loop>", "exec"), env)
        self.assertEqual(seen, [(f - 1, f) for f in range(1, 106)])
        self.assertEqual(env["records"]["last_frame"]["frame"], 105)
        self.assertEqual(env["timing_records"][-1]["gpu_measured_frame"], 104)

    def test_measure_launch_uses_requested_budget_and_temporal_off(self):
        from contextlib import ExitStack, nullcontext
        from unittest.mock import patch
        from scripts.falcor import fixed_view_suite as suite
        root = measure.ROOT
        (root / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root / "tmp") as folder:
            folder = Path(folder)
            scene = folder / "scene.pyscene"
            scene.write_text("")
            view_path = folder / "view.json"
            view_path.write_text("{}")
            experiment_path = folder / "timing.json"
            experiment_path.write_text(json.dumps(suite.plan()["experiments"]["timing"]))
            config = {"scene_id": "test", "view_id": "a",
                      "scene_source": scene.relative_to(root).as_posix(),
                      "camera": {"position": [0,0,1], "direction": [0,0,-1],
                                 "up": [0,1,0], "vertical_fov": 45}}
            entry = {"adapted": False, "asset_sha256": {}, "source_sha256": {}}
            captured = {}
            def fake_process(command, output, timeout, *, prepare, verify, metadata):
                # Only the external renderer is substituted. Exercise generated script and metadata.
                output.mkdir()
                prepare(output)
                captured.update(metadata)
                compile((output / "render.py").read_text(), "<generated>", "exec")
                return output / "manifest.json"
            with ExitStack() as stack:
                replacements = [
                    (measure, "exclusive_operation", lambda _: nullcontext()),
                    (measure, "check_renderer_idle", lambda: None),
                    (measure, "isolated_python_environment", nullcontext),
                    (measure.capture.build, "verify_build", lambda: {"commit": "test"}),
                    (measure.capture.views, "frozen_views", lambda: {("test", "a"): entry}),
                    (measure.capture.views, "load_config", lambda _: config),
                    (measure.capture.reference_extension_batch, "recheck_view", lambda *args: None),
                    (measure.capture.views, "validate_reference_for_view", lambda *a, **k: {}),
                    (measure.capture, "validate_runtime", lambda *a, **k: {}),
                    (measure.subprocess, "check_output", lambda *a, **k: "test GPU"),
                    (measure.run, "execute", fake_process)]
                for obj, name, replacement in replacements:
                    stack.enter_context(patch.object(obj, name, replacement))
                measure.launch(view_path, folder / "output", folder, "baseline",
                               experiment_path=experiment_path, temporal_reuse=False,
                               drain_last_frame=True)
            self.assertFalse(captured["temporal_reuse"])
            self.assertFalse(captured["requested_graph_options"]["reSTIRPathTracingOptions"]["useTemporalResampling"])
            self.assertEqual(captured["capture_frames"], list(range(41, 105)))
            self.assertEqual(captured["rendered_frames"], 105)
            self.assertFalse(captured["save_hdr"])

    def test_csv_keeps_gpu_and_cpu_times_on_their_own_frame(self):
        from scripts.falcor import fixed_view_suite as suite
        import csv
        records = [{"rendered_frame": f, "gpu_measured_frame": f-1,
                    "render_wall_ms_current_frame": 10*f,
                    "events_previous_frame": {"/onFrameRender/gpu_time": {"value": f-1}}}
                   for f in range(1, 5)]
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "timings.json").write_text(json.dumps(records))
            suite.timing_csv(directory, [2, 3])
            with (directory / "frames.csv").open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([(r["frame"], r["render_wall_ms"], r["/onFrameRender/gpu_time"]) for r in rows],
                             [("2", "20", "2"), ("3", "30", "3")])

    def test_four_quality_realizations_have_distinct_paths_and_only_one_timing_run(self):
        from scripts.falcor import fixed_view_suite as suite
        planned = suite.plan()
        quality = list(suite.phase_jobs(planned, "quality"))
        timing = list(suite.phase_jobs(planned, "timing"))
        self.assertEqual(len(quality), 96)
        self.assertEqual(len(timing), 24)
        self.assertEqual(len({j["run_id"] for j in quality + timing}), 120)
        for job in planned["jobs"]:
            self.assertEqual([j["seed_offset"] for j in quality if j["id"] == job["id"]],
                             [0, 100000, 200000, 300000])
        self.assertEqual({j["seed_offset"] for j in timing}, {0})
        self.assertTrue(all("/quality/seed-" in j["run_id"] for j in quality))

    def test_rejects_duplicate_overlapping_invalid_and_overflowing_quality_seeds(self):
        from scripts.falcor import fixed_view_suite as suite
        original = json.loads(suite.DEFAULT_CONFIG.read_text())
        (suite.ROOT / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=suite.ROOT / "tmp") as folder:
            path = Path(folder) / "suite.json"
            for seeds in ([0, 0, 200000, 300000], [0, 1, 200000, 300000],
                          [0, True, 200000, 300000], [0, -1, 200000, 300000],
                          [0, 100000, 200000, 2**32-1]):
                with self.subTest(seeds=seeds):
                    path.write_text(json.dumps({**original, "quality_seed_offsets": seeds}))
                    with self.assertRaises(ValueError):
                        suite.plan(path)

    def test_formal_capture_accepts_independent_seed_but_not_diagnostic_profile(self):
        from scripts.falcor import spatial_capture as capture
        for method in ("baseline", "cgns", "pdf-similarity"):
            capture.validate_capture_controls(method, scout=False, seed_offset=100000)
        with self.assertRaises(ValueError):
            capture.validate_capture_controls("pdf-similarity", seed_offset=100000, pdf_profile="one")

    def test_artifact_validation_binds_nonzero_path_and_temporal_seeds(self):
        import numpy as np
        import OpenEXR
        from scripts.falcor import spatial_campaign as campaign
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            records = []
            for frame, seed, reuse in ((1, 100000, 0), (41, 100040, 100039)):
                path = directory / f"capture.PathTracer.color.{frame}.exr"
                OpenEXR.File({}, {"RGB": np.ones((2, 3, 3), dtype=np.float32)}).write(str(path))
                records.append({"frame": frame, "seed": seed, "reuse_seed": reuse,
                                "hdr": path.name, "sha256": campaign.run.sha(path)})
            result = campaign.validate_artifacts(directory, records, [1, 41], 3, 2, seed_offset=100000)
            self.assertEqual([(r["seed"], r["reuse_seed"]) for r in result], [(100000, 0), (100040, 100039)])
            with self.assertRaises(ValueError):
                campaign.validate_artifacts(directory, records, [1, 41], 3, 2, seed_offset=0)
            records[0]["reuse_seed"] = 100000
            with self.assertRaises(ValueError):
                campaign.validate_artifacts(directory, records, [1, 41], 3, 2, seed_offset=100000)


if __name__ == "__main__":
    unittest.main()
