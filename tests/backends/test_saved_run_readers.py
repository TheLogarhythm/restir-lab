"""Backend result normalization with real PFM/EXR artifacts and no renderer."""

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts/run")]
from tests.fixtures.saved_runs import digest, save, write_rtxdi_run, write_falcor_run


class SavedRunReaderTests(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module("records")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_both_backends_normalize_without_writing_inputs(self):
        for backend, fixture in (
            ("rtxdi", write_rtxdi_run),
            ("falcor", write_falcor_run),
        ):
            folder = fixture(self.root / backend)
            before = {p.name: digest(p) for p in folder.iterdir()}
            run = self.api.read_run(folder)
            self.assertEqual(run.backend, backend)
            self.assertEqual((run.width, run.height), (3, 2))
            self.assertEqual(self.api.load_frame(run, 1).shape, (2, 3, 3))
            self.assertEqual({p.name: digest(p) for p in folder.iterdir()}, before)
        self.assertIsNone(run.seed)
        self.assertNotIn("independent_trials", run.capabilities)
        self.assertTrue(run.limitations)
        self.assertIsNone(run.frames[0].reset)
        self.assertIsNone(run.frames[0].target)

    def test_rtxdi_preserves_native_target_and_all_control_frames(self):
        from experiment.reference import target

        folder = write_rtxdi_run(self.root / "run")
        config = json.loads((folder / "config.json").read_text())
        config["frames"][0]["capture"] = False
        save(folder / "config.json", config)
        record = json.loads((folder / "manifest.json").read_text())
        record["config_sha256"] = digest(folder / "config.json")
        record["captures"] = record["captures"][1:]
        save(folder / "manifest.json", record)
        run = self.api.read_run(folder)
        self.assertEqual(len(run.controls), 4)
        self.assertEqual([f.index for f in run.frames], [2, 3, 4])
        self.assertEqual(
            run.frames[0].target, target(config, config["frames"][1], "a" * 64)
        )
        self.assertIn("independent_trials", run.capabilities)

    def test_historical_falcor_missing_snapshots_stays_readable_and_limited(self):
        run = self.api.read_run(write_falcor_run(self.root / "old", snapshots=False))
        self.assertIn("build_snapshot_missing", run.limitations)
        self.assertNotIn("independent_trials", run.capabilities)
        self.assertIsNone(run.provenance["gpu_time_ms"])

    def test_readers_reject_modified_images_and_recheck_at_load(self):
        for backend, fixture in (
            ("rtxdi", write_rtxdi_run),
            ("falcor", write_falcor_run),
        ):
            with self.subTest(backend=backend):
                folder = fixture(self.root / backend)
                run = self.api.read_run(folder)
                run.frames[0].image.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "hash|digest|modified"):
                    self.api.load_frame(run, 1)
                with self.assertRaises(ValueError):
                    self.api.read_run(folder)

    def test_rtxdi_rejects_incomplete_hashes_and_ambiguous_capture_coverage(self):
        for failure in (
            "failed",
            "config",
            "image_hash",
            "duplicate",
            "missing",
            "extra",
        ):
            with self.subTest(failure=failure):
                folder = write_rtxdi_run(self.root / failure)
                record = json.loads((folder / "manifest.json").read_text())
                if failure == "failed":
                    record["status"] = "failed"
                elif failure == "config":
                    (folder / "config.json").write_text("{}")
                elif failure == "image_hash":
                    record["captures"][0].pop("image_sha256")
                elif failure == "duplicate":
                    record["captures"].append(record["captures"][0])
                elif failure == "missing":
                    record["captures"].pop()
                else:
                    record["captures"].append({"frame": 9, "image_sha256": "a" * 64})
                save(folder / "manifest.json", record)
                with self.assertRaises(ValueError):
                    self.api.read_run(folder)

    def test_rtxdi_rejects_missing_or_invalid_estimator_build_evidence(self):
        cases = [
            ("missing_executable", ("executable_sha256",), {}),
            ("missing_shaders", ("shader_sha256",), {}),
            ("missing_both", ("executable_sha256", "shader_sha256"), {}),
        ]
        for index, value in enumerate((None, "", True, 7, [], "e" * 63, "g" * 64)):
            cases.append(
                (f"invalid_executable_{index}", (), {"executable_sha256": value})
            )
        for index, value in enumerate((None, {}, [], True, "f" * 64)):
            cases.append((f"invalid_shaders_{index}", (), {"shader_sha256": value}))
        for index, value in enumerate((None, "", False, 7, [], "f" * 63, "g" * 64)):
            cases.append(
                (
                    f"invalid_shader_digest_{index}",
                    (),
                    {"shader_sha256": {"valid.bin": "f" * 64, "invalid.bin": value}},
                )
            )
        for index, name in enumerate(("", "   ")):
            cases.append(
                (f"empty_shader_name_{index}", (), {"shader_sha256": {name: "f" * 64}})
            )
        for failure, removed, updates in cases:
            with self.subTest(failure=failure):
                folder = write_rtxdi_run(self.root / failure)
                manifest = json.loads((folder / "manifest.json").read_text())
                for key in removed:
                    manifest["build"].pop(key)
                manifest["build"].update(updates)
                save(folder / "manifest.json", manifest)
                with self.assertRaisesRegex(ValueError, "RTXDI.*(executable|shader)"):
                    self.api.read_run(folder)

    def test_rtxdi_rejects_bad_full_controls_and_unsupported_transport(self):
        for failure in ("seed", "gap", "reset", "sampling", "capture", "indirect"):
            with self.subTest(failure=failure):
                folder = write_rtxdi_run(self.root / failure)
                config = json.loads((folder / "config.json").read_text())
                if failure == "seed":
                    config["seed"] = True
                elif failure == "gap":
                    config["frames"][1]["frame"] = 9
                elif failure == "reset":
                    config["frames"][0]["reset"] = False
                elif failure == "sampling":
                    config["frames"][0]["sampling_frame"] = -1
                elif failure == "capture":
                    config["frames"][0]["capture"] = "yes"
                else:
                    config["arguments"]["lighting.indirectMode"] = "RESTIRPT"
                save(folder / "config.json", config)
                record = json.loads((folder / "manifest.json").read_text())
                record["config_sha256"] = digest(folder / "config.json")
                save(folder / "manifest.json", record)
                with self.assertRaises(ValueError):
                    self.api.read_run(folder)

    def test_falcor_rejects_corrupt_or_inconsistent_records(self):
        for failure in (
            "schema",
            "config",
            "duplicate",
            "frame",
            "encoding",
            "build",
            "graph",
            "coverage",
            "escape",
            "absolute",
        ):
            with self.subTest(failure=failure):
                folder = write_falcor_run(self.root / failure)
                record = json.loads((folder / "manifest.json").read_text())
                if failure == "schema":
                    record["schema_version"] = 2
                elif failure == "config":
                    save(folder / "config.json", {})
                elif failure == "duplicate":
                    record["artifacts"].append(record["artifacts"][0])
                elif failure == "frame":
                    record["artifacts"][0]["frame"] = 2
                elif failure == "encoding":
                    record["artifacts"][0]["encoding"] = "sRGB"
                elif failure == "build":
                    save(folder / "build.json", {"commit": "c" * 40})
                elif failure == "graph":
                    (folder / "graphs.py").write_text("modified")
                elif failure == "coverage":
                    record["artifacts"].pop()
                elif failure == "escape":
                    record["artifacts"][0]["hdr"] = "../outside.exr"
                else:
                    record["artifacts"][0]["hdr"] = "C:/outside.exr"
                save(folder / "manifest.json", record)
                with self.assertRaises(ValueError):
                    self.api.read_run(folder)

    def test_falcor_checks_recorded_preview_hashes_and_paths(self):
        for failure in ("modified", "missing_hash", "missing_file", "escape"):
            with self.subTest(failure=failure):
                folder = write_falcor_run(self.root / failure)
                record = json.loads((folder / "manifest.json").read_text())
                row = record["artifacts"][0]
                if failure == "modified":
                    (folder / row["preview"]).write_bytes(b"changed")
                elif failure == "missing_hash":
                    row.pop("preview_sha256")
                elif failure == "missing_file":
                    (folder / row["preview"]).unlink()
                else:
                    row["preview"] = "../outside.png"
                save(folder / "manifest.json", record)
                with self.assertRaises(ValueError):
                    self.api.read_run(folder)

    def test_falcor_rechecks_previews_after_record_was_read(self):
        folder = write_falcor_run(self.root / "run")
        run = self.api.read_run(folder)
        preview = folder / "frame-0001.png"
        self.assertIn(preview.name, run.provenance["record_files"])
        self.assertEqual(run.provenance["record_files"][preview.name], digest(preview))
        preview.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "record changed"):
            self.api.load_frame(run, 1)

    def test_offline_readers_need_neither_checkout_helpers_nor_live_gpu(self):
        folder = write_falcor_run(self.root / "run")
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        code = "import sys; from records import read_run; r=read_run(sys.argv[1]); assert r.backend=='falcor'; assert not any(n.startswith(('experiment','rtxdi_','scripts.','falcor')) for n in sys.modules)"
        child = subprocess.run(
            [sys.executable, "-B", "-c", code, str(folder)],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(child.returncode, 0, child.stderr)


if __name__ == "__main__":
    unittest.main()
