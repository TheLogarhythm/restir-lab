"""Exercise build rollback with a small fake renderer, without invoking CMake."""
from contextlib import ExitStack, nullcontext
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))
import build_rtxdi_experiments as builder


class BuildRecoveryTests(unittest.TestCase):
    def run_build(self, root, *, fail_restore=False, fail_compile=True, reference=False):
        renderer = root / "renderer"
        build = renderer / "build"
        binary = build / "bin"
        shaders = binary / "shaders/full-sample"
        shaders.mkdir(parents=True)
        source = renderer / "source.cpp"
        official = binary / "FullSample.exe"
        for path, data in ((source, b"source"), (renderer / "importer.cpp", b"importer"), (official, b"official"),
                           (shaders / "original.bin", b"shader"),
                           (build / "CMakeCache.txt", b"cache")):
            path.write_bytes(data)
        script = root / "build.py"
        patch = root / "integration.patch"
        helper = root / "helper.h"
        for path in (script, patch, helper):
            path.write_text("fixture")
        destination = renderer / "helper.h"
        real_copy = builder.shutil.copy2

        def copy(source_path, target_path, *args, **kwargs):
            if fail_restore and Path(source_path).name == "official.exe" and Path(target_path) == official:
                raise OSError("restore blocked")
            return real_copy(source_path, target_path, *args, **kwargs)

        def command(*args, **kwargs):
            if args[0] == "cmake":
                source.write_bytes(b"modified")
                official.write_bytes(b"variant")
                if fail_compile or reference:
                    (shaders / "original.bin").write_bytes(b"changed")
                    (shaders / "added.bin").write_bytes(b"extra")
                if fail_compile:
                    raise RuntimeError("compile failed")

        constants = {"ROOT": root, "RENDERER": renderer, "BUILD": build, "BIN": binary,
                     "FILES": ["source.cpp"], "PATCH": patch, "HELPER": helper,
                     "DEST": destination, "__file__": str(script), "SUPPORT_FILE": helper, "BUILD_SUPPORT_FILE": helper, "IMPORTER": Path("importer.cpp"),
                     "REFERENCE_FILES": [], "REFERENCE_SHADER": helper}
        with ExitStack() as stack:
            for name, value in constants.items():
                stack.enter_context(mock.patch.object(builder, name, value))
            stack.enter_context(mock.patch.object(sys, "argv", [str(script)] + (["--reference"] if reference else [])))
            stack.enter_context(mock.patch.object(builder, "run", side_effect=command))
            stack.enter_context(mock.patch.object(builder, "adapt_reference"))
            stack.enter_context(mock.patch.object(builder, "require_clean_renderer"))
            stack.enter_context(mock.patch.object(builder, "checked_submodule",
                return_value={"commit": "donut-revision", "source_sha256": {"src/engine/GltfImporter.cpp": "source-hash"}}))
            stack.enter_context(mock.patch.object(builder, "emission_support", return_value=nullcontext()))
            stack.enter_context(mock.patch.object(builder.shutil, "copy2", side_effect=copy))
            stack.enter_context(mock.patch.object(builder.subprocess, "check_output",
                side_effect=lambda command, **kw: "" if command[0] == "powershell" else "revision"))
            with self.assertRaises((RuntimeError, OSError)) if fail_compile or fail_restore else nullcontext():
                builder.main()
        return renderer, build, binary, shaders

    def test_compile_failure_restores_exact_original_files(self):
        with tempfile.TemporaryDirectory() as folder:
            renderer, build, binary, shaders = self.run_build(Path(folder))
            self.assertEqual((renderer / "source.cpp").read_bytes(), b"source")
            self.assertEqual((binary / "FullSample.exe").read_bytes(), b"official")
            self.assertEqual({p.name: p.read_bytes() for p in shaders.iterdir()}, {"original.bin": b"shader"})
            self.assertFalse((renderer / "helper.h").exists())
            self.assertFalse((binary / "FullSampleExperiments.exe").exists())
            self.assertEqual(list(build.glob("experiment-build-*")), [])

    def test_failed_restore_keeps_recovery_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            renderer, build, binary, shaders = self.run_build(Path(folder), fail_restore=True)
            backups = list(build.glob("experiment-build-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "official.exe").read_bytes(), b"official")
            self.assertEqual((backups[0] / "sources/source.cpp").read_bytes(), b"source")
            self.assertEqual((backups[0] / "shaders/original.bin").read_bytes(), b"shader")
            self.assertEqual((renderer / "source.cpp").read_bytes(), b"source")
            self.assertEqual({p.name: p.read_bytes() for p in shaders.iterdir()}, {"original.bin": b"shader"})

    def test_success_publishes_variant_after_restoring_official_files(self):
        for reference in (False, True):
            with self.subTest(reference=reference), tempfile.TemporaryDirectory() as folder:
                renderer, build, binary, shaders = self.run_build(Path(folder), fail_compile=False, reference=reference)
                variant = binary / ("FullSampleReference.exe" if reference else "FullSampleExperiments.exe")
                self.assertEqual(variant.read_bytes(), b"variant")
                self.assertEqual((renderer / "source.cpp").read_bytes(), b"source")
                self.assertEqual((binary / "FullSample.exe").read_bytes(), b"official")
                self.assertEqual({p.name: p.read_bytes() for p in shaders.iterdir()}, {"original.bin": b"shader"})
                record = json.loads(variant.with_suffix(".build.json").read_text())
                self.assertEqual(record["executable_sha256"], builder.sha(variant))
                self.assertEqual(record["donut"]["commit"], "donut-revision")
                self.assertEqual(record["donut"]["source_sha256"]["src/engine/GltfImporter.cpp"], "source-hash")
                self.assertEqual(record["shader_sha256"], builder.tree_hashes(binary / record["shader_directory"]))
                if reference:
                    self.assertEqual((binary / record["shader_directory"] / "added.bin").read_bytes(), b"extra")
                self.assertEqual(list(build.glob("experiment-build-*")), [])


if __name__ == "__main__":
    unittest.main()
