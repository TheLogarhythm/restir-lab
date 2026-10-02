"""Build signatures reject stale adapters; rollback attempts every resource."""
from pathlib import Path
from contextlib import ExitStack
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/run"))
from rtxdi_build import integration_hashes, validate_integration, restore_renderer
import rtxdi_build as build_support


class BuildSupportTests(unittest.TestCase):
    def test_changed_adapter_requires_rebuild(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            adapter = root / "adapter.py"
            adapter.write_text("old")
            record = {"integration_sha256": integration_hashes([adapter], root)}
            validate_integration(record, root, [adapter])
            adapter.write_text("new")
            with self.assertRaisesRegex(RuntimeError, "rebuild"):
                validate_integration(record, root, [adapter])

    def test_legacy_record_cannot_skip_required_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaisesRegex(RuntimeError, "rebuild"):
                validate_integration({"integration_sha256": {}}, root, [root / "adapter.py"])

    def test_failed_source_restore_still_restores_binary_and_shaders(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            backup = root / "backup"
            (backup / "sources").mkdir(parents=True)
            (backup / "sources/source.cpp").write_bytes(b"original source")
            (backup / "official.exe").write_bytes(b"original exe")
            (backup / "shaders").mkdir()
            (backup / "shaders/a.bin").write_bytes(b"original shader")
            exe = root / "app.exe"
            exe.write_bytes(b"modified")
            shaders = root / "shaders"
            shaders.mkdir()
            (shaders / "extra.bin").write_bytes(b"extra")
            import shutil
            copy = shutil.copy2
            def fail_source(source, destination, *args, **kwargs):
                if Path(source).name == "source.cpp":
                    raise OSError("blocked")
                return copy(source, destination, *args, **kwargs)
            with patch("rtxdi_build.shutil.copy2", side_effect=fail_source):
                with self.assertRaisesRegex(RuntimeError, "retained"):
                    restore_renderer(backup, root, ["source.cpp"], exe, shaders)
            self.assertEqual(exe.read_bytes(), b"original exe")
            self.assertEqual((shaders / "a.bin").read_bytes(), b"original shader")
            self.assertFalse((shaders / "extra.bin").exists())
            self.assertTrue((backup / "sources/source.cpp").exists())


class BuildIsolationTests(unittest.TestCase):
    def test_builders_reject_unrecorded_sources_before_backup(self):
        import build_rtxdi_experiments
        import build_rtxdi_external
        for builder in (build_rtxdi_experiments, build_rtxdi_external):
            for change in ("unstaged", "staged", "untracked", "dependency"):
                with self.subTest(builder=builder.__name__, change=change), tempfile.TemporaryDirectory() as folder:
                    root = Path(folder)
                    donut, importer, _ = self.fixture(root)
                    source = root / "source.cpp"
                    other = root / "other.cpp"
                    source.write_text("patched source")
                    other.write_text("unrelated source")
                    (root / ".gitignore").write_text("build/\n")
                    self.git(root, "add", "source.cpp", "other.cpp", ".gitignore")
                    self.git(root, "commit", "-qm", "sources")
                    build = root / "build"
                    build.mkdir()
                    (build / "FullSample.exe").write_bytes(b"official")
                    (build / "CMakeCache.txt").write_bytes(b"cache")
                    build_support.require_clean_renderer(root)
                    if change == "dependency":
                        importer.write_bytes(b"edited dependency")
                    elif change == "untracked":
                        (root / "new.cpp").write_text("new source")
                    else:
                        other.write_text("local edit")
                        if change == "staged":
                            self.git(root, "add", "other.cpp")
                    with ExitStack() as stack:
                        for name, value in {"ROOT": root, "RENDERER": root, "BUILD": build, "BIN": build,
                                            "PATCH": source, "SUPPORT_FILE": source, "BUILD_SUPPORT_FILE": source,
                                            "__file__": str(source)}.items():
                            stack.enter_context(patch.object(builder, name, value))
                        if builder is build_rtxdi_experiments:
                            for name, value in {"FILES": ["source.cpp"], "HELPER": source,
                                                "DEST": root / "helper.h"}.items():
                                stack.enter_context(patch.object(builder, name, value))
                            stack.enter_context(patch.object(sys, "argv", ["builder"]))
                        else:
                            stack.enter_context(patch.object(builder, "SOURCE", source))
                        check_output = subprocess.check_output
                        stack.enter_context(patch.object(builder.subprocess, "check_output",
                            side_effect=lambda args, **kw: "" if args[0] == "powershell" else check_output(args, **kw)))
                        # No compilation or source patching; reaching backup is already a failure.
                        stack.enter_context(patch.object(builder, "run"))
                        stack.enter_context(patch.object(builder, "backup_renderer",
                            side_effect=AssertionError("Dirty inputs reached the build stage")))
                        with self.assertRaisesRegex(RuntimeError, "local changes"):
                            builder.main()

    def test_restored_sources_are_newer_than_variant_objects(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            backup = root / "backup"
            files = ["Samples/FullSample/Source/App/SceneRenderer.cpp",
                     "External/donut/src/engine/GltfImporter.cpp"]
            for name in files:
                original = backup / "sources" / name
                original.parent.mkdir(parents=True, exist_ok=True)
                original.write_bytes(b"official source")
                os.utime(original, (1000000000, 1000000000))
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"variant source")
            (backup / "official.exe").write_bytes(b"official exe")
            (backup / "shaders").mkdir()
            shaders = root / "shaders"
            shaders.mkdir()
            variant_object = root / "variant.obj"
            variant_object.write_bytes(b"compiled patched source")
            os.utime(variant_object, (1000000100, 1000000100))
            official = root / "FullSample.exe"
            restore_renderer(backup, root, files, official, shaders)
            for name in files:
                with self.subTest(source=name):
                    self.assertEqual((root / name).read_bytes(), b"official source")
                    self.assertGreater((root / name).stat().st_mtime_ns,
                                       variant_object.stat().st_mtime_ns)
            self.assertEqual(official.read_bytes(), b"official exe")

    def git(self, root, *args):
        return subprocess.check_output([
            "git", "-c", "user.name=Build Test", "-c", "user.email=build-test@example.invalid",
            "-c", "core.hooksPath=" + str(root / "unused-hooks"), *args],
            cwd=root, text=True, stderr=subprocess.PIPE).strip()

    def fixture(self, root):
        self.git(root, "init", "-q")
        donut = root / "External/donut"
        donut.mkdir(parents=True)
        self.git(donut, "init", "-q")
        source = donut / "src/engine/GltfImporter.cpp"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"official importer")
        self.git(donut, "add", "src/engine/GltfImporter.cpp")
        self.git(donut, "commit", "-qm", "fixture")
        revision = self.git(donut, "rev-parse", "HEAD")
        self.git(root, "update-index", "--add", "--cacheinfo",
                 "160000," + revision + ",External/donut")
        self.git(root, "commit", "-qm", "pin fixture dependency")
        return donut, source, revision

    def test_checked_submodule_records_pinned_revision_and_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, source, revision = self.fixture(root)
            record = build_support.checked_submodule(root, "External/donut", ["src/engine/GltfImporter.cpp"])
            self.assertEqual(record["commit"], revision)
            self.assertEqual(record["source_sha256"], {"src/engine/GltfImporter.cpp": build_support.sha(source)})

    def test_checked_submodule_rejects_staged_and_unstaged_edits(self):
        for staged in (False, True):
            with self.subTest(staged=staged), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                donut, source, _ = self.fixture(root)
                source.write_bytes(b"local edit")
                if staged:
                    self.git(donut, "add", "src/engine/GltfImporter.cpp")
                with self.assertRaisesRegex(RuntimeError, "local changes"):
                    build_support.checked_submodule(root, "External/donut", ["src/engine/GltfImporter.cpp"])

    def test_checked_submodule_rejects_clean_but_unpinned_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            donut, source, _ = self.fixture(root)
            source.write_bytes(b"different revision")
            self.git(donut, "add", "src/engine/GltfImporter.cpp")
            self.git(donut, "commit", "-qm", "advance dependency")
            with self.assertRaisesRegex(RuntimeError, "pinned"):
                build_support.checked_submodule(root, "External/donut", ["src/engine/GltfImporter.cpp"])
