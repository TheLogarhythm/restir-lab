"""Check that the private core runtime owns Slang compile requests and relinks privately."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts.falcor import live_core_runtime as core
from tests.fixtures.cpp import compiler_environment


class LiveCoreRuntimeTests(unittest.TestCase):
    def test_compile_request_owns_frontend_and_program_keeps_session(self):
        source = core.SOURCE.read_text(encoding="utf8")
        patched = core.patch_source(source)
        version = patched.split("ProgramManager::createProgramVersion", 1)[1].split(
            "ProgramManager::createProgramKernels", 1
        )[0]
        self.assertIn("SlangRequest requestOwner(createRequest(), spDestroyCompileRequest);", version)
        self.assertIn("return createSlangCompileRequest(program);", version)
        self.assertIn("make_ref<SessionProgramVersion>(pSlangSession", version)
        self.assertIn("private SlangSessionOwner, public ProgramVersion", patched)
        self.assertNotIn("spDestroyCompileRequest(pSlangRequest);", version)
        self.assertIn("return requestOwner.release();", patched)
        with self.assertRaisesRegex(ValueError, "anchor"):
            core.patch_source(patched)

    def test_shared_module_sessions_are_bounded_and_invalidated(self):
        patched = core.patch_source(core.SOURCE.read_text(encoding="utf8"))
        self.assertIn("getSessionDescDigest(&desc", patched)
        self.assertIn("module.name.empty()", patched)
        self.assertIn("module.sources.front().type == ProgramDesc::ShaderSource::Type::File", patched)
        self.assertIn("module.sources.size() == 1", patched)
        self.assertIn("findFileInShaderDirectories(module.sources.front().path, resolved)", patched)
        self.assertIn("roots.push_back(resolved.string());", patched)
        self.assertIn("entry.key == key && entry.roots == roots", patched)
        self.assertIn("generation != currentGeneration", patched)
        self.assertIn("if (entries.size() == 4)", patched)
        for method in ("reloadAllPrograms", "setHlslLanguagePrelude", "unregisterProgramForReload"):
            body = patched.split("ProgramManager::" + method + "(", 1)[1].split("\n}", 1)[0]
            self.assertIn("gLiveSlangCache.clear();", body)

    def test_persistent_ir_with_pinned_slang_sdk(self):
        sdk = core.UPSTREAM / "external/packman/slang"
        if not all((sdk / name).is_file() for name in ("lib/slang.lib", "bin/slang.dll")):
            self.skipTest("Pinned Falcor Slang SDK is not installed")
        compiler, environment = compiler_environment()
        source = core.ROOT / "tests/falcor/live_slang_disk_cache.cpp"
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "live_slang_disk_cache.exe"
            built = subprocess.run(
                [compiler, "/nologo", "/EHsc", "/MD", "/std:c++17", "/I" + str(sdk / "include"),
                 str(source), "/Fe:" + str(executable), "/link", str(sdk / "lib/slang.lib")],
                cwd=directory, env=environment, text=True, capture_output=True, timeout=90,
            )
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            shutil.copy2(sdk / "bin/slang.dll", directory)
            args = [str(executable), str(Path(directory) / "fixture")]
            runtime = core.STOCK.parent
            if all((runtime / name).is_file() for name in (
                "dxcompiler.dll", "dxil.dll", "shaders/Scene/Lights/UpdateTriangleVertices.cs.slang",
                "shaders/Rendering/Materials/StandardMaterial.slang",
            )):
                shutil.copy2(runtime / "dxcompiler.dll", directory)
                shutil.copy2(runtime / "dxil.dll", directory)
                args.append(str(runtime))
            run = subprocess.run(
                args,
                cwd=directory, env=environment, text=True, capture_output=True, timeout=90,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_release_recipes_retarget_selected_object_and_outputs(self):
        if not core.TLOG.is_dir():
            self.skipTest("Retained Falcor Release build records are not installed")
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            commands, link_command = core.release_commands(stage)
            compile_command = commands["ProgramManager.cpp"]
            self.assertNotIn("/Yu", compile_command)
            self.assertIn(str(stage / "ProgramManager.obj"), compile_command)
            self.assertIn(str(stage / "ProgramManager.cpp"), compile_command)
            self.assertIn(str(stage / "ProgramManager.obj"), link_command)
            self.assertIn(str(stage / "Falcor.dll"), link_command)
            self.assertIn(str(stage / "Falcor.lib"), link_command)
            self.assertIn(str(stage / "Falcor.pdb"), link_command)
            self.assertNotIn(r"FALCOR.DIR\RELEASE\PROGRAMMANAGER.OBJ", link_command)


if __name__ == "__main__":
    unittest.main()
