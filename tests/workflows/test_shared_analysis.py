"""Shared offline analysis preserves artifact and independent-trial boundaries."""

import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from tests.fixtures.saved_runs import digest, save, write_falcor_run, write_rtxdi_run
from records import read_run, load_frame
from image_io.images import write_pfm


class SharedAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module("analysis.saved_runs")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_describe_both_backends_with_explicit_uncertified_reference(self):
        for backend, fixture in (
            ("rtxdi", write_rtxdi_run),
            ("falcor", write_falcor_run),
        ):
            run = read_run(fixture(self.root / backend))
            reference = self.root / (backend + "-reference.pfm")
            write_pfm(reference, load_frame(run, 1))
            result = self.api.describe_run(run, reference_image=reference)
            self.assertEqual(result["backend"], backend)
            self.assertEqual(result["frames"][0]["smape_percent"], 0)
            self.assertFalse(result["reference"]["target_or_convergence_certified"])
            self.assertIn("analysis_source_sha256", result)
            self.assertEqual(result["reference"]["sha256"], digest(reference))

    def test_falcor_repeat_never_becomes_an_independent_trial(self):
        runs = [read_run(write_falcor_run(self.root / str(i))) for i in range(2)]
        with self.assertRaisesRegex(ValueError, "independent"):
            self.api.independent_sequences(runs, [1, 4])
        runs[0] = read_run(write_rtxdi_run(self.root / "rtxdi"))
        with self.assertRaises(ValueError):
            self.api.independent_sequences(runs, [1, 4])

    def test_rtxdi_repeats_keep_full_controls_and_nonoverlapping_rng(self):
        runs = [
            read_run(write_rtxdi_run(self.root / str(i), seed=i, value=i))
            for i in (1, 2)
        ]
        sequences = self.api.independent_sequences(runs, [1, 2, 3, 4])
        self.assertEqual(
            [sequence.id for sequence in sequences], ["rtxdi:1", "rtxdi:2"]
        )
        self.assertEqual([f.index for f in sequences[0].frames], [1, 2, 3, 4])
        result = self.api.analyze_repeats(runs, [1, 2, 3, 4], lag=1, radius=0)
        self.assertEqual(result["valid_temporal_frame_pairs"], 3)
        with self.assertRaisesRegex(ValueError, "seed|independent"):
            self.api.independent_sequences([runs[0], runs[0]], [1, 2])

    def test_repeat_analysis_rejects_matching_incomplete_builds(self):
        for failure in (
            "missing_executable",
            "missing_shaders",
            "empty_shaders",
            "missing_both",
        ):
            with self.subTest(failure=failure):
                folders = []
                for seed in (1, 2):
                    folder = write_rtxdi_run(self.root / failure / str(seed), seed=seed)
                    manifest = json.loads((folder / "manifest.json").read_text())
                    if failure in ("missing_executable", "missing_both"):
                        manifest["build"].pop("executable_sha256")
                    if failure in ("missing_shaders", "missing_both"):
                        manifest["build"].pop("shader_sha256")
                    if failure == "empty_shaders":
                        manifest["build"]["shader_sha256"] = {}
                    save(folder / "manifest.json", manifest)
                    folders.append(folder)
                with self.assertRaisesRegex(ValueError, "RTXDI.*(executable|shader)"):
                    self.api.analyze_repeats(
                        [read_run(folder) for folder in folders],
                        [1, 2, 3, 4],
                        lag=1,
                        radius=0,
                    )

    def test_repeat_analysis_rejects_different_estimator_fingerprints(self):
        for field in ("executable_sha256", "shader_sha256"):
            with self.subTest(field=field):
                left = write_rtxdi_run(self.root / field / "left", seed=1)
                right = write_rtxdi_run(self.root / field / "right", seed=2)
                manifest = json.loads((right / "manifest.json").read_text())
                manifest["build"][field] = (
                    "a" * 64 if field == "executable_sha256" else {"shader": "a" * 64}
                )
                save(right / "manifest.json", manifest)
                runs = [read_run(left), read_run(right)]
                self.assertTrue(
                    all("independent_trials" in run.capabilities for run in runs)
                )
                with self.assertRaisesRegex(ValueError, "settings|provenance"):
                    self.api.analyze_repeats(runs, [1, 2, 3, 4], lag=1, radius=0)

    def test_changed_unmeasured_controls_sampling_or_lighting_rejects_comparison(self):
        for failure in ("warmup", "rng", "lighting", "settings"):
            with self.subTest(failure=failure):
                left = write_rtxdi_run(self.root / (failure + "-a"), seed=1)
                right = write_rtxdi_run(self.root / (failure + "-b"), seed=2)
                config = json.loads((right / "config.json").read_text())
                manifest = json.loads((right / "manifest.json").read_text())
                if failure == "warmup":
                    config["frames"][0]["position"][0] = 10
                elif failure == "rng":
                    config["frames"][0]["sampling_frame"] = 1048576
                elif failure == "settings":
                    config["arguments"]["restirDI.testParameter"] = 1
                else:
                    manifest["build"]["donut"]["commit"] = "changed"
                save(right / "config.json", config)
                manifest["config_sha256"] = digest(right / "config.json")
                save(right / "manifest.json", manifest)
                with self.assertRaises(ValueError):
                    self.api.independent_sequences(
                        [read_run(left), read_run(right)], [2, 3, 4]
                    )

    def test_repeat_analysis_rejects_inconsistent_rng_progression(self):
        for failure in ("repeated", "skipped", "wrong_seed_block", "different_offset"):
            with self.subTest(failure=failure):
                left = write_rtxdi_run(self.root / (failure + "-a"), seed=1)
                right = write_rtxdi_run(self.root / (failure + "-b"), seed=2)
                config = json.loads((right / "config.json").read_text())
                for row in config["frames"]:
                    if failure == "repeated":
                        row["sampling_frame"] = 2097152
                    elif failure == "skipped":
                        row["sampling_frame"] = 2097152 + 2 * (row["frame"] - 1)
                    elif failure == "wrong_seed_block":
                        row["sampling_frame"] += 1048576
                    else:
                        row["sampling_frame"] += 64
                save(right / "config.json", config)
                manifest = json.loads((right / "manifest.json").read_text())
                manifest["config_sha256"] = digest(right / "config.json")
                save(right / "manifest.json", manifest)
                with self.assertRaisesRegex(ValueError, "sampling|RNG|controls"):
                    self.api.analyze_repeats(
                        [read_run(left), read_run(right)], [1, 2, 3, 4], lag=1, radius=0
                    )

    def test_common_controlled_sampling_offset_is_preserved(self):
        runs = []
        for seed in (1, 2):
            folder = write_rtxdi_run(self.root / str(seed), seed=seed)
            config = json.loads((folder / "config.json").read_text())
            for row in config["frames"]:
                row["sampling_frame"] += 64
            save(folder / "config.json", config)
            manifest = json.loads((folder / "manifest.json").read_text())
            manifest["config_sha256"] = digest(folder / "config.json")
            save(folder / "manifest.json", manifest)
            runs.append(read_run(folder))
        result = self.api.analyze_repeats(runs, [1, 2, 3, 4], lag=1, radius=0)
        self.assertEqual(result["valid_temporal_frame_pairs"], 3)
        self.assertEqual(runs[0].controls[0]["sampling_frame"], 1048640)

    def test_repeat_analysis_binds_saved_inputs_and_uncertified_references(self):
        runs = [read_run(write_rtxdi_run(self.root / str(i), seed=i)) for i in (1, 2)]
        reference = self.root / "reference.pfm"
        write_pfm(reference, load_frame(runs[0], 1))
        for references in (reference, {frame: reference for frame in (1, 2, 3, 4)}):
            with self.subTest(references=type(references).__name__):
                result = self.api.analyze_repeats(
                    runs, [1, 2, 3, 4], references=references, lag=1, radius=0
                )
                self.assertIn("input_runs", result)
                self.assertEqual(len(result["input_runs"]), 2)
                for saved, run in zip(result["input_runs"], runs):
                    self.assertEqual(saved["run_directory"], str(run.directory))
                    self.assertEqual(
                        saved["manifest_sha256"],
                        digest(run.directory / "manifest.json"),
                    )
                    self.assertEqual(
                        saved["record_files"]["config.json"],
                        digest(run.directory / "config.json"),
                    )
                    self.assertEqual(
                        [row["frame"] for row in saved["frames"]], [1, 2, 3, 4]
                    )
                    self.assertEqual(
                        saved["frames"][0]["sha256"], digest(run.frames[0].image)
                    )
                self.assertEqual(
                    [row["frame"] for row in result["references"]], [1, 2, 3, 4]
                )
                for row in result["references"]:
                    self.assertEqual(row["path"], str(reference.resolve()))
                    self.assertEqual(row["sha256"], digest(reference))
                    self.assertFalse(row["target_or_convergence_certified"])
                self.assertIn(
                    "analysis/saved_runs.py",
                    result["analysis_source_sha256"],
                )
                json.dumps(result, allow_nan=False)

    def test_repeat_analysis_rejects_reference_changed_during_analysis(self):
        runs = [read_run(write_rtxdi_run(self.root / str(i), seed=i)) for i in (1, 2)]
        reference = self.root / "reference.pfm"
        rgb = load_frame(runs[0], 1)
        for change_at in (1, 4):
            with self.subTest(change_at=change_at):
                write_pfm(reference, rgb)

                def masks(frame):
                    if frame == change_at:
                        write_pfm(reference, rgb + 1)
                    return {}

                with self.assertRaisesRegex(ValueError, "Reference.*changed"):
                    self.api.analyze_repeats(
                        runs,
                        [1, 2, 3, 4],
                        references=reference,
                        masks=masks,
                        regions=("all",),
                        lag=1,
                        radius=0,
                    )

    def test_analysis_rechecks_images_after_record_was_read(self):
        runs = [read_run(write_rtxdi_run(self.root / str(i), seed=i)) for i in (1, 2)]
        runs[0].frames[0].image.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.api.describe_run(runs[0])
        with self.assertRaises(ValueError):
            self.api.analyze_repeats(runs, [1, 2, 3, 4], lag=1, radius=0)

    def test_record_metadata_changes_after_read_are_rejected(self):
        run = read_run(write_falcor_run(self.root / "run"))
        (run.directory / "config.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "record changed"):
            self.api.describe_run(run)

    def test_cli_preserves_input_and_existing_output(self):
        run = write_falcor_run(self.root / "run")
        before = {p.name: digest(p) for p in run.iterdir()}
        output = self.root / "analysis"
        command = [
            sys.executable,
            "-B",
            str(ROOT / "scripts/analyze_run.py"),
            "--run",
            str(run),
            "--output",
            str(output),
        ]
        first = subprocess.run(command, cwd=self.root, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        report = output / "analysis.json"
        result = json.loads(report.read_text())
        self.assertEqual(result["status"], "completed")
        original = report.read_bytes()
        second = subprocess.run(command, cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(report.read_bytes(), original)
        self.assertEqual({p.name: digest(p) for p in run.iterdir()}, before)
        inside = subprocess.run(
            command[:-1] + [str(run / "analysis")],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(inside.returncode, 0)
        self.assertFalse((run / "analysis").exists())


if __name__ == "__main__":
    unittest.main()
