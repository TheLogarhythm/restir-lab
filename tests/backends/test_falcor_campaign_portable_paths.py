import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.falcor import spatial_campaign as campaign
from scripts.falcor import cgns_temporal_capture, cgns_paper_capture
from scripts.falcor import spatial_experiment_config


class CampaignPortablePathsTest(unittest.TestCase):
    def test_analysis_records_are_relative_to_input_manifest(self):
        for module in (campaign,):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as d:
                base = Path(d)
                manifest = base / "analysis" / "input-001.json"
                image = base / "jobs" / "scene" / "capture.exr"
                expected = {"path": "../jobs/scene/capture.exr", "sha256": "a" * 64}
                self.assertEqual(module._analysis_file_record(image, "a" * 64, manifest), expected)

    def test_identity_does_not_depend_on_workspace_location(self):
        for module in (campaign,):
            identities = []
            for _ in range(2):
                with tempfile.TemporaryDirectory() as d:
                    root = Path(d)
                    frozen = root / "frozen"
                    frozen.write_text("frozen")
                    entry = {"config_sha256": "a" * 64, "adapted": False}
                    catalog = {
                        ("classroom", "board"): {
                            "entry": entry,
                            "config_path": root / "config.json",
                            "reference": {"path": str(root / "ref.exr"), "sha256": "b" * 64},
                        }
                    }
                    with (
                        patch.object(module, "ROOT", root),
                        patch.object(module.six, "baseline_path", return_value=frozen),
                        patch.object(module.six, "extension_manifest_path", return_value=frozen),
                        patch.object(module, "_code_identity", return_value={}),
                    ):
                        identities.append(
                            module._identity(
                                catalog,
                                {("baseline", False): {}},
                                "commit",
                                experiment=spatial_experiment_config.load_config(),
                                experiment_path=root / "experiment.json",
                                experiment_sha256="c" * 64,
                                runtime_paths={("baseline", False): root / "runtime"},
                            )
                        )
            self.assertEqual(identities[0], identities[1])

    def test_render_script_is_reproducible_after_workspace_move(self):
        camera = {
            "position": [0, 0, 0],
            "direction": [0, 0, 1],
            "up": [0, 1, 0],
            "vertical_fov": 45,
        }
        for module in (cgns_temporal_capture, cgns_paper_capture):
            scripts = []
            for _ in range(2):
                with tempfile.TemporaryDirectory() as d:
                    root = Path(d)
                    scripts.append(
                        module.render_script(
                            root / "scene.pyscene",
                            camera,
                            root / "jobs" / "attempt",
                            2,
                            1,
                            "baseline",
                            adapted=False,
                            portable=True,
                        )
                    )
            self.assertEqual(scripts[0], scripts[1])
            self.assertIn("m.frameCapture.outputDir = str(Path('.').resolve())", scripts[0])

    def test_capture_metadata_and_attempt_paths_have_explicit_bases(self):
        for module in (cgns_temporal_capture, cgns_paper_capture):
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                output = root / "runs" / "job"
                exe = root / "build" / "Mogwai.exe"
                with patch.object(module, "ROOT", root):
                    metadata = module._portable_paths(
                        root / "experiment.json",
                        root / "build",
                        [str(exe), "--script", str(output / "render.py")],
                    )
                self.assertEqual(metadata["path_format"], "workspace-relative-v1")
                self.assertEqual(metadata["experiment_config_path"], "experiment.json")
                self.assertEqual(metadata["runtime"], "build")
                self.assertEqual(
                    metadata["command"], ["build/Mogwai.exe", "--script", "runs/job/render.py"]
                )
        for module in (campaign,):
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                attempt = root / "jobs" / "attempt-001"
                self.assertEqual(module._attempt_path(attempt, root), "jobs/attempt-001")


if __name__ == "__main__":
    unittest.main()
