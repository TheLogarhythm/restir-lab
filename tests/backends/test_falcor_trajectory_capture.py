"""Formal trajectory budgets, delayed GPU timestamps and display annotation."""
import copy
import importlib
import importlib.util
import json
import math
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def pipeline():
    spec = importlib.util.find_spec("scripts.falcor.trajectory_capture")
    if spec is None:
        raise AssertionError("Formal trajectory capture pipeline is missing")
    return importlib.import_module("scripts.falcor.trajectory_capture")


def timing_records():
    return [{"rendered_frame": frame, "gpu_measured_frame": frame - 1,
             "render_wall_ms_current_frame": 9000,
             "events_previous_frame": {
                 "/onFrameRender/gpu_time": {"value": float(frame - 1)},
                 "/onFrameRender/cpu_time": {"value": 9999},
                 "/onFrameRender/RenderGraphExe::execute()/PathTracer/tracePass/gpu_time": {"value": 2},
                 "/onFrameRender/RenderGraphExe::execute()/PathTracer/ReSTIRPathTracing::updateReSTIRPT/spatialResampling/gpu_time": {"value": 3}}}
            for frame in range(1, 342)]


class TrajectoryCaptureTests(unittest.TestCase):
    def test_gpu_alignment_recovers_final_frame_and_uses_parent_only(self):
        mod = pipeline()
        rows = mod.timing_rows(timing_records())
        self.assertEqual(len(rows), 300)
        self.assertEqual((rows[0]["frame"], rows[0]["video_frame"], rows[0]["gpu_ms_raw"]), (41, 0, 41))
        self.assertEqual((rows[-1]["frame"], rows[-1]["video_frame"], rows[-1]["gpu_ms_raw"]), (340, 299, 340))
        self.assertEqual(rows[0]["gpu_ms_mean15"], 41)
        self.assertEqual(rows[14]["gpu_ms_mean15"], 48)
        self.assertEqual(rows[15]["gpu_ms_mean15"], 49)
        self.assertEqual(rows[-1]["gpu_ms_mean15"], 333)
        self.assertAlmostEqual(rows[-1]["gpu_fps_mean15"], 1000 / 333)
        self.assertEqual(rows[0]["gpu_events_ms"]["/onFrameRender/gpu_time"], 41)

    def test_timing_rejects_missing_delayed_frames_cpu_fallback_and_bad_gpu(self):
        mod = pipeline()
        corruptions = [
            lambda rows: rows.pop(),
            lambda rows: rows[-1].update(gpu_measured_frame=339),
            lambda rows: rows[41]["events_previous_frame"].pop("/onFrameRender/gpu_time"),
            lambda rows: rows[41]["events_previous_frame"]["/onFrameRender/gpu_time"].update(value=float("nan")),
            lambda rows: rows[41]["events_previous_frame"]["/onFrameRender/gpu_time"].update(value=0),
            lambda rows: rows[41]["events_previous_frame"]["/onFrameRender/gpu_time"].update(value=True),
            lambda rows: rows[41]["events_previous_frame"].pop("/onFrameRender/RenderGraphExe::execute()/PathTracer/tracePass/gpu_time"),
        ]
        for corrupt in corruptions:
            rows = timing_records()
            corrupt(rows)
            with self.subTest(corrupt=corrupt), self.assertRaises(ValueError):
                mod.timing_rows(rows)

    def test_watermark_distinguishes_gpu_measurement_and_playback(self):
        mod = pipeline()
        row = mod.timing_rows(timing_records())[0]
        self.assertEqual(mod.watermark("baseline", row),
                         "Baseline | GPU 41.00 ms | 24.39 GPU FPS | Playback 30 FPS")
        self.assertTrue(mod.watermark("pdf-similarity", row).startswith("PDF similarity | GPU "))
        self.assertTrue(mod.watermark("cgns", row).startswith("CGNS | GPU "))

    def test_only_approved_routes_and_new_runs_outputs_are_accepted(self):
        mod = pipeline()
        route = ROOT / "scenes/trajectories/pt-walkthroughs/classroom.json"
        for output in (ROOT / "runs", ROOT / "outside-runs/new-video"):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "new.*runs"):
                mod.launch(route, output, ROOT / "missing-runtime", "baseline")
        with self.assertRaisesRegex(ValueError, "approved trajectory"):
            mod.launch(ROOT / "missing.json", ROOT / "runs/not-created-formal-video", ROOT, "baseline")
        with self.assertRaisesRegex(ValueError, "method"):
            mod.launch(route, ROOT / "runs/not-created-formal-video", ROOT, "unknown")
        self.assertFalse((ROOT / "runs/not-created-formal-video").exists())

    def test_output_root_is_rejected_even_without_local_runs(self):
        mod = pipeline()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            runs = root / "runs"
            self.assertFalse(runs.exists())
            with patch.object(mod, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "new.*runs"):
                    mod._new_output(runs)
                self.assertEqual(mod._new_output(runs / "new-video"), runs / "new-video")
                runs.mkdir()
                with self.assertRaisesRegex(ValueError, "new.*runs"):
                    mod._new_output(runs)
                existing = runs / "existing-video"
                existing.mkdir()
                with self.assertRaisesRegex(ValueError, "new.*runs"):
                    mod._new_output(existing)
                with self.assertRaisesRegex(ValueError, "new.*runs"):
                    mod._new_output(root / "outside-runs")
            self.assertFalse((runs / "new-video").exists())

    def test_approved_routes_do_not_depend_on_local_runtime_preflight(self):
        mod = pipeline()
        with patch.object(mod, "PREFLIGHT", ROOT / "build/missing-trajectory-preflight.json"):
            for name in ("classroom", "bistro-interior", "bistro-exterior", "zero-day"):
                route = ROOT / "scenes/trajectories/pt-walkthroughs" / (name + ".json")
                with self.subTest(route=name):
                    actual, config, frames = mod._approved_trajectory(route)
                    self.assertEqual(actual, route.resolve())
                    self.assertEqual(len(frames), 340)

    def test_missing_or_changed_tracked_approval_receipt_cannot_be_bypassed_by_preflight(self):
        mod = pipeline()
        route = ROOT / "scenes/trajectories/pt-walkthroughs/classroom.json"
        with tempfile.TemporaryDirectory() as folder:
            receipt_path = Path(folder) / "approved-routes.json"
            with patch.object(mod, "APPROVAL_RECEIPT", receipt_path, create=True):
                with self.assertRaisesRegex(ValueError, "approval receipt"):
                    mod._approved_trajectory(route)
                receipt_path.write_text(json.dumps({"schema_version": 1, "trajectory_sha256": {
                    route.relative_to(ROOT).as_posix(): "0" * 64}}), encoding="utf8")
                with self.assertRaisesRegex(ValueError, "approved trajectory hash"):
                    mod._approved_trajectory(route)

    def test_formal_scripts_reject_schedule_or_seed_changes_before_building(self):
        from scripts.falcor import camera_trajectory
        mod = pipeline()
        frames = camera_trajectory.sample_frames(camera_trajectory.load(
            ROOT / "scenes/trajectories/pt-walkthroughs/classroom.json"))
        corruptions = (
            lambda rows: rows.pop(),
            lambda rows: rows[0].update(frame=2),
            lambda rows: rows[39].update(video_frame=0),
            lambda rows: rows[-1].update(video_frame=300),
            lambda rows: rows[0].update(path_seed=1),
            lambda rows: rows[-1].update(path_seed=340),
        )
        for corrupt in corruptions:
            altered = copy.deepcopy(frames)
            corrupt(altered)
            for phase in ("capture", "timing"):
                with self.subTest(corrupt=corrupt, phase=phase), self.assertRaisesRegex(ValueError, r"40\+300"):
                    mod.render_script(Path("scene.pyscene"), altered, Path("out"), {}, phase=phase)

    def test_render_scripts_keep_capture_budget_and_timing_flush_separate(self):
        from scripts.falcor import camera_trajectory
        mod = pipeline()
        config = camera_trajectory.load(ROOT / "scenes/trajectories/pt-walkthroughs/classroom.json")
        frames = camera_trajectory.sample_frames(config)
        for phase, count in (("capture", 340), ("timing", 341)):
            source = mod.render_script(Path("scene.pyscene"), frames, Path("out"), {}, phase=phase)
            compile(source, "<formal-video>", "exec")
            # Execute the generated loop with a deterministic stand-in for Falcor.
            begin = source.index("m.profiler.enabled = ")
            end = source.index("\nwith Path(", begin)
            loop = source[begin:end]
            from types import SimpleNamespace
            emitted, captured, actual = [], [], []
            clock = SimpleNamespace(frame=0, framerate=0, time=0)
            tracer = SimpleNamespace(fixedSeed=0)
            camera = SimpleNamespace(position=None, target=None, up=None)
            profiler = SimpleNamespace(events={})
            def render():
                emitted.append((clock.frame, tracer.fixedSeed, camera.position))
            engine = SimpleNamespace(renderFrame=render, clock=clock, profiler=profiler,
                                     frameCapture=SimpleNamespace(capture=lambda: captured.append(clock.frame)),
                                     scene=SimpleNamespace(renderSettings=SimpleNamespace(useAnalyticLights=True, useEnvLight=True, useEmissiveLights=True), lights=[], envMap=None, stats={}))
            class Sink:
                def write_text(self, *args, **kwargs):
                    pass
            def camera_state():
                return {"position": camera.position[:], "target": camera.target[:], "up": camera.up[:],
                        "frameHeight": 24, "focalLength": 12 / math.tan(math.radians(65) / 2),
                        "apertureRadius": 0, "animated": False,
                        "nearPlane": frames[0]["camera"]["near_plane"]}
            namespace = {"trajectory": frames, "trajectory_records": actual, "timing_records": [],
                         "m": engine, "tracer": tracer, "camera": camera,
                         "float3": lambda *values: list(values), "camera_state": camera_state,
                         "records": {}, "Path": lambda *args: Sink(), "json": json,
                         "time": SimpleNamespace(perf_counter=lambda: 0)}
            exec(loop, namespace)
            self.assertEqual(len(emitted), count)
            self.assertEqual(len(actual), 340)
            mod.trajectory_script.verify_camera_records(actual, frames)
            self.assertEqual([row[2] for row in emitted[:340]],
                             [row["camera"]["position"] for row in frames])
            self.assertEqual(profiler.enabled, phase == "timing")
            self.assertEqual(namespace["records"]["last_frame"]["frame"], count)
            self.assertEqual(emitted[0][:2], (1, 0))
            self.assertEqual(emitted[339][:2], (340, 339))
            self.assertEqual(captured, list(range(41, 341)) if phase == "capture" else [])
            if phase == "timing":
                self.assertEqual(emitted[-1], (341, 340, frames[-1]["camera"]["position"]))
                self.assertEqual(len(namespace["timing_records"]), 341)
                self.assertEqual(namespace["timing_records"][-1]["gpu_measured_frame"], 340)


if __name__ == "__main__":
    unittest.main()
