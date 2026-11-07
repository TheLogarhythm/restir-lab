"""Path-spp and continuation contracts cannot reuse local-light sample counts."""
import importlib
from pathlib import Path
import sys
import unittest
import tempfile
import json
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts/run")]
from rtxdi_common import sha


class PathReferenceTests(unittest.TestCase):
    def test_runtime_mount_is_canonical_and_cannot_change_render_controls(self):
        from experiment.runtime_config import write_runtime_config, validate_runtime_config
        from experiment.artifacts import save_json
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); output=root/'deep'/'checkpoint'/'attempt-1'; output.mkdir(parents=True)
            config={'repository_root':'../../..','output':'.','scene':{'source':{'root':'assets'}},
                    'reference':{'completed_spp':8192},'frames':[{'sampling_frame':123}]}
            record=write_runtime_config(output,config)
            runtime=json.loads((output/record['path']).read_text())
            self.assertEqual(runtime,dict(config,repository_root=str(root.resolve())))
            self.assertEqual(config['repository_root'],'../../..')
            save_json(output/'manifest.json',{'runtime_config':record,'environment':{'RTXDI_EXPERIMENT_CONFIG':record['path']}})
            validate_runtime_config(output,config)
            runtime['reference']['completed_spp']=1
            save_json(output/record['path'],runtime)
            with self.assertRaisesRegex(ValueError,'Runtime configuration'):
                validate_runtime_config(output,config)
            record['sha256']=sha(output/record['path'])
            save_json(output/'manifest.json',{'runtime_config':record,'environment':{'RTXDI_EXPERIMENT_CONFIG':record['path']}})
            with self.assertRaisesRegex(ValueError,'Runtime configuration'):
                validate_runtime_config(output,config)

    def setUp(self):
        self.api = importlib.import_module("experiment.path_reference")
        from experiment.comparison_config import load_spec, resolve_configs, DI_SPEC
        self.base = resolve_configs(load_spec(DI_SPEC))[0]["config"]

    def test_explicit_path_policy_rejects_local_sample_policy(self):
        policy = self.api.policy("full")
        self.assertEqual(policy["spp"], 8192)
        self.assertEqual(policy["checkpoints"], [4096, 8192])
        self.assertEqual(policy["paths_per_iteration"], 1)
        self.api.validate_policy(policy)
        policy["local_samples"] = 8192
        with self.assertRaises(ValueError):
            self.api.validate_policy(policy)

    def test_path_config_counts_every_iteration_and_has_no_reservoir(self):
        for component, depth in (("direct", 1), ("full", 2)):
            config = self.api.make_config(self.base, self.base["frames"][-1], component, 16)
            self.assertEqual(len(config["frames"]), 16)
            self.assertEqual(config["transport"]["max_surface_scattering"], depth)
            self.assertEqual(config["mode"], "initial")
            self.assertFalse(config["definition"]["cgns"])
            self.assertEqual(config["arguments"]["lighting.indirectMode"], "NONE")
            self.assertEqual(config["reference"]["estimator"], "conventional_path_tracing")
            self.assertEqual(config["reference"]["completed_spp"], 16)
            self.assertNotIn("batch_samples_per_light_class", config["reference"])
            self.assertEqual(config["frames"][-1]["sampling_frame"], 1001 * 1048576 + 15)
            self.assertFalse(config["diagnostics"])

    def test_resume_requires_verified_parent_identity(self):
        with self.assertRaises(ValueError):
            self.api.make_config(self.base, self.base["frames"][-1], "full", 16,
                                 completed_spp=8)

    def test_runtime_rejects_wrong_depth_or_sample_count(self):
        config = self.api.make_config(self.base, self.base["frames"][-1], "full", 16)
        resolved = {"max_surface_scattering": 2, "paths_per_iteration": 1,
                    "reference_mis": "off-disjoint-support", "reference_roulette": False,
                    "reference_cutoff": 0.0, "reference_glass": "legacy-DI"}
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            counter = {"completed_spp": 16, "next_sample_index": 16, "paths_per_iteration": 1}
            (output / "path-checkpoint.json").write_text(json.dumps(counter))
            self.api.validate_runtime(output, config, resolved)
            with self.assertRaises(ValueError):
                self.api.validate_runtime(output, config, dict(resolved, max_surface_scattering=1))
            counter["completed_spp"] = 15
            (output / "path-checkpoint.json").write_text(json.dumps(counter))
            with self.assertRaises(ValueError):
                self.api.validate_runtime(output, config, resolved)

    def _write_runtime_fixture(self, output, textures):
        import csv
        from experiment.artifacts import save_json
        from tests.fixtures.cgns import cgns_runtime_record
        base, resolved, timing = cgns_runtime_record(False)
        base["arguments"]["postProcessing.textures"] = textures
        config = self.api.make_config(base, base["frames"][-1], "full", 2)
        definition = config["definition"]
        resolved.update(mode=0, textures=bool(textures),
            estimator="conventional_path_tracing", source_format="RGBA32_FLOAT accumulated reference",
            max_surface_scattering=2, paths_per_iteration=1, reference_mis="off-disjoint-support",
            reference_roulette=False, reference_cutoff=0.0, reference_glass="legacy-DI")
        for field, setting in (("numLocalLightSamples", "initial_local_candidates"),
                               ("numBrdfSamples", "initial_brdf_candidates"),
                               ("numInfiniteLightSamples", "initial_infinite_candidates"),
                               ("numEnvironmentSamples", "initial_environment_candidates")):
            resolved["initialSamplingParams"][field] = definition[setting]
        resolved["initialSamplingParams"]["localLightSamplingMode"] = 1
        save_json(output/"resolved.json", resolved)
        save_json(output/"path-checkpoint.json", {"completed_spp":2, "next_sample_index":2, "paths_per_iteration":1})
        timing.update(initial_ms=0, temporal_ms=0, spatial_ms=0, presample_lights_ms=0, presample_environment_ms=0)
        with (output/"timings.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=timing)
            writer.writeheader()
            for frame in config["frames"]:
                writer.writerow(dict(timing, frame=frame["frame"], sampling_frame=frame["sampling_frame"],
                                     capture=int(frame["capture"]), history_reset=int(frame["reset"])))
        return config, resolved

    def test_runtime_textures_match_requested_path_reference_mode(self):
        from experiment.artifacts import save_json, validate_runtime_outputs
        for requested in (1, 0):
            with self.subTest(requested=requested), tempfile.TemporaryDirectory() as temp:
                output = Path(temp)
                config, resolved = self._write_runtime_fixture(output, requested)
                self.assertEqual(config["arguments"]["postProcessing.textures"], requested)
                validate_runtime_outputs(output, config)
                for actual in (not bool(requested), None):
                    with self.subTest(actual=actual):
                        changed = dict(resolved, textures=actual)
                        if actual is None:
                            changed.pop("textures")
                        save_json(output/"resolved.json", changed)
                        with self.assertRaisesRegex(RuntimeError, "textures"):
                            validate_runtime_outputs(output, config)

    def test_legacy_reference_does_not_require_texture_acknowledgement(self):
        from experiment.artifacts import save_json, validate_runtime_outputs
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            config, resolved = self._write_runtime_fixture(output, 1)
            config["reference"]["estimator"] = resolved["estimator"] = "conventional_light_sampling"
            config["definition"].pop("path_reference_schema")
            config.pop("transport")
            resolved.pop("textures")
            save_json(output/"resolved.json", resolved)
            validate_runtime_outputs(output, config)

    def test_checkpoint_lookup_never_retries_failed_or_duplicates_completed(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            self.assertIsNone(self.api.find_checkpoint(folder))
            attempt = folder / "attempt-1"
            attempt.mkdir()
            (attempt / "manifest.json").write_text(json.dumps({"status": "failed"}))
            with self.assertRaisesRegex(ValueError, "diagnosis"):
                self.api.find_checkpoint(folder)
            (attempt / "manifest.json").write_text(json.dumps({"status": "completed"}))
            self.assertEqual(self.api.find_checkpoint(folder), attempt)
            second = folder / "attempt-2"
            second.mkdir()
            (second / "manifest.json").write_text(json.dumps({"status": "completed"}))
            with self.assertRaisesRegex(ValueError, "Multiple"):
                self.api.find_checkpoint(folder)

    def test_indexed_checkpoint_requires_canonical_unambiguous_attempt(self):
        from experiment.transport import target, target_key
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); assets={"sha256":"asset"}
            value=target(self.base,self.base["frames"][-1],"asset","full"); key=target_key(value)
            record={"target":value,"target_key":key,"policy":self.api.policy("full"),"build":{},"checkpoints":[]}
            for spp in (4096,8192):
                folder=root/key/f"checkpoint-{spp}"/"attempt-1"; folder.mkdir(parents=True)
                (folder/"manifest.json").write_text(json.dumps({"status":"completed"}))
                (folder/"config.json").write_text("{}")
                image=folder/f"frame-{spp:04d}.pfm.gz"; image.write_bytes(b"image identity fixture")
                record["checkpoints"].append({"spp":spp,"image":image.relative_to(root).as_posix(),"image_sha256":sha(image),
                    "config_sha256":sha(folder/"config.json"),"manifest_sha256":sha(folder/"manifest.json")})
            with patch.object(self.api,"validate_checkpoint",side_effect=lambda d,b,c,s,*a,**k:d/f"frame-{s:04d}.pfm.gz"):
                self.assertEqual(self.api.load_reference(root,record,self.base,"full",{},assets),image)
                sibling=root/key/"checkpoint-4096"/"attempt-2"; sibling.mkdir()
                with self.assertRaisesRegex(ValueError,"diagnosis"):
                    self.api.load_reference(root,record,self.base,"full",{},assets)
                (sibling/"manifest.json").write_text(json.dumps({"status":"completed"}))
                with self.assertRaisesRegex(ValueError,"Multiple"):
                    self.api.load_reference(root,record,self.base,"full",{},assets)


if __name__ == "__main__":
    unittest.main()
