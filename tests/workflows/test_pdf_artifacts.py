"""CPU-only artifact checks against small, hand-constructed HDR captures."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import shutil
import subprocess

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/run"))
sys.path.insert(0, str(ROOT))
from experiment.images import write_pfm


class PdfArtifactTests(unittest.TestCase):
    def exporter(self):
        try:
            return importlib.import_module("scripts.analysis.pdf_artifacts")
        except ModuleNotFoundError:
            self.fail("The offline PDF artifact exporter has not been implemented")

    def fixture(self, root, frames=(1, 128)):
        off, on, refs = (root / name for name in ("off", "on", "refs"))
        for directory in (off, on, refs):
            directory.mkdir()
        references = {}
        for frame in frames:
            reference = np.ones((4, 8, 3), dtype=np.float32)
            for directory, value in ((off, 3), (on, 1), (refs, 1)):
                path = directory / f"frame-{frame:04d}.pfm.gz"
                write_pfm(path, reference * value)
                if directory == refs:
                    references[frame] = path
        return off, on, references

    def test_fixed_map_scale_preserves_equal_values_and_reports_clipping(self):
        module = self.exporter()
        signed = np.array([[-100., -50., 0., 50., 100.]])
        pixels, clipped = module.colorize_map(signed, "signed_relative")
        self.assertEqual(clipped, .4)
        np.testing.assert_array_equal(pixels[0, 0], pixels[0, 1])
        np.testing.assert_array_equal(pixels[0, 3], pixels[0, 4])
        self.assertGreater(pixels[0, 1, 2], pixels[0, 1, 0])
        self.assertGreater(pixels[0, 3, 0], pixels[0, 3, 2])
        self.assertGreater(int(pixels[0, 2].min()), 245)
        other, _ = module.colorize_map(np.array([[0., 50.]]), "signed_relative")
        np.testing.assert_array_equal(other[0, 1], pixels[0, 3])
        smape, _ = module.colorize_map(np.array([[0., 50., 100.]]), "smape")
        cropped, _ = module.colorize_map(np.array([[50.]]), "smape")
        np.testing.assert_array_equal(smape[0, 1], cropped[0, 0])

    def test_missing_reference_and_acceptance_fail_before_creating_output(self):
        module = self.exporter()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            off, on, refs = self.fixture(root)
            output = root / "artifacts"
            with self.assertRaisesRegex(ValueError, "accepted"):
                module.export_condition(output, off, on, refs, references_accepted=False,
                    expected_resolution=(8, 4), write_videos=False)
            self.assertFalse(output.exists())
            del refs[128]
            with self.assertRaisesRegex(ValueError, "reference|Reference"):
                module.export_condition(output, off, on, refs, references_accepted=True,
                    expected_resolution=(8, 4), write_videos=False)
            self.assertFalse(output.exists())

    def test_static_export_orders_frames_retains_maps_and_shared_roi(self):
        module = self.exporter()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            off, on, refs = self.fixture(root, frames=(128, 1))
            output = root / "artifacts"
            result = module.export_condition(output, off, on, refs, references_accepted=True,
                expected_resolution=(8, 4), expected_frames=(1, 128), write_videos=False,
                rois=[dict(name="receiver", x=2, y=1, width=3, height=2)])
            self.assertEqual(result["frames"], [1, 128])
            self.assertEqual(result["temporal_pairs"], [])
            self.assertEqual(result["scales"]["signed_relative"]["range"], [-50., 50.])
            self.assertEqual(result["rois"], [dict(name="receiver", x=2, y=1, width=3, height=2)])
            with np.load(output / "maps/pdf-off/frame-0128.npz") as maps:
                self.assertEqual(maps["signed_relative"].dtype, np.float64)
                self.assertGreater(maps["signed_relative"].min(), 199.)
                self.assertNotIn("trmae", maps)
            with Image.open(output / "frames/reference/frame-0128.png") as image:
                self.assertEqual(image.size, (8, 4))
            with Image.open(output / "rois/receiver/reference/frame-0128.png") as image:
                self.assertEqual(image.size, (3, 2))
            saved = json.loads((output / "manifest.json").read_text())
            self.assertEqual(saved["frames"], [1, 128])
            self.assertEqual(saved["frame_metrics"][0]["method"], "pdf-off")
            self.assertEqual(saved["frame_metrics"][0]["signed_clipped_fraction"], 1.)

    def test_temporal_export_requires_pilot_scale_and_labels_later_frame(self):
        module = self.exporter()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            off, on, refs = self.fixture(root, frames=(31, 32, 33))
            output = root / "artifacts"
            with self.assertRaisesRegex(ValueError, "pilot|temporal_scale"):
                module.export_condition(output, off, on, refs, references_accepted=True,
                    expected_resolution=(8, 4), write_videos=False)
            self.assertFalse(output.exists())
            result = module.export_condition(output, off, on, refs, references_accepted=True,
                expected_resolution=(8, 4), write_videos=False, temporal_scale=(0, 2))
            self.assertEqual(result["temporal_pairs"], [[31, 32], [32, 33]])
            self.assertEqual(result["scales"]["trmae"]["range"], [0., 2.])
            self.assertEqual(result["temporal_keyframes"]["32"]["pair"], [31, 32])
            self.assertEqual(result["temporal_keyframes"]["33"]["label"], "32 -> 33")
            with np.load(output / "maps/pdf-off/frame-0033.npz") as maps:
                np.testing.assert_array_equal(maps["trmae"], np.zeros((4, 8)))

    def test_mismatched_configs_and_invalid_shapes_leave_no_artifacts(self):
        module = self.exporter()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            off, on, refs = self.fixture(root)
            base = dict(seed=1, width=8, height=4, definition=dict(pdf_similarity=False),
                        frames=[dict(frame=1, position=[0, 0, 0])])
            (off / "config.json").write_text(json.dumps(base))
            base["definition"]["pdf_similarity"] = True
            base["frames"][0]["position"][0] = 1
            (on / "config.json").write_text(json.dumps(base))
            output = root / "bad-config"
            with self.assertRaisesRegex(ValueError, "config alignment"):
                module.export_condition(output, off, on, refs, references_accepted=True,
                    expected_resolution=(8, 4), write_videos=False)
            self.assertFalse(output.exists())
            base["frames"][0]["position"][0] = 0
            (on / "config.json").write_text(json.dumps(base))
            write_pfm(on / "frame-0128.pfm.gz", np.ones((4, 7, 3)))
            with self.assertRaisesRegex(ValueError, "resolution/alignment"):
                module.export_condition(output, off, on, refs, references_accepted=True,
                    expected_resolution=(8, 4), write_videos=False)
            self.assertFalse(output.exists())

    def test_native_panel_keeps_reference_off_on_order_and_pixels(self):
        module = self.exporter()
        images = [Image.new("RGB", (80, 40), color) for color in ("red", "green", "blue")]
        panel = module._panel(images, ["Reference", "PDF off", "PDF on"])
        self.assertEqual(panel.width, 240)
        self.assertEqual(panel.getpixel((40, 48)), (255, 0, 0))
        self.assertEqual(panel.getpixel((120, 48)), (0, 128, 0))
        self.assertEqual(panel.getpixel((200, 48)), (0, 0, 255))

    def test_alignment_allows_confirmed_pdf_toggle_in_resolved_state(self):
        module = self.exporter()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            off, on, _ = self.fixture(root)
            for directory, enabled in ((off, False), (on, True)):
                (directory / "config.json").write_text(json.dumps(
                    dict(seed=1, definition=dict(pdf_similarity=enabled))))
                (directory / "resolved.json").write_text(json.dumps(
                    dict(pdf_similarity=enabled, width=8, height=4, pdf_history_mode=0)))
            self.assertTrue(module._config_alignment(off, on)["checked"])
            changed = dict(pdf_similarity=True, width=8, height=4, pdf_history_mode=1)
            (on / "resolved.json").write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "resolved-state"):
                module._config_alignment(off, on)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/ffprobe not installed")
    def test_video_is_1080p_30fps_and_preserves_input_order(self):
        module = self.exporter()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            off, on, refs = self.fixture(root, frames=(2, 1))
            for frame, value in ((1, .02), (2, 8.)):
                write_pfm(refs[frame], np.full((4, 8, 3), value))
            output = root / "video"
            module.export_condition(output, off, on, refs, references_accepted=True,
                expected_resolution=(8, 4), temporal_scale=(0, 5), write_videos=True)
            probe = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate,nb_frames", "-of", "json",
                str(output / "videos/reference.mp4")], capture_output=True, check=True, text=True)
            stream = json.loads(probe.stdout)["streams"][0]
            self.assertEqual((stream["width"], stream["height"]), (1920, 1080))
            self.assertEqual(stream["r_frame_rate"], "30/1")
            self.assertEqual(stream["nb_frames"], "2")
            decode = subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-i",
                str(output / "videos/reference.mp4"), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                capture_output=True, check=True)
            pixels = np.frombuffer(decode.stdout, dtype=np.uint8).reshape(2, 1080, 1920, 3)
            self.assertLess(float(pixels[0, 500:600, 800:900].mean()), 60.)
            self.assertGreater(float(pixels[1, 500:600, 800:900].mean()), 230.)


class PdfSummaryTests(unittest.TestCase):
    def summarizer(self):
        try:
            return importlib.import_module("scripts.analysis.pdf_summary")
        except ModuleNotFoundError:
            self.fail("The independent-seed PDF summary has not been implemented")

    def condition(self, root, scenario="static"):
        frames = [128] if scenario == "static" else list(range(1, 97))
        refs = root / "refs"
        refs.mkdir()
        references = {}
        for frame in frames:
            path = refs / f"frame-{frame:04d}.pfm.gz"
            write_pfm(path, np.ones((2, 2, 3)))
            references[frame] = path
        runs = []
        for seed in (1, 2, 3):
            pair = {"seed": seed}
            for method in ("off", "on"):
                directory = root / f"{method}-{seed}"
                directory.mkdir()
                pair[f"{method}_dir"] = directory
                for frame in frames:
                    value = (seed + 1 if method == "off" else 1) if scenario == "static" else (
                        2 if method == "off" and frame == 33 else 3 if method == "off" and frame == 65 else 1)
                    write_pfm(directory / f"frame-{frame:04d}.pfm.gz", np.full((2, 2, 3), value))
                count = 128 if scenario == "static" else 96
                timing = ["frame,gpu_ms,initial_ms,spatial_ms"]
                for frame in range(1, count + 1):
                    cost = (1000 if frame <= 40 else seed * 10) if scenario == "static" else seed * 10
                    timing.append(f"{frame},{cost * (2 if method == 'on' else 1)},1,3")
                (directory / "timings.csv").write_text("\n".join(timing) + "\n")
            runs.append(pair)
        return dict(id="fixture", runs=runs, references=references, scenario=scenario, expected_resolution=(2, 2),
                    rois=[dict(name="receiver", x=0, y=0, width=1, height=1)])

    def test_summary_uses_independent_seed_errors_and_paired_differences(self):
        module = self.summarizer()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            condition = self.condition(root)
            result = module.summarize_suite(root / "summary", [condition], references_accepted=True)
            full = [row for row in result["summaries"] if row["region"] == "full"]
            off = next(row for row in full if row["method"] == "pdf-off")
            self.assertAlmostEqual(off["rmae_mean"], 2.)
            self.assertAlmostEqual(off["rmae_sd"], 1.)
            self.assertAlmostEqual(off["smape_mean"], 47.77659077, places=6)
            self.assertEqual(off["gpu_ms_mean"], 20.)
            self.assertEqual(off["gpu_ms_sd"], 10.)
            paired = next(row for row in result["paired_differences"] if row["region"] == "full")
            self.assertAlmostEqual(paired["rmae_mean"], -2.)
            self.assertAlmostEqual(paired["rmae_sd"], 1.)
            self.assertEqual(paired["gpu_ms_mean"], 20.)
            self.assertEqual(paired["gpu_ms_sd"], 10.)
            self.assertIn("smape_reference_status", paired)
            self.assertEqual(paired["smape_reference_status"], "unassessed")
            self.assertEqual(paired["smape_direction"], "no resolved difference")
            self.assertTrue((root / "summary/summary.csv").is_file())
            self.assertTrue((root / "summary/summary.md").is_file())

    def test_reference_variation_can_leave_a_positive_difference_unresolved(self):
        module = self.summarizer()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            condition = self.condition(root)
            for run in condition["runs"]:
                write_pfm(run["off_dir"] / "frame-0128.pfm.gz", np.full((2, 2, 3), 2.))
                write_pfm(run["on_dir"] / "frame-0128.pfm.gz", np.full((2, 2, 3), 2.0001))
            # Hand-compute the delta from the float32 PFM values, independently of the exporter.
            on = float(np.float32(2.0001))
            current = 100 * (on - 1) / (on + 1 + 1e-4) - 100 / (3 + 1e-4)
            receipt = {"current": current,
                "variants": {"half_a": current - .01, "half_b": current + .01, "previous": current},
                "max_reference_change": .01, "direction_resolved": False, "state": "inconclusive"}
            assessment = {"differences": {"passed": True, "regions": {"full": {
                "static": {"metrics": {"smape": {"paired_difference": receipt}}}}}}}
            condition["reference_assessment"] = assessment
            result = module.summarize_suite(root / "summary", [condition], references_accepted=True)
            paired = next(row for row in result["paired_differences"] if row["region"] == "full")
            self.assertGreater(paired["smape_mean"], 0.)
            self.assertIn("smape_reference_status", paired)
            self.assertEqual(paired["smape_reference_status"], "inconclusive")
            self.assertEqual(paired["smape_direction"], "no resolved difference")
            self.assertEqual(result["conditions"][0]["reference_assessment"], assessment)
            saved = json.loads((root / "summary/analysis.json").read_text())
            self.assertEqual(saved["conditions"][0]["reference_assessment"], assessment)
            markdown = (root / "summary/summary.md").read_text(encoding="utf-8")
            self.assertIn("no resolved difference", markdown)
            self.assertNotIn("SMAPE increases", markdown)

    def test_small_reference_changes_resolve_direction_only_for_the_matching_delta(self):
        module = self.summarizer()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            condition = self.condition(root)
            current = -(100 / 3.0001 + 200 / 4.0001 + 300 / 5.0001) / 3
            receipt = {"current": current,
                "variants": {"half_a": current + .001, "half_b": current - .001, "previous": current + .002},
                "max_reference_change": .002, "direction_resolved": True, "state": "resolved"}
            condition["reference_assessment"] = {"differences": {"passed": True, "regions": {"full": {
                "static": {"metrics": {"smape": {"paired_difference": receipt}}}}}}}
            result = module.summarize_suite(root / "resolved", [condition], references_accepted=True)
            paired = next(row for row in result["paired_differences"] if row["region"] == "full")
            self.assertIn("smape_reference_status", paired)
            self.assertEqual(paired["smape_reference_status"], "resolved")
            self.assertEqual(paired["smape_direction"], "improves")
            self.assertIn("improvement resolved", (root / "resolved/summary.md").read_text(encoding="utf-8"))
            receipt["current"] = -1.
            result = module.summarize_suite(root / "mismatched", [condition], references_accepted=True)
            paired = next(row for row in result["paired_differences"] if row["region"] == "full")
            self.assertEqual(paired["smape_reference_status"], "mismatch")
            self.assertEqual(paired["smape_direction"], "no resolved difference")

    def test_temporal_phase_average_assigns_boundaries_to_later_frame(self):
        module = self.summarizer()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            condition = self.condition(root, "motion")
            condition["reference_assessment"] = {"temporal": {"passed": True, "regions": {"full": {
                "1-32": {"paired_difference": {"current": 0.,
                    "variants": {"half_a": 0., "half_b": 0., "previous": 0.},
                    "max_reference_change": 0., "direction_resolved": False, "state": "equal"}},
                "33-64": {"paired_difference": {"current": -6.25,
                    "variants": {"half_a": -6.2, "half_b": -6.3, "previous": -6.25},
                    "max_reference_change": .05, "direction_resolved": True, "state": "resolved"}},
                "65-96": {"paired_difference": {"current": -12.5,
                    "variants": {"half_a": 1.5, "half_b": -12.4, "previous": -12.6},
                    "max_reference_change": 14., "direction_resolved": False, "state": "inconclusive"}},
            }}}}
            spatial_delta = -(100 / 3.0001) / 32
            condition["reference_assessment"]["temporal"]["regions"]["full"]["33-64"]["metrics"] = {
                "smape": {"paired_difference": {"current": spatial_delta,
                    "variants": {"half_a": spatial_delta + .0001, "half_b": spatial_delta - .0001,
                                 "previous": spatial_delta},
                    "max_reference_change": .0001, "direction_resolved": True, "state": "resolved"}}}
            result = module.summarize_suite(root / "summary", [condition], references_accepted=True)
            off = {row["phase"]: row for row in result["summaries"]
                   if row["region"] == "full" and row["method"] == "pdf-off"}
            self.assertEqual(off["startup"]["trmae_mean"], 0.)
            self.assertAlmostEqual(off["motion-change"]["trmae_mean"], 6.25)
            self.assertAlmostEqual(off["recovery"]["trmae_mean"], 12.5)
            seed_rows = [row for row in result["seed_metrics"]
                        if row["seed"] == 1 and row["region"] == "full" and row["method"] == "pdf-off"]
            self.assertEqual({row["phase"]: row["temporal_pair_count"] for row in seed_rows},
                             {"startup": 31, "motion-change": 32, "recovery": 32})
            paired = {row["phase"]: row for row in result["paired_differences"] if row["region"] == "full"}
            self.assertEqual(paired["startup"]["trmae_reference_status"], "equal")
            self.assertEqual(paired["motion-change"]["trmae_direction"], "improves")
            self.assertEqual(paired["recovery"]["trmae_direction"], "no resolved difference")
            self.assertEqual(paired["motion-change"]["smape_reference_status"], "resolved")
            self.assertEqual(paired["motion-change"]["smape_direction"], "improves")
            self.assertEqual(paired["recovery"]["smape_reference_status"], "unassessed")

    def test_summary_rejects_incomplete_seeds_before_creating_output(self):
        module = self.summarizer()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            condition = self.condition(root)
            condition["runs"].pop()
            with self.assertRaisesRegex(ValueError, "seeds|Seeds"):
                module.summarize_suite(root / "summary", [condition], references_accepted=True)
            self.assertFalse((root / "summary").exists())

    def test_summary_rejects_unaccepted_references_and_nonfinite_gpu_cost(self):
        module = self.summarizer()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            condition = self.condition(root)
            with self.assertRaisesRegex(ValueError, "accepted"):
                module.summarize_suite(root / "summary", [condition], references_accepted=False)
            path = condition["runs"][0]["off_dir"] / "timings.csv"
            path.write_text(path.read_text().replace("128,10,1,3", "128,nan,1,3"))
            with self.assertRaisesRegex(ValueError, "GPU timings"):
                module.summarize_suite(root / "summary", [condition], references_accepted=True)
            self.assertFalse((root / "summary").exists())


if __name__ == "__main__":
    unittest.main()
