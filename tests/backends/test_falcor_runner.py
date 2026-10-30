"""Portable contracts for the independent Falcor adapter."""

import importlib.util
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import types

ROOT = Path(__file__).resolve().parents[2]


def module():
    return importlib.import_module("scripts.falcor.run")


class FalcorRunnerTests(unittest.TestCase):
    def test_build_refuses_surviving_renderer_before_mutation(self):
        b = importlib.import_module("scripts.falcor.build")
        process = importlib.import_module("scripts.falcor.process_utils")
        # A killed launcher releases its lock, but its Windows renderer can survive.
        with patch.object(
            process, "os", types.SimpleNamespace(name="nt")
        ), patch.object(
            b.subprocess, "check_output", return_value="12345\n"
        ), patch.object(
            b, "ensure_source", side_effect=RuntimeError("mutable setup reached")
        ) as initialize:
            with self.assertRaisesRegex(RuntimeError, "Another renderer is active"):
                b._build(types.SimpleNamespace(check_only=False, jobs=4))
            initialize.assert_not_called()

    def test_dependency_download_failure_can_be_retried(self):
        b = importlib.import_module("scripts.falcor.build")
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            origin = folder / "origin"
            subprocess.run(
                ["git", "init", str(origin)], check=True, capture_output=True
            )
            (origin / "header.h").write_text("// pinned dependency\n")
            subprocess.run(
                ["git", "-C", str(origin), "add", "header.h"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(origin),
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "-m",
                    "fixture",
                ],
                check=True,
                capture_output=True,
            )
            commit = subprocess.check_output(
                ["git", "-C", str(origin), "rev-parse", "HEAD"], text=True
            ).strip()
            pin = {
                "cmake_dependencies": {
                    "testdep": {"repository": str(origin), "commit": commit}
                }
            }
            failed_once = False

            def run(command, phase):
                nonlocal failed_once
                if phase.endswith("-fetch") and not failed_once:
                    failed_once = True
                    raise RuntimeError("download interrupted")
                subprocess.run(command, check=True, capture_output=True)

            with patch.object(b, "OUTPUT", folder / "build"):
                with self.assertRaisesRegex(RuntimeError, "interrupted"):
                    b.prepare_cmake_dependencies(pin, run)
                result = b.prepare_cmake_dependencies(pin, run)
                installed = folder / "build/deps/testdep"
                self.assertEqual(
                    (installed / "header.h").read_text(), "// pinned dependency\n"
                )
                self.assertEqual(
                    result,
                    ["-DFETCHCONTENT_SOURCE_DIR_TESTDEP=" + installed.as_posix()],
                )
                b.check_cmake_dependencies(pin)

    def test_run_keeps_build_record_and_uses_absolute_executable(self):
        m = module()
        b = importlib.import_module("scripts.falcor.build")
        config = {
            "width": 3,
            "height": 2,
            "frames": 1,
            "captures": [1],
            "timeout": 5,
            "mode": "path-tracer",
        }
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            files = {
                "scenes/configs/falcor/cornell-box.pyscene": "# scene\n",
                "renderers/rtxdi/Assets/Media/CornellBox/CornellBox.gltf": "{}",
                "scripts/falcor/run.py": "# launcher\n",
                "scripts/falcor/graphs.py": "# captured graph source\n",
                "build/falcor/build.json": json.dumps(
                    {"commit": "a" * 40, "executable": "bin/Mogwai.exe"}
                ),
            }
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(data)
            record_path = root / "build/falcor/build.json"
            original_record = record_path.read_bytes()
            build_record = json.loads(original_record)
            out = root / "runs/test"

            def execute(command, output, timeout, *, prepare, **kwargs):
                output.mkdir(parents=True)
                prepare(output)
                self.assertTrue(Path(command[0]).is_absolute())
                return output / "manifest.json"

            with patch.object(m, "ROOT", root), patch.object(
                m, "__file__", str(root / "scripts/falcor/run.py")
            ), patch.dict(sys.modules, {"build": b}), patch.object(
                b, "verify_build", return_value=build_record
            ), patch.object(
                m.subprocess, "check_output", return_value=""
            ), patch.object(
                m, "version", return_value="fixture"
            ), patch.object(
                m, "execute", side_effect=execute
            ):
                m.launch(config, out, Path(os.path.relpath(root / "bin/Mogwai.exe")))
            record_path.write_text('{"replacement": true}')
            self.assertEqual((out / "build.json").read_bytes(), original_record)
            self.assertEqual(
                (out / "graphs.py").read_text(), "# captured graph source\n"
            )

    def test_timeout_falls_back_when_tree_termination_fails(self):
        m = module()
        child = Mock(pid=123456789, returncode=None)
        killed = False

        def wait(timeout=None):
            if killed:
                child.returncode = -9
                return -9
            if timeout is None:
                raise AssertionError("cleanup must never wait without a timeout")
            raise subprocess.TimeoutExpired("renderer", timeout)

        def kill():
            nonlocal killed
            killed = True

        child.wait.side_effect = wait
        child.kill.side_effect = kill
        child.poll.side_effect = lambda: child.returncode
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / "failed-tree-kill"
            with patch.object(m.subprocess, "Popen", return_value=child), patch.object(
                m.subprocess, "run", side_effect=OSError("tree termination unavailable")
            ):
                with self.assertRaisesRegex(TimeoutError, "exceeded timeout"):
                    m.execute(["renderer"], output, 0.1)
            record = json.loads((output / "manifest.json").read_text())
            self.assertEqual(record["status"], "failed")
            self.assertTrue(killed)

    def test_cleanup_failure_keeps_original_error_and_failed_manifest(self):
        m = module()
        child = Mock(pid=123456789)
        child.poll.return_value = None
        child.wait.side_effect = subprocess.TimeoutExpired("renderer", 0.1)
        child.kill.side_effect = PermissionError("cannot kill child")
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / "cleanup-failure"
            with patch.object(m.subprocess, "Popen", return_value=child), patch.object(
                m.subprocess, "run", side_effect=OSError("tree termination unavailable")
            ):
                with self.assertRaisesRegex(TimeoutError, "exceeded timeout"):
                    m.execute(["renderer"], output, 0.1)
            record = json.loads((output / "manifest.json").read_text())
            self.assertEqual(record["status"], "failed")
            self.assertIn("exceeded timeout", record["error"])
            self.assertTrue(record["cleanup_error"])

    def test_build_verification_rejects_uninitialized_submodule(self):
        b = importlib.import_module("scripts.falcor.build")
        pin = json.loads(b.PIN.read_text())
        record = {
            "commit": pin["commit"],
            "pin_sha256": b.sha(b.PIN),
            "executable": "Mogwai.exe",
            "files": {},
        }
        with tempfile.TemporaryDirectory() as d:
            output = Path(d)
            (output / "build.json").write_text(json.dumps(record))
            with patch.object(b, "OUTPUT", output), patch.object(
                b, "source_check", return_value=pin
            ), patch.object(b, "check_cmake_dependencies"), patch.object(
                b, "check_runtime_files"
            ), patch.object(
                b, "git", return_value="-" + "a" * 40 + " external/pybind11"
            ):
                with self.assertRaisesRegex(RuntimeError, "submodule"):
                    b.verify_build()

    def test_invalid_mode_or_frame_schedule_rejected(self):
        m = module()
        good = {
            "width": 320,
            "height": 180,
            "frames": 16,
            "captures": [1, 16],
            "timeout": 600,
            "mode": "path-tracer",
        }
        self.assertEqual(m.validate_config(good), good)
        for override in (
            {"mode": "wrong"},
            {"frames": 0},
            {"captures": [0]},
            {"captures": [2, 1]},
            {"timeout": 0},
            {"width": True},
        ):
            with self.assertRaises(ValueError):
                m.validate_config(dict(good, **override))

    def test_existing_output_is_preserved(self):
        m = module()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "keep").write_text("preserve")
            with self.assertRaises(FileExistsError):
                m.execute([sys.executable, "-c", "pass"], p, 1)
            self.assertEqual((p / "keep").read_text(), "preserve")

    def test_paths_with_spaces(self):
        m = module()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "output with spaces"
            m.execute([sys.executable, "-c", "print('finished')"], p, 5)
            self.assertIn("finished", (p / "renderer.log").read_text())

    def test_nonzero_exit_retains_failed_manifest(self):
        m = module()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "failed"
            with self.assertRaises(RuntimeError):
                m.execute([sys.executable, "-c", "raise SystemExit(7)"], p, 5)
            self.assertEqual(
                json.loads((p / "manifest.json").read_text())["status"], "failed"
            )

    def test_timeout_preserves_unrelated_process(self):
        m = module()
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time;time.sleep(20)"]
        )
        try:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "timeout"
                with self.assertRaises(TimeoutError):
                    m.execute(
                        [sys.executable, "-c", "import time;time.sleep(20)"], p, 0.3
                    )
                self.assertIsNone(unrelated.poll())
                self.assertEqual(
                    json.loads((p / "manifest.json").read_text())["status"], "failed"
                )
        finally:
            unrelated.terminate()
            unrelated.wait()

    def test_missing_or_invalid_hdr_fails_after_zero_exit(self):
        m = module()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "missing"

            def verify(_):
                raise ValueError("Missing HDR")

            with self.assertRaises(ValueError):
                m.execute([sys.executable, "-c", "pass"], p, 5, verify=verify)
            self.assertEqual(
                json.loads((p / "manifest.json").read_text())["status"], "failed"
            )

    def test_falcor_layout_outside_frozen_sources(self):
        for p in (ROOT / "scripts/falcor").rglob("*.py"):
            self.assertFalse(p.is_relative_to(ROOT / "scripts/run"))
            self.assertFalse(p.is_relative_to(ROOT / "scripts/analysis"))
        self.assertFalse(list((ROOT / "scenes/configs/falcor").glob("*.json")))

    def test_graph_exports_unaccumulated_linear_color(self):
        spec = importlib.util.spec_from_file_location(
            "falcor_graphs", ROOT / "scripts/falcor/graphs.py"
        )
        graphs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(graphs)

        class Graph:
            def __init__(self, name):
                self.passes = {}
                self.edges = []
                self.outputs = []

            def addPass(self, p, name):
                self.passes[name] = p

            def addEdge(self, a, b):
                self.edges.append((a, b))

            def markOutput(self, name):
                self.outputs.append(name)

        api = types.SimpleNamespace(
            RenderGraph=Graph, createPass=lambda name, opts: (name, opts)
        )
        with patch.dict(sys.modules, {"falcor": api}):
            for mode in ("path-tracer", "restir-pt"):
                g = graphs.build_graph(mode)
                self.assertEqual(set(g.passes), {"VBufferRT", "PathTracer"})
                self.assertEqual(g.outputs, ["PathTracer.color"])
                opts = g.passes["PathTracer"][1]
                self.assertEqual(opts["samplesPerPixel"], 1)
                self.assertNotIn("usePairedNeighbors", opts)
                self.assertEqual(opts["useReSTIRPT"], mode == "restir-pt")

    def test_exr_type_and_nonfinite_validation(self):
        import OpenEXR
        import numpy as np

        m = module()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "fixture.exr"
            for value, dtype, valid in (
                (1, np.float32, True),
                (1, np.float16, False),
                (float("nan"), np.float32, False),
                (0, np.float32, False),
            ):
                rgb = np.full((2, 3, 3), value, dtype=dtype)
                OpenEXR.File({}, {"RGB": rgb}).write(str(p))
                if valid:
                    self.assertEqual(m.inspect_hdr(p, 3, 2).shape, (2, 3, 3))
                else:
                    with self.assertRaises(ValueError):
                        m.inspect_hdr(p, 3, 2)

    def test_generated_script_sets_camera_and_capture_schedule(self):
        m = module()
        config = {"mode": "restir-pt", "frames": 16, "captures": [1, 16]}
        script = m.renderer_script(
            config,
            ROOT / "runs/falcor/test space",
            ROOT / "scenes/configs/falcor/cornell-box.pyscene",
        )
        compile(script, "render.py", "exec")
        self.assertIn("camera.position", script)
        self.assertIn("camera.focalLength", script)
        self.assertIn("range(1,17)", script)
        self.assertIn("[1, 16]", script)
        self.assertIn("resolved-camera.json", script)
        self.assertNotIn("m.saveConfig(", script)
        self.assertIn("g.print()", script)

    def test_capture_filenames_match_requested_frames(self):
        m = module()
        good = [
            Path("capture.PathTracer.color.1.exr"),
            Path("capture.PathTracer.color.16.exr"),
        ]
        self.assertEqual(m.capture_frames(good, [1, 16]), [1, 16])
        for bad in (
            [good[0]],
            [good[0], Path("capture.PathTracer.color.15.exr")],
            [good[0], Path("unexpected.exr")],
        ):
            with self.assertRaises(ValueError):
                m.capture_frames(bad, [1, 16])

    def test_build_preflight_rejects_wrong_pin_and_dirty_source(self):
        b = importlib.import_module("scripts.falcor.build")
        pin = json.loads(b.PIN.read_text())
        with patch.object(b, "git", return_value="0" * 40):
            with self.assertRaisesRegex(RuntimeError, "revision"):
                b.source_check()
        with patch.object(b, "git", side_effect=[pin["commit"], " M Source/keep.cpp"]):
            with self.assertRaisesRegex(RuntimeError, "source"):
                b.source_check()

    def test_build_rejects_spaces_before_bootstrap(self):
        b = importlib.import_module("scripts.falcor.build")
        with self.assertRaisesRegex(RuntimeError, "spaces"):
            b.check_build_path(Path("C:/checkout with spaces/Falcor"))

    def test_build_interrupt_ends_owned_process_tree(self):
        from unittest.mock import Mock

        b = importlib.import_module("scripts.falcor.build")
        child = Mock(pid=123456789)
        child.wait.side_effect = [KeyboardInterrupt(), 0]
        child.poll.return_value = None
        with tempfile.TemporaryDirectory() as d:
            with patch.object(b.subprocess, "Popen", return_value=child), patch.object(
                b.subprocess, "run"
            ) as kill:
                with self.assertRaises(KeyboardInterrupt):
                    b.run_phase(["owned-child"], Path(d), {}, Path(d) / "phase.log")
                if b.os.name == "nt":
                    self.assertEqual(
                        kill.call_args.args[0],
                        ["taskkill", "/PID", "123456789", "/T", "/F"],
                    )
                else:
                    child.kill.assert_called_once()
                self.assertTrue((Path(d) / "phase.log").is_file())

    def test_source_initialization_preserves_nonempty_wrong_checkout(self):
        b = importlib.import_module("scripts.falcor.build")
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "source"
            folder.mkdir()
            (folder / "keep").write_text("keep")
            with patch.object(b, "SOURCE", folder), patch.object(
                b, "source_check", side_effect=RuntimeError("revision differs")
            ), patch.object(b.subprocess, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "revision"):
                    b.ensure_source()
                run.assert_not_called()
                self.assertEqual((folder / "keep").read_text(), "keep")

    def test_interactive_smoke_holds_after_finite_render_loop(self):
        m = module()
        script = m.renderer_script(
            {"mode": "path-tracer", "frames": 16, "captures": [1, 16]},
            ROOT / "runs/falcor/ui",
            ROOT / "scene.pyscene",
            interactive=True,
        )
        self.assertIn("time.sleep(30)", script)
        self.assertLess(
            script.index("m.frameCapture.capture()"), script.index("time.sleep(30)")
        )
        self.assertEqual(script.count("m.renderFrame()"), 1)

    def test_build_requires_runtime_deployment(self):
        b = importlib.import_module("scripts.falcor.build")
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            (directory / "plugins").mkdir()
            (directory / "Mogwai.exe").touch()
            (directory / "plugins/PathTracer.dll").touch()
            with self.assertRaisesRegex(RuntimeError, "runtime"):
                b.check_runtime_files(directory)

    def test_script_executes_with_noniterable_native_vectors(self):
        import contextlib, io

        m = module()
        captures = []
        rendered = []
        camera = types.SimpleNamespace()
        clock = types.SimpleNamespace(pause=lambda: None, time=0, frame=0)
        fc = types.SimpleNamespace(capture=lambda: captures.append(clock.frame))
        renderer = types.SimpleNamespace(
            addGraph=lambda g: None,
            loadScene=lambda s: None,
            scene=types.SimpleNamespace(camera=camera),
            clock=clock,
            frameCapture=fc,
            renderFrame=lambda: rendered.append(clock.frame),
        )
        vector = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / "graphs.py").write_text(
                "from types import SimpleNamespace\ndef build_graph(mode):\n    return SimpleNamespace(print=lambda: print('# snapshotted graph'))\n"
            )
            script = m.renderer_script(
                {"mode": "path-tracer", "frames": 16, "captures": [1, 16]},
                out,
                ROOT / "scene.pyscene",
            )
            with patch.dict(
                sys.modules, {"falcor": types.SimpleNamespace(float3=vector)}
            ), patch.object(sys, "path", list(sys.path)), contextlib.redirect_stdout(
                io.StringIO()
            ):
                sys.modules.pop("graphs", None)
                exec(script, {"m": renderer, "exit": lambda: None})
            self.assertEqual(captures, [1, 16])
            self.assertEqual(rendered, list(range(1, 17)))
            self.assertEqual(
                json.loads((out / "resolved-camera.json").read_text())["position"],
                [0, 5, -15],
            )
            self.assertEqual((out / "resolved.py").read_text(), "# snapshotted graph\n")


if __name__ == "__main__":
    unittest.main()
