"""PDF-similarity settings must never be silently ignored by the DI runner."""
from pathlib import Path
import sys
import unittest
import subprocess
import tempfile
import shutil
import os
import json
import re
import ast
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / "scripts/run/rtxdi_experiments"
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment.config import load_definition, make_config
from experiment.scenes import load_scene


class PdfSimilarityConfigTests(unittest.TestCase):
    def test_viewer_is_windowed_and_does_not_capture_experiment_frames(self):
        from rtxdi_pdf_viewer import viewer_config
        for enabled in (True, False):
            config = viewer_config(load_scene("cornell-box"), "combined", [640, 360], enabled)
            self.assertTrue(config["interactive"])
            self.assertEqual(config["viewer_frames"], 0)
            self.assertEqual(config["arguments"]["device.headless"], 0)
            self.assertEqual(config["definition"]["pdf_similarity"], enabled)
            self.assertEqual(len(config["frames"]), 1)
            self.assertFalse(config["frames"][0]["capture"])

    def test_invalid_switch_rejected_before_rendering(self):
        scene = load_scene("cornell-box")
        for value in ("true", 1, None, {}):
            definition = load_definition()
            definition["pdf_similarity"] = value
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "pdf_similarity"):
                    make_config(scene, definition, "combined", "static")

    def test_invalid_research_history_mode_is_rejected(self):
        for value in (-1, 3, True, "2", 0.5):
            definition = load_definition()
            definition["pdf_history_mode"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "pdf_history_mode"):
                make_config(load_scene("arcade"), definition, "combined", "motion")

    def test_nonzero_history_mode_requires_pdf_similarity(self):
        for mode in (1, 2):
            definition = load_definition()
            definition.update(pdf_similarity=False, pdf_history_mode=mode)
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "pdf_history_mode"):
                make_config(load_scene("cornell-box"), definition, "combined", "motion")

    def test_supported_history_modes_preserve_requested_value(self):
        for mode in (0, 1, 2):
            definition = load_definition()
            definition.update(pdf_similarity=True, pdf_history_mode=mode)
            config = make_config(load_scene("cornell-box"), definition, "combined", "motion")
            self.assertEqual(config["definition"]["pdf_history_mode"], mode)

    def test_pdf_requires_spatial_reuse(self):
        definition = load_definition()
        definition["pdf_similarity"] = True
        for mode in ("initial", "temporal"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "spatial"):
                make_config(load_scene("cornell-box"), definition, mode, "static")

    def test_pdf_settings_preserve_reset_schedule(self):
        definition = load_definition()
        definition["pdf_similarity"] = True
        for mode in ("spatial", "combined"):
            config = make_config(load_scene("cornell-box"), definition, mode, "reset")
            self.assertTrue(config["definition"]["pdf_similarity"])
            self.assertEqual([f["frame"] for f in config["frames"] if f["reset"]], [1, 65])

    def test_old_executable_cannot_silently_ignore_pdf_switch(self):
        from experiment import runner
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / "old.exe"
            executable.write_bytes(b"fixture")
            executable.with_suffix(".build.json").write_text("{}")
            with mock.patch.object(runner, "query", return_value=""):
                with self.assertRaisesRegex(RuntimeError, "PDF similarity"):
                    runner.preflight({"pdf_similarity": True}, executable)

    def test_missing_runtime_confirmation_rejects_requested_pdf(self):
        from experiment.artifacts import validate_run_outputs
        definition = load_definition()
        definition["pdf_similarity"] = True
        config = make_config(load_scene("cornell-box"), definition, "combined", "static")
        config["frames"] = config["frames"][:1]
        frame = config["frames"][0]
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output / "timings.csv").write_text(
                "frame,sampling_frame,capture,history_reset,gpu_ms\n"
                f"1,{frame['sampling_frame']},1,1,1\n")
            (output / "resolved.json").write_text(json.dumps({"pdf_similarity": False}))
            with self.assertRaisesRegex(RuntimeError, "PDF similarity"):
                validate_run_outputs(output, config)


