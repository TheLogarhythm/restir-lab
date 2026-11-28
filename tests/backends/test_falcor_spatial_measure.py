"""Regression checks for delayed native GPU timestamps and historical settings."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.falcor import spatial_measure as measure, spatial_capture as capture


class SpatialMeasurementTests(unittest.TestCase):
    def test_campaign_rejects_development_override_before_preparing_inputs(self):
        import os
        from unittest.mock import patch
        from scripts.falcor import spatial_campaign as campaign
        with patch.object(os, "environ", {**os.environ, "FALCOR_DEVMODE": "1"}):
            try:
                with self.assertRaisesRegex(RuntimeError, "FALCOR_DEVMODE"):
                    campaign.run_campaign(measure.ROOT / "tmp/not-created",
                                          experiment_path=measure.ROOT / "missing-experiment.json")
            except OSError as error:
                self.fail("Development override reached campaign preparation: " + str(error))

    def test_capture_and_measure_reject_development_shader_override(self):
        import os
        from unittest.mock import patch
        with patch.object(os, "environ", {**os.environ, "FALCOR_DEVMODE": "1"}):
            for launch in (capture.launch, measure.launch):
                with self.subTest(launch=launch.__module__):
                    try:
                        with self.assertRaisesRegex(RuntimeError, "FALCOR_DEVMODE"):
                            launch(measure.ROOT / "missing-view.json", measure.ROOT / "tmp/not-created",
                                   measure.ROOT, method="baseline")
                    except OSError as error:
                        self.fail("Development override reached input preflight: " + str(error))

    def test_instrumentation_preserves_render_count_and_hdr_schedule(self):
        script = capture.render_script(Path("scene.pyscene"),
            {"position": [0,0,1], "direction": [0,0,-1], "up": [0,1,0], "vertical_fov": 45},
            Path("output"), 40, 8, "baseline", adapted=False)
        profiled = measure.instrument(script, list(range(41,49)), True)
        compile(profiled, "<profiled>", "exec")
        self.assertIn("range(1, 49)", profiled)
        self.assertEqual(profiled.count("m.renderFrame()"), 1)
        self.assertIn("frame - 1", profiled)
        self.assertIn("if frame in [41, 42, 43, 44, 45, 46, 47, 48]: m.frameCapture.capture()", profiled)
        timed = measure.instrument(script, list(range(41,49)), False)
        self.assertNotIn("m.frameCapture.capture()", timed)
        self.assertEqual(timed.count("m.renderFrame()"), 1)

    def test_previous_frame_alignment_and_nonfinite_rejection(self):
        events = {"/onFrameRender/PathTracer/tracePass/gpu_time": {"value": 1.5}}
        records = [{"rendered_frame": f, "gpu_measured_frame": f-1,
                    "events_previous_frame": events} for f in range(1,49)]
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "timings.json"
            p.write_text(json.dumps(records))
            result = measure.validate_timings(p, list(range(41,49)))
            self.assertEqual(result["measured_gpu_frames"], list(range(41,48)))
            self.assertEqual(result["unmeasured_last_gpu_frame"], 48)
            records[-1]["gpu_measured_frame"] = 48
            p.write_text(json.dumps(records))
            with self.assertRaises(ValueError):
                measure.validate_timings(p, list(range(41,49)))
            records[-1]["gpu_measured_frame"] = 47
            events["/onFrameRender/PathTracer/tracePass/gpu_time"]["value"] = float("nan")
            p.write_text(json.dumps(records))
            with self.assertRaises(ValueError):
                measure.validate_timings(p, list(range(41,49)))
