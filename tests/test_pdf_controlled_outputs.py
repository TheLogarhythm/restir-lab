"""Persistent controlled-output reuse without replacing prior artifacts."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))


class ControlledOutputTests(unittest.TestCase):
    def helper(self):
        try:
            return importlib.import_module("experiment.controlled_outputs")
        except ModuleNotFoundError:
            self.fail("The persistent controlled-output fingerprint helper is missing")

    def test_completed_matching_inputs_reuse_without_calling_generator(self):
        module = self.helper()
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "analysis"
            generated = []
            def produce(path):
                self.assertFalse(path.exists())
                generated.append(path)
                path.mkdir()
                (path / "data.txt").write_text("accepted output")
            first = module.generate_versioned(destination,
                {"reference_sha256": "aaa", "settings": {"fps": 30, "scale": [0, 1]}}, produce)
            second = module.generate_versioned(destination,
                {"settings": {"scale": [0, 1], "fps": 30}, "reference_sha256": "aaa"}, produce)
            self.assertEqual(first, destination)
            self.assertEqual(second, first)
            self.assertEqual(generated, [destination])
            receipt = json.loads((first / module.RECEIPT_NAME).read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "completed")
            self.assertEqual(receipt["schema_version"], 2)
            self.assertEqual(receipt["files"]["data.txt"]["bytes"], len(b"accepted output"))

    def test_missing_or_changed_output_regenerates_without_replacing_old_directory(self):
        module = self.helper()
        for change in ("deleted", "truncated", "same-size"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                destination = Path(folder) / "visuals"
                def produce(path):
                    path.mkdir()
                    (path / "videos").mkdir()
                    (path / "videos/comparison.mp4").write_bytes(b"complete video")
                first = module.generate_versioned(destination, {"captures": "fixed"}, produce)
                video = first / "videos/comparison.mp4"
                if change == "deleted":
                    video.unlink()
                    old_bytes = None
                else:
                    old_bytes = b"short" if change == "truncated" else b"modified video"
                    video.write_bytes(old_bytes)
                receipt = (first / module.RECEIPT_NAME).read_bytes()
                second = module.generate_versioned(destination, {"captures": "fixed"}, produce)
                self.assertNotEqual(second, first)
                self.assertEqual((second / "videos/comparison.mp4").read_bytes(), b"complete video")
                self.assertEqual((first / module.RECEIPT_NAME).read_bytes(), receipt)
                self.assertEqual(video.read_bytes() if video.exists() else None, old_bytes)

    def test_legacy_or_unsafe_file_inventory_is_never_reused(self):
        module = self.helper()
        for unsafe in ("legacy", "../outside.txt", "/outside.txt", "C:/outside.txt", "videos/../video.mp4"):
            with self.subTest(inventory=unsafe), tempfile.TemporaryDirectory() as folder:
                destination = Path(folder) / "visuals"
                def produce(path):
                    path.mkdir()
                    (path / "data.txt").write_bytes(b"complete")
                first = module.generate_versioned(destination, {"captures": "fixed"}, produce)
                receipt_path = first / module.RECEIPT_NAME
                receipt = json.loads(receipt_path.read_text())
                if unsafe == "legacy":
                    receipt["schema_version"] = 1
                else:
                    receipt["files"] = {unsafe: {"sha256": "a" * 64, "bytes": 8}}
                receipt_path.write_text(json.dumps(receipt))
                old_receipt = receipt_path.read_bytes()
                second = module.generate_versioned(destination, {"captures": "fixed"}, produce)
                self.assertNotEqual(second, first)
                self.assertEqual(receipt_path.read_bytes(), old_receipt)

    def test_changed_reference_produces_a_version_and_preserves_old_output(self):
        module = self.helper()
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "analysis"
            def producer(value):
                def produce(path):
                    self.assertFalse(path.exists())
                    path.mkdir()
                    (path / "data.txt").write_text(value)
                return produce
            old = module.generate_versioned(destination, {"reference_sha256": "old"}, producer("old result"))
            new = module.generate_versioned(destination, {"reference_sha256": "new"}, producer("new result"))
            reused = module.generate_versioned(destination, {"reference_sha256": "new"},
                lambda path: self.fail("Matching version was regenerated"))
            self.assertNotEqual(old, new)
            self.assertEqual(reused, new)
            self.assertEqual((old / "data.txt").read_text(), "old result")
            self.assertEqual((new / "data.txt").read_text(), "new result")

    def test_interrupted_producer_is_preserved_and_retry_uses_a_new_path(self):
        module = self.helper()
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "panels"
            identity = {"reference_sha256": "current", "pilot_scale": [0, 2]}
            def interrupted(path):
                path.mkdir()
                (path / "partial.txt").write_text("failure diagnostics")
                raise RuntimeError("producer interrupted")
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                module.generate_versioned(destination, identity, interrupted)
            self.assertTrue((destination / "partial.txt").is_file())
            self.assertFalse((destination / module.RECEIPT_NAME).exists())
            def complete(path):
                self.assertFalse(path.exists())
                path.mkdir()
                (path / "complete.txt").write_text("finished")
            retried = module.generate_versioned(destination, identity, complete)
            self.assertNotEqual(retried, destination)
            self.assertEqual((destination / "partial.txt").read_text(), "failure diagnostics")
            self.assertTrue((retried / module.RECEIPT_NAME).is_file())

    def test_unknown_and_corrupt_receipt_folders_are_never_reused(self):
        module = self.helper()
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "summary"
            destination.mkdir()
            (destination / module.RECEIPT_NAME).write_text("interrupted JSON{")
            (destination / "old.txt").write_text("keep")
            def complete(path):
                self.assertFalse(path.exists())
                path.mkdir()
                (path / "new.txt").write_text("new")
            first = module.generate_versioned(destination, {"inputs": "same"}, complete)
            receipt_path = first / module.RECEIPT_NAME
            receipt = json.loads(receipt_path.read_text())
            receipt["identity"] = {"inputs": "different"}
            receipt_path.write_text(json.dumps(receipt))
            second = module.generate_versioned(destination, {"inputs": "same"}, complete)
            self.assertNotIn(second, (destination, first))
            self.assertEqual((destination / "old.txt").read_text(), "keep")
            self.assertTrue((first / "new.txt").is_file())


if __name__ == "__main__":
    unittest.main()
