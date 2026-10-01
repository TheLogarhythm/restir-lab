"""Run naming and portable records; GPU execution is replaced at the process boundary."""
import importlib
import json
import ntpath
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.cli = importlib.import_module("rtxdi_reuse")
        self.runner = importlib.import_module("experiment.runner")
        self.config = importlib.import_module("experiment.config")
        self.scene = importlib.import_module("experiment.scenes").load_scene("cornell-box")

    def test_output_name_stays_inside_runs_and_rejects_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.cli.output_directory("baseline-v1", root=root)
            self.assertEqual(path, root / "runs/baseline-v1")
            self.assertFalse(path.exists())
            path.mkdir(parents=True)
            with self.assertRaises(FileExistsError):
                self.cli.output_directory("baseline-v1", root=root)
            for name in ("", "../outside", "a/b", "a\\b", "C:\\out", "CON", "nul.txt", "a " * 40):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    self.cli.output_directory(name, root=root)

    def test_default_name_remains_timestamped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.cli.output_directory(None, root=Path(directory))
            self.assertRegex(path.name, r"^\d{8}T\d{12}Z-di-reuse$")

    def test_window_selection_does_not_change_sampling_or_frame_sequence(self):
        definition = self.config.load_definition()
        hidden = self.config.make_config(self.scene, definition, "combined", "motion")
        self.assertEqual(hidden["arguments"].get("device.headless"), 1)
        visible = self.config.make_config(self.scene, definition, "combined", "motion", headless=False)
        self.assertEqual(visible["arguments"].pop("device.headless"), 0)
        hidden["arguments"].pop("device.headless")
        self.assertEqual(hidden, visible)

    def test_records_remain_usable_after_suite_rename(self):
        config = self.config.make_config(self.scene, self.config.load_definition(), "initial", "static")
        with tempfile.TemporaryDirectory() as directory:
            suite = Path(directory) / "original"
            output = suite / "cornell-box/static/initial/seed-1"

            def render(command, **kwargs):
                self.assertEqual((kwargs["cwd"] / command[0]).resolve(), self.runner.EXE.resolve())
                self.assertEqual(Path(kwargs["executable"]), self.runner.EXE)
                self.assertIn("--device.headless=1", command)
                self.assertIn("--device.vk=0", command)
                self.assertEqual(kwargs["env"]["RTXDI_EXPERIMENT_CONFIG"], "config.json")
                kwargs["stdout"].write(f"Loaded {ROOT / 'assets/example.gltf'}\n")
                return mock.Mock(returncode=0)

            with mock.patch.object(self.runner.platform, "platform", return_value="test"), \
                 mock.patch.object(self.runner, "query", return_value="test"), \
                 mock.patch.object(self.runner.subprocess, "run", side_effect=render), \
                 mock.patch.object(self.runner, "finalize_outputs", return_value=[]):
                self.runner.run_one(config, output, {}, {})
            renamed = suite.with_name("renamed")
            suite.rename(renamed)
            output = renamed / "cornell-box/static/initial/seed-1"
            record = json.loads((output / "manifest.json").read_text())
            saved = json.loads((output / "config.json").read_text())
            self.assertEqual(record["cwd"], ".")
            self.assertEqual(saved["output"], ".")
            self.assertEqual((output / record["command"][0]).resolve(), self.runner.EXE.resolve())
            self.assertEqual((output / saved["repository_root"]).resolve(), ROOT)
            self.assertEqual((output / saved["repository_root"] / saved["scene"]["source"]["root"]).resolve(),
                             ROOT / "renderers/rtxdi/Assets/Media")

            def check(value):
                if isinstance(value, dict):
                    for child in value.values():
                        check(child)
                elif isinstance(value, list):
                    for child in value:
                        check(child)
                elif isinstance(value, str):
                    self.assertFalse(ntpath.isabs(value), value)

            check(record)
            check(saved)
            self.assertNotIn(str(ROOT), (output / "renderer.log").read_text())


if __name__ == "__main__":
    unittest.main()
