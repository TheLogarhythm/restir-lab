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

    def compile_and_run(self, source, spatial_header=None):
        with tempfile.TemporaryDirectory() as directory:
            if spatial_header is not None:
                (Path(directory) / "spatial_under_test.h").write_text(spatial_header)
            result = subprocess.run([self.compiler, "/nologo", "/EHsc", "/std:c++17",
                str(ROOT / "tests" / source), "/I" + str(PAYLOAD), "/I" + directory,
                "/Fe:" + str(Path(directory) / "math.exe"),
                "/Fo:" + str(Path(directory) / "math.obj")], cwd=directory, capture_output=True, text=True, env=self.environment)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(Path(directory) / "math.exe")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
