import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("build_media", Path(__file__).resolve().parents[2] / "writing/progress/tools/build_media.py")
media = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(media)

class MediaPathTests(unittest.TestCase):
    def test_command_paths_normalize_and_reuse_legacy_receipts(self):
        original = ["ffmpeg", "-i", str(media.REPO / "runs/input/frame-%04d.png"), "-vf", "scale=1:1", str(media.REPO / "writing/progress/assets/videos/out.mp4")]
        expected = ["ffmpeg", "-i", "runs/input/frame-%04d.png", "-vf", "scale=1:1", "writing/progress/assets/videos/out.mp4"]
        self.assertEqual(media.record_command(original), expected)
        self.assertTrue(media.commands_match(original, expected, "repository_root"))
        self.assertTrue(media.commands_match(original, original, None))
        self.assertFalse(media.commands_match(original, [*expected[:-1], "other.mp4"], "repository_root"))

    def test_external_path_and_unknown_base_are_rejected(self):
        original = ["ffmpeg", "-i", str(media.REPO / "runs/input.png"), str(media.REPO / "out.mp4")]
        external = ["ffmpeg", "-i", str(media.REPO.parent / "outside.png"), str(media.REPO / "out.mp4")]
        with self.assertRaises(ValueError): media.record_command(external)
        self.assertFalse(media.commands_match(original, external, None))
        self.assertFalse(media.commands_match(original, original, "unknown"))

if __name__ == "__main__": unittest.main()
