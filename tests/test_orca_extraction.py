"""ORCA extraction publishes a complete scene without replacing existing assets."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class OrcaExtractionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.archive = self.root / "source.zip"
        self.output = self.root / "prepared"
        self.files = {"README.txt": b"notice", "LICENSE.txt": b"license",
                      "MEASURE_SEVEN/scene.fbx": b"source scene",
                      "MEASURE_SEVEN/textures/map.dds": b"source texture",
                      "MEASURE_ONE/other.fbx": b"other scene"}
        with zipfile.ZipFile(self.archive, "w") as archive:
            for name, content in self.files.items():
                archive.writestr(name, content)

    def extract(self, *extra):
        return subprocess.run([sys.executable, "-B", str(ROOT / "scripts/assets/extract_orca.py"),
                               "--archive", str(self.archive), "--folder", "MEASURE_SEVEN",
                               "--output", str(self.output), *extra], capture_output=True, text=True)

    def test_pinned_archive_extracts_only_scene_and_notices(self):
        digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        result = self.extract("--expected-sha256", digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = {p.relative_to(self.output).as_posix(): p.read_bytes()
                  for p in self.output.rglob("*") if p.is_file()}
        self.assertEqual(actual, {k: v for k, v in self.files.items() if not k.startswith("MEASURE_ONE/")})

    def test_existing_output_is_never_overwritten(self):
        target = self.output / "MEASURE_SEVEN/scene.fbx"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"local changes")
        result = self.extract()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_bytes(), b"local changes")
        self.assertFalse((self.output / "README.txt").exists())

    def test_bad_crc_never_publishes_partial_directory(self):
        self.archive.write_bytes(self.archive.read_bytes().replace(b"source texture", b"broken texture"))
        result = self.extract()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_wrong_archive_hash_never_publishes(self):
        result = self.extract("--expected-sha256", "0" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256", result.stderr)
        self.assertFalse(self.output.exists())

    def test_notice_filename_cannot_be_used_as_a_scene_folder(self):
        result = self.extract("--folder", "README.txt")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_case_collision_never_publishes(self):
        with zipfile.ZipFile(self.archive, "a") as archive:
            archive.writestr("MEASURE_SEVEN/SCENE.fbx", b"different scene")
        result = self.extract()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
