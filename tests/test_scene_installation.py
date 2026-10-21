"""Pinned downloads and atomic extraction/conversion; no network or large assets."""
import hashlib
import importlib
import io
import json
import os
import shutil
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/assets"))


class SceneInstallationTests(unittest.TestCase):
    def setUp(self):
        self.installer = importlib.import_module("install_scene")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self, extra=None):
        stream = io.BytesIO()
        entries = {"model/scene.gltf": json.dumps({"asset": {"version": "2.0"},
                    "buffers": [{"uri": "mesh.bin", "byteLength": 4}]}).encode(),
                   "model/mesh.bin": b"mesh", "LICENSE.txt": b"Keep source attribution"}
        entries.update(extra or {})
        with zipfile.ZipFile(stream, "w") as archive:
            for name, value in entries.items():
                member = zipfile.ZipInfo(name)
                member.filename = name  # Preserve hostile backslashes on Windows for the path-validation test.
                archive.writestr(member, value)
        payload = stream.getvalue()
        record = {"id": "test-scene", "source_download_url": "https://example.com/scene.zip",
                  "source_revision": "scene.zip", "source_sha256": hashlib.sha256(payload).hexdigest(),
                  "installation": {"source_entry": "model/scene.gltf", "profile": "san-miguel",
                                   "output_entry": "scene.gltf"}}
        # Hand-specified expected converted bytes, independent of converter helpers.
        converted = b'{"asset":{"version":"2.0"},"buffers":[{"uri":"resources/buffer-0000.bin","byteLength":4}]}\n'
        converted = converted.replace(b"\n", os.linesep.encode())
        files = {"scene.gltf": hashlib.sha256(converted).hexdigest(),
                 "resources/buffer-0000.bin": hashlib.sha256(entries["model/mesh.bin"]).hexdigest()}
        closure = "".join(f"{value}  {name}\n" for name, value in sorted(files.items()))
        record["runtime_assets"] = {"sha256": hashlib.sha256(closure.encode()).hexdigest(), "file_count": 2}
        (self.root / "scenes").mkdir(parents=True)
        (self.root / "scenes/manifest.yaml").write_text(json.dumps({"scenes": [record]}))
        return payload, record

    def install(self, payload, **kwargs):
        with patch.object(self.installer, "urlopen", return_value=io.BytesIO(payload)):
            return self.installer.install_scene("test-scene", root=self.root, **kwargs)

    def test_install_retains_notices_and_reuses_verified_outputs(self):
        payload, _ = self.fixture()
        output = self.install(payload)
        self.assertEqual(output, self.root / "assets/converted/test-scene/scene.gltf")
        self.assertEqual((self.root / "assets/prepared/test-scene/LICENSE.txt").read_bytes(),
                         b"Keep source attribution")
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with patch.object(self.installer, "urlopen", side_effect=AssertionError("Unexpected download")):
            self.assertEqual(self.installer.install_scene("test-scene", root=self.root), output)
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_conversion_record_binds_the_pinned_source_archive(self):
        payload, record = self.fixture()
        output = self.install(payload)
        converted = json.loads(output.with_suffix(".conversion.json").read_text())
        self.assertEqual(converted.get("source_archive_sha256"), record["source_sha256"])

    def test_same_entry_with_changed_source_dependency_rejects_old_conversion(self):
        payload, _ = self.fixture()
        output = self.install(payload)
        previous_root = self.root
        self.root = previous_root / "changed-source"
        try:
            changed, _ = self.fixture({"model/mesh.bin": b"diff"})
            reused = self.root / "assets/converted/test-scene"
            shutil.copytree(output.parent, reused)
            before = {p.relative_to(reused): p.read_bytes() for p in reused.rglob("*") if p.is_file()}
            with self.assertRaisesRegex(ValueError, "source archive"):
                self.install(changed)
            self.assertEqual(before, {p.relative_to(reused): p.read_bytes() for p in reused.rglob("*") if p.is_file()})
            self.assertEqual((self.root / "assets/prepared/test-scene/model/mesh.bin").read_bytes(), b"diff")
        finally:
            self.root = previous_root

    def test_old_conversion_without_archive_binding_is_rejected(self):
        payload, _ = self.fixture()
        output = self.install(payload)
        path = output.with_suffix(".conversion.json")
        converted = json.loads(path.read_text())
        converted.pop("source_archive_sha256", None)
        path.write_text(json.dumps(converted))
        with self.assertRaisesRegex(ValueError, "source archive"):
            self.install(payload)

    def test_new_conversion_must_match_registered_runtime_digest(self):
        payload, record = self.fixture()
        record["runtime_assets"]["sha256"] = "0" * 64
        (self.root / "scenes/manifest.yaml").write_text(json.dumps({"scenes": [record]}))
        with self.assertRaisesRegex(ValueError, "Runtime assets differ"):
            self.install(payload)
        self.assertTrue((self.root / "assets/prepared/test-scene/model/scene.gltf").is_file())

    def test_reused_conversion_must_match_registered_runtime_digest_and_count(self):
        payload, record = self.fixture()
        output = self.install(payload)
        expected = dict(record["runtime_assets"])
        before = {p.relative_to(output.parent): p.read_bytes() for p in output.parent.rglob("*") if p.is_file()}
        for key, value in (("sha256", "0" * 64), ("file_count", 3)):
            with self.subTest(field=key):
                record["runtime_assets"] = {**expected, key: value}
                (self.root / "scenes/manifest.yaml").write_text(json.dumps({"scenes": [record]}))
                with self.assertRaisesRegex(ValueError, "Runtime assets differ"):
                    self.install(payload)
                self.assertEqual(before, {p.relative_to(output.parent): p.read_bytes() for p in output.parent.rglob("*") if p.is_file()})

    def test_missing_runtime_registration_is_rejected_before_installation(self):
        payload, record = self.fixture()
        del record["runtime_assets"]
        (self.root / "scenes/manifest.yaml").write_text(json.dumps({"scenes": [record]}))
        with self.assertRaisesRegex(ValueError, "runtime_assets"):
            self.install(payload)
        self.assertFalse((self.root / "assets").exists())

    def test_download_only_verifies_zip_without_extracting(self):
        payload, _ = self.fixture()
        archive = self.install(payload, download_only=True)
        self.assertEqual(archive.read_bytes(), payload)
        self.assertFalse((self.root / "assets/prepared").exists())
        self.assertFalse((self.root / "assets/converted").exists())

    def test_hash_mismatch_does_not_publish_archive_or_scene(self):
        self.fixture()
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.install(b"wrong archive")
        self.assertFalse((self.root / "assets/sources/test-scene/scene.zip").exists())
        self.assertFalse((self.root / "assets/prepared").exists())

    def test_existing_wrong_archive_is_preserved_and_rejected(self):
        payload, _ = self.fixture()
        archive = self.root / "assets/sources/test-scene/scene.zip"
        archive.parent.mkdir(parents=True)
        archive.write_bytes(b"keep original")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.install(payload)
        self.assertEqual(archive.read_bytes(), b"keep original")

    def test_unsafe_archive_paths_never_publish_extraction(self):
        for name in ("../outside", "/absolute", "nested\\evil", "C:evil", "model/../evil"):
            with self.subTest(path=name), tempfile.TemporaryDirectory() as folder:
                old_root = self.root
                self.root = Path(folder)
                try:
                    payload, _ = self.fixture({name: b"unsafe"})
                    with self.assertRaisesRegex(ValueError, "Unsafe archive"):
                        self.install(payload)
                    self.assertFalse((self.root / "assets/prepared/test-scene").exists())
                finally:
                    self.root = old_root

    def test_symlink_archive_member_is_rejected(self):
        payload, record = self.fixture()
        stream = io.BytesIO(payload)
        with zipfile.ZipFile(stream, "a") as archive:
            link = zipfile.ZipInfo("model/link")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, "../../outside")
        payload = stream.getvalue()
        record["source_sha256"] = hashlib.sha256(payload).hexdigest()
        (self.root / "scenes/manifest.yaml").write_text(json.dumps({"scenes": [record]}))
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.install(payload)
        self.assertFalse((self.root / "assets/prepared/test-scene").exists())

    def test_case_colliding_archive_names_are_rejected(self):
        payload, _ = self.fixture({"MODEL/mesh.bin": b"collision"})
        with self.assertRaisesRegex(ValueError, "[Cc]ollision"):
            self.install(payload)
        self.assertFalse((self.root / "assets/prepared/test-scene").exists())

    def test_missing_source_entry_does_not_publish_prepared_directory(self):
        payload, record = self.fixture()
        record["installation"]["source_entry"] = "missing.gltf"
        (self.root / "scenes/manifest.yaml").write_text(json.dumps({"scenes": [record]}))
        with self.assertRaisesRegex(ValueError, "source entry"):
            self.install(payload)
        self.assertFalse((self.root / "assets/prepared/test-scene").exists())

    def test_modified_extraction_is_rejected_without_overwriting(self):
        payload, _ = self.fixture()
        self.install(payload)
        source = self.root / "assets/prepared/test-scene/model/mesh.bin"
        source.write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "[Pp]repared"):
            self.install(payload)
        self.assertEqual(source.read_bytes(), b"modified")

    def test_unrecorded_extraction_is_adopted_only_when_it_matches_zip(self):
        payload, _ = self.fixture()
        prepared = self.root / "assets/prepared/test-scene"
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            archive.extractall(prepared)
        output = self.install(payload)
        self.assertTrue(output.is_file())
        self.assertTrue((prepared / ".installation.json").is_file())

    def test_unrecorded_extraction_with_extra_or_modified_file_is_rejected(self):
        for modified in (False, True):
            with self.subTest(modified=modified), tempfile.TemporaryDirectory() as folder:
                old_root, self.root = self.root, Path(folder)
                try:
                    payload, _ = self.fixture()
                    prepared = self.root / "assets/prepared/test-scene"
                    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                        archive.extractall(prepared)
                    target = prepared / ("model/mesh.bin" if modified else "extra.txt")
                    target.write_bytes(b"keep me")
                    with self.assertRaisesRegex(ValueError, "[Pp]repared"):
                        self.install(payload)
                    self.assertEqual(target.read_bytes(), b"keep me")
                    self.assertFalse((prepared / ".installation.json").exists())
                finally:
                    self.root = old_root

    def test_nested_source_record_is_retained_and_verified(self):
        payload, _ = self.fixture({"model/.installation.json": b"source record"})
        output = self.install(payload)
        self.assertEqual(self.install(payload), output)

    def test_modified_converted_resource_is_rejected_without_overwriting(self):
        payload, _ = self.fixture()
        output = self.install(payload)
        document = json.loads(output.read_text())
        resource = output.parent / document["buffers"][0]["uri"]
        resource.write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "[Cc]onverted"):
            self.install(payload)
        self.assertEqual(resource.read_bytes(), b"modified")

    def test_conversion_failure_keeps_download_and_prepared_source(self):
        payload, _ = self.fixture()
        with patch.object(self.installer, "convert_scene", side_effect=RuntimeError("conversion failed")):
            with self.assertRaisesRegex(RuntimeError, "conversion failed"):
                self.install(payload)
        self.assertTrue((self.root / "assets/prepared/test-scene/model/scene.gltf").is_file())
        self.assertFalse((self.root / "assets/converted/test-scene").exists())

    def test_missing_pinned_download_metadata_fails_before_network(self):
        payload, record = self.fixture()
        del record["source_sha256"]
        (self.root / "scenes/manifest.yaml").write_text(json.dumps({"scenes": [record]}))
        with self.assertRaisesRegex(ValueError, "source_sha256"):
            self.install(payload)

    def test_explicit_blender_reaches_the_real_conversion_pipeline(self):
        payload, record = self.fixture({"model/source.obj": b"object source"})
        record["installation"]["source_entry"] = "model/source.obj"
        (self.root / "scenes/manifest.yaml").write_text(json.dumps({"scenes": [record]}))

        def export(source, output, profile, *, blender, **kwargs):
            output.write_text(json.dumps({"asset": {"version": "2.0"},
                "buffers": [{"uri": "mesh.bin", "byteLength": 4}]}))
            (output.parent / "mesh.bin").write_bytes(b"mesh")
            return blender

        with patch("convert_scene.export_scene", side_effect=export):
            output = self.install(payload, blender="explicit-blender")
        converted = json.loads(output.with_suffix(".conversion.json").read_text())
        self.assertEqual(converted["blender_version"], "explicit-blender")


if __name__ == "__main__":
    unittest.main()
