"""Offline PT archive adapters preserve selection, controls and immutable inputs."""
import importlib
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

import numpy as np
import OpenEXR

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from tests.fixtures.falcor_archive import digest, index_archive, save, write_archive
from records import load_frame, read_run
from analysis.saved_runs import analyze_repeats, independent_sequences


class FalcorArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = write_archive(Path(self.temp.name) / "archive")

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec("backends.falcor.archive"),
                             "The archive needs its own offline adapter")
        return importlib.import_module("backends.falcor.archive")

    def capture(self, seed=0):
        return self.root / f"room/temporal-on/quality/seed-{seed}"

    def change_capture(self, change, seed=0):
        path = self.capture(seed) / "manifest.json"
        meta = json.loads(path.read_text())
        change(meta)
        save(path, meta)
        index_archive(self.root)

    def test_archive_enumerates_current_paths_and_keeps_original_provenance(self):
        before = {p.relative_to(self.root).as_posix(): digest(p)
                  for p in self.root.rglob("*") if p.is_file()}
        archive = self.api().read_archive(self.root)
        runs = archive.quality_runs(view="room", method="temporal-on")
        self.assertEqual([run.seed for run in runs], [0, 100])
        self.assertEqual([f.index for f in runs[0].frames], [3, 4, 5])
        self.assertEqual(load_frame(runs[0], 3).shape, (2, 3, 3))
        self.assertEqual(runs[0].provenance["archive"]["source_run_id"],
                         "retired-batch/room/quality/seed-0")
        self.assertEqual(archive.quality_runs(view="room", method="temporal-on", seeds=[100])[0].seed, 100)
        self.assertEqual(before, {p.relative_to(self.root).as_posix(): digest(p)
                                 for p in self.root.rglob("*") if p.is_file()})
        with self.assertRaises(ValueError):
            read_run(self.root)

    def test_quality_format_reads_directly_and_supports_checked_independent_sequences(self):
        run = read_run(self.capture())
        self.assertIn("independent_trials", run.capabilities)
        self.assertEqual([r["sampling_frame"] for r in run.controls], [0, 1, 2, 3, 4])
        self.assertEqual([r["reset"] for r in run.controls], [True, False, False, False, False])
        runs = self.api().read_archive(self.root).quality_runs(view="room", method="temporal-on")
        sequence = independent_sequences(runs, [3, 4, 5])
        self.assertEqual(len(sequence), 2)
        result = analyze_repeats(runs, [3, 4, 5], lag=1, radius=0)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["input_runs"]), 2)

    def test_timing_exclusion_and_reason_are_preserved_and_filterable(self):
        manifest = json.loads((self.root / "manifest.json").read_text())
        manifest["views"]["room"]["methods"]["temporal-on"]["timing"].update(
            included=False, exclusion_reason="Unstable timing attempts")
        save(self.root / "manifest.json", manifest)
        archive = self.api().read_archive(self.root)
        records = archive.timing_records(view="room", method="temporal-on")
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0]["included"])
        self.assertEqual(records[0]["exclusion_reason"], "Unstable timing attempts")
        self.assertEqual(records[0]["source_run_id"], "retired-timing-recheck")
        self.assertEqual(records[0]["directory"], self.root / "room/temporal-on/timing")
        self.assertEqual(archive.timing_records(included_only=True), [])
        manifest["views"]["room"]["methods"]["temporal-on"]["timing"]["exclusion_reason"] = None
        save(self.root / "manifest.json", manifest)
        with self.assertRaises(ValueError):
            self.api().read_archive(self.root).timing_records()

    def test_rejects_unknown_selection_and_duplicate_seed_entries(self):
        archive = self.api().read_archive(self.root)
        for options in ({"view": "missing"}, {"method": "missing"}, {"seeds": [7]}, {"seeds": [0, 0]}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                archive.quality_runs(**options)
        manifest = json.loads((self.root / "manifest.json").read_text())
        q = manifest["views"]["room"]["methods"]["temporal-on"]["quality"]
        q[1]["seed_offset"] = 0
        save(self.root / "manifest.json", manifest)
        with self.assertRaises(ValueError):
            self.api().read_archive(self.root).quality_runs()

    def test_rejects_missing_changed_and_escaping_archive_artifacts(self):
        api = self.api()
        image = next(self.capture().glob("*.exr"))
        image.unlink()
        with self.assertRaises(ValueError):
            api.read_archive(self.root).quality_runs()
        # Metadata traversal must be rejected without following historical paths.
        manifest = json.loads((self.root / "manifest.json").read_text())
        manifest["views"]["room"]["view_config"] = "../outside.json"
        save(self.root / "manifest.json", manifest)
        with self.assertRaises(ValueError):
            api.read_archive(self.root).quality_runs()

    def test_rejects_changed_images_and_original_capture_hash_disagreement(self):
        api = self.api()
        image = next(self.capture().glob("*.exr"))
        image.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            api.read_archive(self.root).quality_runs()
        index_archive(self.root)
        with self.assertRaises(ValueError):
            api.read_archive(self.root).quality_runs()

    def test_rejects_nonfloat32_nonfinite_or_wrong_dimension_images(self):
        for dtype, value, shape in ((np.float16, 1, (2, 3, 3)),
                                    (np.float32, float("nan"), (2, 3, 3)),
                                    (np.float32, 1, (1, 1, 3))):
            with self.subTest(dtype=dtype, value=value, shape=shape):
                image = next(self.capture().glob("*.exr"))
                OpenEXR.File({}, {"RGB": np.full(shape, value, dtype=dtype)}).write(str(image))
                def change(meta):
                    next(a for a in meta["artifacts"] if a["hdr"] == image.name)["sha256"] = digest(image)
                self.change_capture(change)
                with self.assertRaises(ValueError):
                    self.api().read_archive(self.root).quality_runs()

    def test_rejects_seed_reuse_seed_and_recorded_seed_policy_mismatch(self):
        for key, value in (("seed", 9), ("reuse_seed", 9)):
            with self.subTest(key=key):
                self.change_capture(lambda m: m["artifacts"][0].update({key: value}))
                with self.assertRaises(ValueError):
                    self.api().read_archive(self.root).quality_runs()
                self.change_capture(lambda m: m["artifacts"][0].update(seed=2, reuse_seed=1))
        self.change_capture(lambda m: m.update(seed_policy="unverified seeds"))
        with self.assertRaises(ValueError):
            read_run(self.capture())

    def test_full_warmup_seed_ranges_cannot_overlap(self):
        other = write_archive(Path(self.temp.name) / "overlap", seeds=(0, 4))
        runs = self.api().read_archive(other).quality_runs()
        with self.assertRaisesRegex(ValueError, "overlap"):
            independent_sequences(runs, [3, 4, 5])

    def test_rejects_changed_collector_or_unverified_history_evidence(self):
        script = self.capture() / "render.py"
        script.write_text(script.read_text().replace("frame - 1", "frame + 1"))
        with self.assertRaises(ValueError):
            read_run(self.capture())
        self.change_capture(lambda m: m.update(render_script_sha256=digest(script)))
        with self.assertRaises(ValueError):
            read_run(self.capture())

    def test_immutable_capture_and_archive_metadata_are_rechecked_at_load(self):
        run = self.api().read_archive(self.root).quality_runs(seeds=[0])[0]
        save(self.root / "room/view.json", {"changed": True})
        with self.assertRaisesRegex(ValueError, "changed|hash"):
            load_frame(run, 3)

    def test_rejects_repeat_graph_camera_and_lighting_mismatches(self):
        runs = self.api().read_archive(self.root).quality_runs()
        for file in ("resolved-camera.json", "scene-state.json"):
            with self.subTest(file=file):
                path = self.capture(100) / file
                old = path.read_bytes()
                data = json.loads(old)
                if file == "scene-state.json":
                    data["lights"][0]["intensity"] = [2, 2, 2]
                else:
                    for state in data.values(): state["position"] = [1, 0, 2]
                save(path, data)
                index_archive(self.root)
                current = self.api().read_archive(self.root).quality_runs()
                with self.assertRaisesRegex(ValueError, "differ"):
                    independent_sequences(current, [3, 4, 5])
                path.write_bytes(old)
                index_archive(self.root)

    def test_inspect_cli_reads_metadata_without_decoding_quality_images(self):
        # An invalid EXR stays present: metadata inspection must not decode it.
        next(self.capture().glob("*.exr")).write_bytes(b"not an EXR")
        command = [sys.executable, "-B", str(ROOT / "scripts/analysis/pt_stage_archive.py"),
                   "--root", str(self.root), "--inspect"]
        child = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(child.returncode, 0, child.stderr)
        data = json.loads(child.stdout)
        self.assertEqual(data["quality_captures"], 2)
        self.assertEqual(data["timing_captures"], 1)
        self.assertFalse(data["quality_images_decoded"])
        self.assertFalse(data["renderer_launched"])

    def test_collectors_without_full_history_controls_do_not_gain_independence(self):
        script = self.capture() / "render.py"
        script.write_text(script.read_text().replace("tracer.useFixedSeed = True", "tracer.useFixedSeed = False"))
        self.change_capture(lambda m: m.update(render_script_sha256=digest(script)))
        with self.assertRaises(ValueError):
            read_run(self.capture())

    def test_original_record_paths_and_archive_root_cannot_escape(self):
        self.change_capture(lambda m: m["artifacts"][0].update(hdr="../outside.exr"))
        with self.assertRaises(ValueError):
            read_run(self.capture())
        manifest = json.loads((self.root / "manifest.json").read_text())
        manifest["views"]["room"]["methods"]["temporal-on"]["quality"][0]["directory"] = "../outside"
        save(self.root / "manifest.json", manifest)
        with self.assertRaises(ValueError):
            self.api().read_archive(self.root).quality_runs()

    def test_seed_must_be_set_before_render_and_history_must_not_reset_midstream(self):
        script = self.capture() / "render.py"
        original = script.read_text()
        mutations = [
            original.replace("    tracer.fixedSeed = frame - 1\n    m.clock.frame = frame\n    m.renderFrame()",
                             "    m.clock.frame = frame\n    m.renderFrame()\n    tracer.fixedSeed = frame - 1"),
            original.replace("    m.renderFrame()", "    tracer.reset()\n    m.renderFrame()"),
            original.replace("    m.renderFrame()", "    tracer.useFixedSeed = False\n    m.renderFrame()"),
            original.replace("    m.renderFrame()", "    m.clock.time = 1\n    m.renderFrame()")]
        for text in mutations:
            with self.subTest(script=text):
                script.write_text(text)
                self.change_capture(lambda m: m.update(render_script_sha256=digest(script)))
                with self.assertRaises(ValueError):
                    read_run(self.capture())

    def test_swapped_timing_method_or_view_is_rejected(self):
        path = self.root / "room/temporal-on/timing/manifest.json"
        original = json.loads(path.read_text())
        for change in ({"requested_method": "cgns"}, {"temporal_reuse": False},
                       {"scene_id": "bistro"}, {"view_id": "other"}):
            with self.subTest(change=change):
                save(path, dict(original, **change))
                index_archive(self.root)
                with self.assertRaises(ValueError):
                    self.api().read_archive(self.root).timing_records()
