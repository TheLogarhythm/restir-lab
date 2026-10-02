"""Launcher validation must happen before running a renderer or creating a run."""
from contextlib import nullcontext
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
            (exe.with_suffix(".build.json")).write_text(json.dumps({"executable_sha256": runner.sha(exe), "renderer_commit": "test-commit"}))
            observed = {}
            def execute(command, **kwargs):
                self.assertIn("--device.vk=0", command)
                self.assertIn("--camera.position=0.0 0.0 0.0", command)
                observed.update({k: v for k, v in kwargs["env"].items() if k.startswith("RTXDI_")})
                return subprocess.CompletedProcess(command, 0)
            argv = ["runner", "--scene", str(scene), "--camera-position", "0", "0", "0",
                    "--camera-direction", "0", "0", "1", "--interactive"]
            with patch.object(runner, "ROOT", root), patch.object(runner, "EXE", exe), \
                 patch.object(runner, "validate_integration"), \
                 patch.object(sys, "argv", argv), patch.dict(os.environ, {"RTXDI_EMISSIVE_SCALE": "99", "RTXDI_EXPOSURE_BIAS": "20"}, clear=True), \
                 patch.object(runner.subprocess, "check_output", return_value="test-commit"), \
                 patch.object(runner.subprocess, "run", side_effect=execute):
                self.assertEqual(runner.main(), 0)
            self.assertNotIn("RTXDI_EMISSIVE_SCALE", observed)
            self.assertNotIn("RTXDI_EXPOSURE_BIAS", observed)

    def test_stale_adapter_is_rejected_before_creating_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scene, exe = root / "scene.gltf", root / "sample.exe"
            scene.write_text('{"asset":{"version":"2.0"}}')
            exe.write_bytes(b"binary")
            required = [Path(runner.__file__).with_name("build_rtxdi_external.py"),
                        Path(runner.__file__).with_name("rtxdi_external.patch"),
                        runner.BUILD_SUPPORT_FILE, runner.EMISSION_SUPPORT_FILE]
            from rtxdi_build import integration_hashes
            record = {"executable_sha256": runner.sha(exe),
                      "integration_sha256": integration_hashes(required, ROOT)}
            record["integration_sha256"][runner.EMISSION_SUPPORT_FILE.relative_to(ROOT).as_posix()] = "stale"
            exe.with_suffix(".build.json").write_text(json.dumps(record))
            argv = ["runner", "--scene", str(scene), "--camera-position", "0", "0", "0",
                    "--camera-direction", "0", "0", "1", "--interactive"]
            with patch.object(runner, "EXE", exe), patch.object(sys, "argv", argv), patch.object(runner.subprocess, "run") as launch:
                with self.assertRaisesRegex(RuntimeError, "Integration changed"):
                    runner.main()
                launch.assert_not_called()

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
            (root / "importer.cpp").write_bytes(b"importer")
            (root / "shaders/full-sample").mkdir(parents=True)
            fixture = root / "build.py"
            fixture.write_text("fixture")
            def fail_build(*command, **kwargs):
                if command[0] == "cmake":
                    exe.write_bytes(b"partial variant")
                    raise subprocess.CalledProcessError(1, command)
            with patch.object(builder, "ROOT", root), patch.object(builder, "RENDERER", root), \
                 patch.object(builder, "SOURCE", source), patch.object(builder, "BUILD", root), \
                 patch.object(builder, "emission_support", return_value=nullcontext()), \
                 patch.object(builder, "checked_submodule", return_value={"commit": "test-donut"}), \
                 patch.object(builder, "require_clean_renderer"), \
                 patch.object(builder, "BIN", root), patch.object(builder, "run", side_effect=fail_build), \
                 patch.object(builder, "IMPORTER", Path("importer.cpp")), \
                 patch.object(builder, "PATCH", fixture), patch.object(builder, "SUPPORT_FILE", fixture), \
                 patch.object(builder, "BUILD_SUPPORT_FILE", fixture), patch.object(builder, "__file__", str(fixture)), \
                 patch.object(builder.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)), \
                 patch.object(builder.subprocess, "check_output", side_effect=lambda cmd, **kw: "" if cmd[0] == "powershell" else "test-commit"):
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
                 patch.object(runner, "validate_integration"), \
                 patch.object(sys, "argv", argv), patch.object(runner.subprocess, "check_output", return_value="test-commit"):
                with self.assertRaises(SystemExit):
                    runner.main()
            self.assertFalse((root / "runs").exists())


if __name__ == "__main__":
    unittest.main()
