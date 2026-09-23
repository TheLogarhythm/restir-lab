"""Launcher validation must happen before running a renderer or creating a run."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))
import rtxdi_external as runner
import build_rtxdi_external as builder
from rtxdi_common import validate_bmp


class ExternalRunnerTests(unittest.TestCase):
    def test_inherited_render_overrides_do_not_leak_into_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scene, exe = root / "scene.gltf", root / "sample.exe"
            scene.write_text('{"asset":{"version":"2.0"}}')
            exe.write_bytes(b"test binary")
            (exe.with_suffix(".build.json")).write_text(json.dumps({"executable_sha256": runner.sha(exe)}))
            observed = {}
            def execute(command, **kwargs):
                observed.update({k: v for k, v in kwargs["env"].items() if k.startswith("RTXDI_")})
                return subprocess.CompletedProcess(command, 0)
            argv = ["runner", "--scene", str(scene), "--camera-position", "0", "0", "0",
                    "--camera-direction", "0", "0", "1", "--interactive"]
            with patch.object(runner, "ROOT", root), patch.object(runner, "EXE", exe), \
                 patch.object(sys, "argv", argv), patch.dict(os.environ, {"RTXDI_EMISSIVE_SCALE": "99", "RTXDI_EXPOSURE_BIAS": "20"}, clear=True), \
                 patch.object(runner.subprocess, "check_output", return_value="test-commit"), \
                 patch.object(runner.subprocess, "run", side_effect=execute):
                self.assertEqual(runner.main(), 0)
            self.assertNotIn("RTXDI_EMISSIVE_SCALE", observed)
            self.assertNotIn("RTXDI_EXPOSURE_BIAS", observed)

    def test_truncated_capture_is_a_controlled_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "capture.bmp"
            image.write_bytes(b"BM")
            with self.assertRaisesRegex(RuntimeError, "truncated"):
                validate_bmp(image, (640, 360))

    def test_failed_variant_build_restores_official_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "SceneRenderer.cpp"
            original = builder.SOURCE.read_bytes()
            source.write_bytes(original)
            exe = root / "FullSample.exe"
            exe.write_bytes(b"official binary")
            def fail_build(*command, **kwargs):
                if command[0] == "cmake":
                    exe.write_bytes(b"partial variant")
                    raise subprocess.CalledProcessError(1, command)
            with patch.object(builder, "ROOT", root), patch.object(builder, "RENDERER", root), \
                 patch.object(builder, "SOURCE", source), patch.object(builder, "BUILD", root), \
                 patch.object(builder, "BIN", root), patch.object(builder, "run", side_effect=fail_build), \
                 patch.object(builder.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)), \
                 patch.object(builder.subprocess, "check_output", return_value="test-commit"):
                with self.assertRaises(subprocess.CalledProcessError):
                    builder.main()
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(exe.read_bytes(), b"official binary")

    def test_invalid_parameters_do_not_create_run_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scene, exe = root / "scene.gltf", root / "sample.exe"
            scene.write_text('{}'); exe.write_bytes(b"binary")
            argv = ["runner", "--scene", str(scene), "--camera-position", "0", "0", "0",
                    "--camera-direction", "0", "0", "0", "--emissive-scale", "-1"]
            with patch.object(runner, "ROOT", root), patch.object(runner, "EXE", exe), \
                 patch.object(sys, "argv", argv), patch.object(runner.subprocess, "check_output", return_value="test-commit"):
                with self.assertRaises(SystemExit):
                    runner.main()
            self.assertFalse((root / "runs").exists())


if __name__ == "__main__":
    unittest.main()
