"""Exercise the saved-run adapter with real small PFM/config/geometry artifacts."""
from pathlib import Path
import importlib
import json
import sys
import tempfile
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment.config import make_config, load_definition
from experiment.scenes import load_scene
from experiment.images import write_pfm
from experiment.geometry_io import save_geometry
from rtxdi_common import sha
from build_fixtures import lighting_build


class SequenceAnalysisTests(unittest.TestCase):
    def setUp(self):
        try:
            self.api = importlib.import_module("scripts.analysis.sequence_metrics")
        except ImportError:
            self.fail("Saved-run sequence analysis adapter is not implemented")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def run_files(self, name, seed, value):
        path = self.folder / name
        path.mkdir()
        definition = load_definition()
        definition.update(frames=4, reset_frame=2, motion={"start_frame":1, "end_frame":3},
                          captures={k: [1,2,3,4] for k in ("static","motion","reset")})
        config = make_config(load_scene("cornell-box"), definition, "combined", "static",
                             seed=seed, resolution=[4,3])
        (path / "config.json").write_text(json.dumps(config))
        captures = []
        for frame in range(1,5):
            stem = path / f"frame-{frame:04d}"
            write_pfm(stem.with_suffix(".pfm.gz"), np.full((3,4,3), value+frame))
            captures.append({"frame":frame, "image_sha256":sha(stem.with_suffix(".pfm.gz"))})
        np.ones((3,4), dtype="<f4").tofile(path / "frame-0001.depth32f")
        np.full((3,4), 32767 | (32767 << 16), dtype="<u4").tofile(path / "frame-0001.normals32u")
        captures[0].update(save_geometry(path / "frame-0001", 4,3,config["scene"]["camera"]["vertical_fov"]))
        record = {"status":"completed","config_sha256":sha(path/"config.json"), "captures":captures,
                  "scene":{"sha256":"a"*64}, "build":lighting_build(), "run_id":name}
        (path / "manifest.json").write_text(json.dumps(record))
        return path

    def fixture(self):
        for method in ("a","b"):
            for n in (0,1):
                self.run_files(f"{method}{n}", n, 1+n+(method=="b"))
        write_pfm(self.folder/"ref.pfm", np.ones((3,4,3)))
        spec = {"methods":{"baseline":["a0","a1"],"variant":["b0","b1"]},
                "frames":[1,2,3,4], "lag":1, "radius":1,
                "geometry":{"run":"a0", "static_frame":1},
                "references":"ref.pfm", "regions":["all","hard","easy"]}
        path = self.folder/"inputs.json"
        path.write_text(json.dumps(spec))
        return path, spec

    def test_real_files_share_one_mask_and_write_reusable_metrics(self):
        inputs, _ = self.fixture()
        result = self.api.analyze_manifest(inputs, self.folder/"analysis")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["methods"]["baseline"]["valid_temporal_frame_pairs"], 3)
        self.assertEqual(result["methods"]["baseline"]["summary"]["hard"]["pixel_frames"], 4)
        self.assertEqual(result["methods"]["variant"]["summary"]["hard"]["pixel_frames"], 4)
        self.assertEqual(len(result["shared_regions"]), 1)
        self.assertEqual(len(list((self.folder/"analysis").rglob("*.npz"))), 1)
        self.assertTrue((self.folder/"analysis"/"frame-metrics.csv").is_file())
        self.assertTrue((self.folder/"analysis"/"summary.csv").is_file())
        with self.assertRaises(FileExistsError):
            self.api.analyze_manifest(inputs, self.folder/"analysis")

    def test_duplicate_seed_missing_frame_and_modified_capture_are_rejected(self):
        inputs, spec = self.fixture()
        spec["methods"]["baseline"] = ["a0","a0"]
        inputs.write_text(json.dumps(spec))
        with self.assertRaises(ValueError):
            self.api.analyze_manifest(inputs,self.folder/"dup")
        spec["methods"]["baseline"] = ["a0","a1"]
        spec["frames"] = [1,3,4]
        inputs.write_text(json.dumps(spec))
        with self.assertRaises(ValueError):
            self.api.analyze_manifest(inputs,self.folder/"gap")
        spec["frames"] = [1,2,3,4]
        inputs.write_text(json.dumps(spec))
        write_pfm(self.folder/"a1"/"frame-0002.pfm.gz",np.zeros((3,4,3)))
        with self.assertRaises(ValueError):
            self.api.analyze_manifest(inputs,self.folder/"changed")

    def test_geometry_provenance_and_cross_method_controls_are_checked(self):
        inputs, _ = self.fixture()
        config_path=self.folder/"b1"/"config.json"
        config=json.loads(config_path.read_text()); config["frames"][1]["reset"]=True
        config_path.write_text(json.dumps(config))
        manifest_path=config_path.with_name("manifest.json")
        manifest=json.loads(manifest_path.read_text()); manifest["config_sha256"]=sha(config_path)
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,"schedule|reset|control"):
            self.api.analyze_manifest(inputs,self.folder/"misaligned")
        config["frames"][1]["reset"]=False
        config_path.write_text(json.dumps(config)); manifest["config_sha256"]=sha(config_path)
        manifest_path.write_text(json.dumps(manifest))
        source=self.folder/"a0"/"frame-0001.geometry.npz"
        source.write_bytes(source.read_bytes()+b"changed")
        with self.assertRaisesRegex(ValueError,"geometry|Geometry"):
            self.api.analyze_manifest(inputs,self.folder/"bad-geometry")

    def test_covariance_only_all_regions_does_not_require_references_or_geometry(self):
        inputs,spec=self.fixture()
        spec.pop("geometry"); spec.pop("references"); spec.pop("regions")
        inputs.write_text(json.dumps(spec))
        result=self.api.analyze_manifest(inputs,self.folder/"cov-only")
        self.assertIsNone(result["methods"]["baseline"]["summary"]["all"]["smape_percent"])
        self.assertEqual(result["shared_regions"], {})
        self.assertEqual(set(result["methods"]["baseline"]["summary"]), {"all"})


    def edit_config(self, name, edit):
        config_path = self.folder / name / "config.json"
        config = json.loads(config_path.read_text())
        edit(config)
        config_path.write_text(json.dumps(config))
        manifest_path = config_path.with_name("manifest.json")
        manifest = json.loads(manifest_path.read_text())
        manifest["config_sha256"] = sha(config_path)
        manifest_path.write_text(json.dumps(manifest))

    def test_distinct_seed_labels_cannot_reuse_the_same_rng_stream(self):
        inputs, _ = self.fixture()
        def duplicate_stream(config):
            for frame in config["frames"]:
                frame["sampling_frame"] = frame["frame"] - 1
        for name in ("a1", "b1"):
            self.edit_config(name, duplicate_stream)
        with self.assertRaisesRegex(ValueError, "sampling|RNG|stream|seed"):
            self.api.analyze_manifest(inputs, self.folder / "duplicate-stream")

    def test_matching_seed_uses_the_same_rng_stream_across_methods(self):
        inputs, _ = self.fixture()
        def change_stream(config):
            for frame in config["frames"]:
                frame["sampling_frame"] += 8192
        self.edit_config("b1", change_stream)
        with self.assertRaisesRegex(ValueError, "sampling|RNG|stream|seed"):
            self.api.analyze_manifest(inputs, self.folder / "different-stream")

    def test_custom_disjoint_streams_are_allowed_when_methods_match(self):
        inputs, _ = self.fixture()
        def custom_stream(config):
            for frame in config["frames"]:
                frame["sampling_frame"] = 10000 + 1000 * config["seed"] + 17 * frame["frame"]
        for name in ("a0", "a1", "b0", "b1"):
            self.edit_config(name, custom_stream)
        result = self.api.analyze_manifest(inputs, self.folder / "custom-stream")
        self.assertEqual(result["status"], "completed")

    def test_sampling_frame_requires_uint32_integers(self):
        inputs, _ = self.fixture()
        for index, invalid in enumerate((-1, True, 1.5, 4294967296)):
            def invalid_stream(config):
                config["frames"][0]["sampling_frame"] = invalid
            self.edit_config("a1", invalid_stream)
            with self.subTest(value=invalid), self.assertRaisesRegex(ValueError, "sampling|RNG|stream|integer"):
                self.api.analyze_manifest(inputs, self.folder / f"invalid-stream-{index}")

    def test_repeats_within_one_method_must_share_rendering_settings(self):
        inputs, _ = self.fixture()
        def change_budget(config):
            config["arguments"]["restirDI.initialSampling.numLocalLightSamples"] += 1
            config["definition"]["initial_local_candidates"] += 1
        self.edit_config("a1", change_budget)
        with self.assertRaisesRegex(ValueError, "method|setting|repeat|configuration"):
            self.api.analyze_manifest(inputs, self.folder / "mixed-estimators")

    def test_images_must_match_declared_resolution_even_if_all_arrays_agree(self):
        inputs, spec = self.fixture()
        for key in ("geometry", "references", "regions"):
            spec.pop(key)
        inputs.write_text(json.dumps(spec))
        for name in ("a0", "a1", "b0", "b1"):
            directory = self.folder / name
            manifest_path = directory / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            for capture in manifest["captures"]:
                image = directory / f"frame-{capture['frame']:04d}.pfm.gz"
                write_pfm(image, np.ones((2, 4, 3)))  # Config declares H=3,W=4.
                capture["image_sha256"] = sha(image)
            manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "resolution|dimension|shape"):
            self.api.analyze_manifest(inputs, self.folder / "wrong-resolution")

    def test_full_history_controls_include_unmeasured_warmup_frames(self):
        inputs, spec = self.fixture()
        spec["frames"] = [2, 3, 4]
        inputs.write_text(json.dumps(spec))
        def change_warmup(config):
            config["frames"][0]["position"][0] += .25
        self.edit_config("b1", change_warmup)
        with self.assertRaisesRegex(ValueError, "schedule|control"):
            self.api.analyze_manifest(inputs, self.folder / "different-warmup")

    def test_static_geometry_is_rejected_when_camera_changes_after_cached_frame(self):
        inputs, _ = self.fixture()
        def move_camera(config):
            for frame in config["frames"][1:]:
                frame["position"][0] += .25
        for name in ("a0", "a1", "b0", "b1"):
            self.edit_config(name, move_camera)
        with self.assertRaisesRegex(ValueError, "Geometry|geometry|camera|target"):
            self.api.analyze_manifest(inputs, self.folder / "moving-static-mask")

    def test_static_geometry_can_be_shared_across_lighting_changes(self):
        inputs, spec = self.fixture()
        spec.pop("references")
        inputs.write_text(json.dumps(spec))
        def change_lighting(config):
            for frame in config["frames"]:
                frame["lighting"] = {
                    "material": "fixture-emitter",
                    "emissive_intensity_multiplier": float(frame["frame"])}
        for name in ("a0", "a1", "b0", "b1"):
            self.edit_config(name, change_lighting)
        result = self.api.analyze_manifest(inputs, self.folder / "static-geometry-changing-light")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["shared_regions"]), 1)
        for method in result["methods"].values():
            self.assertEqual(method["summary"]["hard"]["pixel_frames"], 4)

    def test_reference_changes_smape_but_never_covariance(self):
        inputs, _ = self.fixture()
        before = self.api.analyze_manifest(inputs, self.folder / "reference-one")
        write_pfm(self.folder / "ref.pfm", np.full((3, 4, 3), 7.))
        after = self.api.analyze_manifest(inputs, self.folder / "reference-seven")
        for method in ("baseline", "variant"):
            a = before["methods"][method]["summary"]["all"]
            b = after["methods"][method]["summary"]["all"]
            self.assertNotEqual(a["smape_percent"], b["smape_percent"])
            self.assertEqual(a["spatial_relative_covariance"], b["spatial_relative_covariance"])
            self.assertEqual(a["temporal_relative_autocovariance"], b["temporal_relative_autocovariance"])


if __name__ == "__main__":
    unittest.main()