class PdfHistoryOutputTests(unittest.TestCase):
    def validate(self, requested, actual, *, enabled=True):
        from experiment.artifacts import validate_run_outputs
        definition = load_definition()
        definition.update(pdf_similarity=enabled, pdf_history_mode=requested)
        config = make_config(load_scene("cornell-box"), definition, "combined", "static")
        config["frames"] = config["frames"][:1]
        frame = config["frames"][0]
        scene = config["scene"]
        resolved = {"pdf_similarity": enabled, "mode": 3, "width": config["width"],
            "height": config["height"], "scene_id": config["scene_id"],
            "loaded_scene": "Assets/Media/" + scene["source"]["entry"], "headless": True,
            "vertical_fov_degrees": scene["camera"]["vertical_fov"],
            "denoiser": 0, "aa": 0, "checkerboard": 0, "pixel_jitter": 0,
            "initialSamplingParams": {"numLocalLightSamples": definition["initial_local_candidates"],
                "numBrdfSamples": definition["initial_brdf_candidates"],
                "numInfiniteLightSamples": definition["initial_infinite_candidates"],
                "numEnvironmentSamples": definition["initial_environment_candidates"],
                "localLightSamplingMode": int(definition.get("initial_local_sampling_mode", "UNIFORM") == "POWER_RIS"),
                "environmentMapImportanceSampling": 1},
            "environment_present": True,
            "spatialResamplingParams": {"numSamples": definition["spatial_neighbors"]},
            "temporalResamplingParams": {"maxHistoryLength": definition["max_history_length"]},
            **scene["lighting"]}
        if actual is not None:
            resolved["pdf_history_mode"] = actual
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output / "timings.csv").write_text(
                "frame,sampling_frame,capture,history_reset,gpu_ms,temporal_ms,spatial_ms\n"
                f"1,{frame['sampling_frame']},{int(frame['capture'])},1,3,1,1\n")
            (output / "resolved.json").write_text(json.dumps(resolved))
            validate_run_outputs(output, config)

    def test_exact_mode_confirmation_passes(self):
        for mode in (0, 1, 2):
            with self.subTest(mode=mode):
                self.validate(mode, mode)
        self.validate(0, None, enabled=False)  # Older ordinary builds have no PDF fields.

    def test_missing_mismatched_or_malformed_mode_confirmation_rejected(self):
        for requested in (0, 1, 2):
            for actual in (None, (requested + 1) % 3, True, float(requested), str(requested)):
                with self.subTest(requested=requested, actual=actual), self.assertRaisesRegex(
                        RuntimeError, "PDF history"):
                    self.validate(requested, actual)


class PdfSimilarityMathTests(unittest.TestCase):
    def test_direction_reservoir_update(self):
        self.compile_and_run("pdf_direction_reservoir.cpp")

    def test_spatial_resampling_uses_fractional_m_in_both_loops(self):
        import rtxdi_pdf
        source = ROOT / "renderers/rtxdi/Libraries/Rtxdi/Include/Rtxdi/DI"
        def function(text, name):
            match = re.search(r"(?:bool|void|RTXDI_DIReservoir) " + name + r"\(", text)
            self.assertIsNotNone(match, name)
            start = text.index("{", match.start())
            depth, end = 1, start + 1
            while depth:
                depth += (text[end] == "{") - (text[end] == "}")
                end += 1
            return re.sub(r"inout (\w+) (\w+)", r"\1& \2", text[match.start():end])
        reservoir = (source / "Reservoir.hlsli").read_text()
        spatial = rtxdi_pdf.adapt_spatial((source / "SpatialResampling.hlsli").read_text())
        extracted = "\n".join(function(reservoir, name) for name in (
            "RTXDI_InternalSimpleResample", "RTXDI_CombineDIReservoirs", "RTXDI_FinalizeResampling"))
        extracted += "\n" + function(spatial, "RTXDI_DISpatialResampling")
        self.compile_and_run("pdf_spatial_resampling.cpp", extracted)

    def test_generated_renderer_history_config_uses_strict_json_modes(self):
        import rtxdi_pdf
        tree = ast.parse(Path(rtxdi_pdf.__file__).read_text())
        additions = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                     and isinstance(node.value, str) and "void ConfigurePdf(" in node.value]
        self.assertEqual(len(additions), 1)
        configure = additions[0].split("    void ApplySun(")[0]
        self.compile_and_run("pdf_history_config.cpp", configure, "pdf_config_under_test.h",
            ROOT / "renderers/rtxdi/External/donut/thirdparty/jsoncpp-amalgam")

    def test_shader_math_on_cpu(self):
        self.compile_and_run("pdf_similarity_math.cpp")

    def test_viewer_toggle_restarts_history_and_sampling_sequence(self):
        self.compile_and_run("pdf_viewer_state.cpp")

    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("cl")
        if cls.compiler is None:
            raise unittest.SkipTest("MSVC is required for the shared shader-math check")
        cls.environment = os.environ.copy()
        if not cls.environment.get("INCLUDE"):
            vcvars = Path(cls.compiler).parents[6] / "Auxiliary/Build/vcvars64.bat"
            settings = subprocess.check_output(f'cmd /d /s /c ""{vcvars}" >nul && set"', text=True)
            cls.environment.update(line.split("=", 1) for line in settings.splitlines() if "=" in line and not line.startswith("="))

    def compile_and_run(self, source, generated_header=None, header_name="spatial_under_test.h", extra_include=PAYLOAD):
        with tempfile.TemporaryDirectory() as directory:
            if generated_header is not None:
                (Path(directory) / header_name).write_text(generated_header)
            result = subprocess.run([self.compiler, "/nologo", "/EHsc", "/std:c++17",
                str(ROOT / "tests" / source), "/I" + str(PAYLOAD), "/I" + directory, "/I" + str(extra_include),
                "/Fe:" + str(Path(directory) / "math.exe"),
                "/Fo:" + str(Path(directory) / "math.obj")], cwd=directory, capture_output=True, text=True, env=self.environment)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(Path(directory) / "math.exe")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
