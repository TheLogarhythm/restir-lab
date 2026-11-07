"""Fixed single-stream references preserve exact budgets and resume provenance."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/"scripts/run")]
from tests.fixtures.provenance import lighting_build
from tests.fixtures.references import small_policy
from experiment.artifacts import save_json
from experiment.images import write_pfm
from experiment.reference import reference_config, target, target_key
from experiment.reference_allocation import allocation_totals
from tests.fixtures.comparison import load_spec, resolve_configs
from experiment.runner import relative_path
from rtxdi_common import sha
from experiment import fixed_reference as api


class FixedReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        spec = load_spec()
        spec.update(resolution=[4,3], warmup_frames=1)
        self.base = resolve_configs(spec)[0]["config"]
        self.build = lighting_build()
        self.sample = {"config":self.base, "frame":self.base["frames"][-1],
                       "manifest":{"build":self.build}, "target":target(self.base,self.base["frames"][-1],"assets")}
        self.sample["key"] = target_key(self.sample["target"])
        self.policy = small_policy()

    def checkpoint(self, samples, previous=None):
        folder = self.folder/self.sample["key"]/f"seed-1001/checkpoint-{samples}/attempt-1"
        folder.mkdir(parents=True)
        config = api.make_config(self.sample,self.policy,samples,previous)
        if previous:
            config["reference"]["resume_image"] = relative_path(previous,folder)
        save_json(folder/"config.json",config)
        image = folder/f"frame-{samples//64:04d}.pfm.gz"
        write_pfm(image,np.ones((3,4,3)))
        save_json(folder/"manifest.json", {"status":"completed","config_sha256":sha(folder/"config.json"),
            "build":self.build,"scene":{"sha256":"assets"},"captures":[{"frame":samples//64,"image_sha256":sha(image)}],
            "wall_seconds_including_startup_and_export":4})
        return image

    def reuse_spec(self):
        first=self.checkpoint(128);final=self.checkpoint(256,first)
        row=api.reference_record(self.folder,self.sample,self.policy,final,self.build)
        index=self.folder/"reference-index.json"
        save_json(index,{"schema_version":1,"kind":"fixed_budget_references","policy":self.policy,
            "build":self.build,"references":{self.sample["key"]:row}})
        spec=load_spec()
        spec.update(resolution=[4,3],warmup_frames=1,reference_budget=self.policy)
        spec["views"]={"cornell-box":spec["views"]["cornell-box"]}
        spec["views"]["cornell-box"]["reference_index"]=str(index)
        from experiment.legacy_comparison import adapt_spec
        spec=adapt_spec(spec)
        path=self.folder/"comparison-config.json";save_json(path,spec)
        return path,spec,index,final

    @patch("experiment.artifacts.validate_run_outputs")
    def test_reuse_freezes_existing_build_before_any_method_render(self, _):
        from experiment import comparison
        path,spec,index,image=self.reuse_spec()
        output=self.folder/"new-methods"
        with patch.object(comparison,"run_one",side_effect=RuntimeError("GPU deliberately disabled")):
            with self.assertRaisesRegex(RuntimeError,"GPU deliberately disabled"):
                comparison.collect(spec,output,{"DI":self.build},{"cornell-box":{"sha256":"assets"}},input_guard=lambda:None)
        saved=api.read_json(output/"comparison.json")
        self.assertEqual(saved["reference_build"],self.build)
        self.assertEqual(saved["reference_inputs"]["reference/cornell-box/direct"],{"path":str(index.resolve()),"sha256":sha(index)})
        self.assertEqual(saved["status"],"incomplete")
        self.assertFalse((output/"references").exists())

    @patch("experiment.artifacts.validate_run_outputs")
    def test_reuse_rejects_reference_damage_before_creating_output(self, _):
        from experiment import comparison
        path,spec,index,image=self.reuse_spec()
        index_bytes=index.read_bytes();image_bytes=image.read_bytes()
        for change in ("missing","image","target","policy","lighting"):
            index.write_bytes(index_bytes);image.write_bytes(image_bytes)
            data=api.read_json(index)
            if change=="missing":index.unlink()
            elif change=="image":image.write_bytes(b"corrupt")
            else:
                if change=="target":data["references"][self.sample["key"]]["target"]["resolution"]=[5,3]
                elif change=="policy":data["policy"]["seed"]=1002
                else:data["build"]["integration_sha256"]["scripts/run/rtxdi_emission.py"]="different"
                save_json(index,data)
            output=self.folder/change
            with self.subTest(change=change), patch.object(comparison,"run_one") as run:
                with self.assertRaises((ValueError,OSError)):
                    comparison.collect(spec,output,{"DI":self.build},{"cornell-box":{"sha256":"assets"}},input_guard=lambda:None)
                run.assert_not_called()
            self.assertFalse(output.exists())

    @patch("experiment.artifacts.validate_run_outputs")
    def test_detached_prepare_reuses_reference_without_reference_executable(self, _):
        from experiment import comparison_batch as batch, comparison_plan, comparison_config, comparison
        from contextlib import nullcontext
        path,spec,index,image=self.reuse_spec()
        preview=self.folder/"preview.png";preview.write_bytes(b"verified-preview-fixture")
        receipt=self.folder/"preview-check.json"
        save_json(receipt,{"status":"verified","views":{"cornell-box":{
            "target":self.sample["target"],"nonblack":True,"visual_checked":True,
            "preview":str(preview),"preview_sha256":sha(preview)}}})
        def method_only(definition,executable):
            if executable != comparison.EXECUTABLES["DI"]:raise AssertionError("Reference executable must not be required")
            return self.build
        gate=self.folder/"gate.json"; evidence=self.folder/"evidence.txt";evidence.write_text("passed")
        save_json(gate,{"status":"passed","unresolved_blockers":[],"builds":{"DI":self.build,"reference":self.build},
            "code_sha256":{},"target_compatibility":{"DI":"direct"},"checks":{
            k:{"status":"passed","evidence":[{"path":"evidence.txt","sha256":sha(evidence)}]} for k in comparison_plan.REQUIRED_CHECKS}})
        root=self.folder/"batch"
        with patch.object(batch,"preflight",side_effect=method_only), patch.object(batch,"validate_assets",return_value={"sha256":"assets"}), \
             patch.object(batch,"source_hashes",return_value={}), patch.object(comparison_plan,"source_hashes",return_value={}), \
             patch.object(batch,"validate_approved_budget"), patch.object(comparison_config,"validate_approved_budget"), \
             patch.object(batch,"query",return_value="fixture"):
            plan=batch.prepare(path,root,receipt,gate)
            self.assertEqual(plan["builds"]["reference"],self.build)
            self.assertEqual(api.read_json(root/"config.json")["references"]["direct"]["source"]["indices"]["cornell-box"],str(index))
            comparison_plan.validate_plan(root)
            from scripts.analysis import comparison_analysis as analysis, comparison_report, comparison_verify
            state=api.read_json(root/"state.json");state.update(status="running")
            def saved_analysis(source,output):
                output.mkdir();save_json(output/"analysis.json",{"status":"completed"})
            def saved_report(source,output):
                output.mkdir();save_json(output/"report.json",{});(output/"comparison.html").write_text("fixture report")
            with patch.object(batch.batch_process,"exclusive",side_effect=lambda *a,**k:nullcontext()), \
                 patch.object(batch.batch_process,"claim_worker",return_value=state), \
                 patch.object(comparison,"collect"), patch.object(analysis,"analyze",side_effect=saved_analysis), \
                 patch.object(comparison_report,"generate",side_effect=saved_report), \
                 patch.object(comparison_verify,"verify",return_value={"status":"verified"}), \
                 patch.object(batch.path_reference,"ensure_reference",side_effect=AssertionError("Must never generate a reference")):
                result=batch.work(root,"test-worker")
            self.assertEqual(result["status"],"awaiting_ui")
            self.assertFalse((root/"references").exists())
            index.write_text(index.read_text()+"\n")
            with self.assertRaisesRegex(ValueError,"reference"):
                comparison_plan.validate_plan(root)

    def test_formal_resolution_allocation_and_seed_are_independent(self):
        spec = load_spec()
        self.assertEqual(spec["resolution"],[1920,1080])
        self.assertEqual(spec["seeds"],[1])
        policy = api.validate_policy(spec["reference_budget"])
        self.assertEqual(policy["seed"],1001)
        self.assertEqual(policy["local_samples"],262144)
        self.assertEqual(policy["max_local_samples"],262144)
        for job in resolve_configs(spec):
            base = job["config"]
            sample = {"config":base,"frame":base["frames"][-1]}
            ref = api.make_config(sample,policy,262144)
            self.assertEqual([ref["width"],ref["height"]],[1920,1080])
            self.assertEqual(len(ref["frames"]),4096)
            self.assertEqual(allocation_totals(ref),dict(local=262144,environment=32768,infinite=16384))
            self.assertEqual(ref["seed"],1001)
            self.assertEqual(base["seed"],1)
            self.assertFalse(ref["definition"]["geometry_export"])

    def test_policy_rejects_invalid_cap_seed_and_checkpoints(self):
        for field, value in (("seed",True),("seed",4096),("local_samples",512),
                ("max_local_samples",128),("checkpoints",[128,128,256]),("checkpoints",[129,256]),
                ("checkpoints",[128]),("local_sampling","unknown")):
            policy = copy.deepcopy(self.policy); policy[field]=value
            with self.subTest(field=field,value=value), self.assertRaises(ValueError):
                api.validate_policy(policy)

    @patch("experiment.artifacts.validate_run_outputs")
    def test_chain_exact_counts_build_target_and_no_second_stream(self, _):
        first = self.checkpoint(128)
        final = self.checkpoint(256,first)
        config = api.validate_chain(self.folder/self.sample["key"],final,self.sample,self.policy,256,self.build)
        self.assertEqual(config["reference"]["resume_batches"],2)
        self.assertEqual(allocation_totals(config),dict(local=256,environment=32,infinite=16))
        for samples in (128,512):
            with self.assertRaises(ValueError):
                api.validate_chain(self.folder/self.sample["key"],final,self.sample,self.policy,samples,self.build)
        for change in ("build","target"):
            sample,build = copy.deepcopy(self.sample),copy.deepcopy(self.build)
            if change=="build":build["executable_sha256"]="changed"
            else:sample["target"]["resolution"]=[5,3]
            with self.subTest(change=change),self.assertRaises(ValueError):
                api.validate_chain(self.folder/self.sample["key"],final,sample,self.policy,256,build)

    @patch("experiment.artifacts.validate_run_outputs")
    def test_fixed_index_ready_is_not_precision_passed(self, _):
        first=self.checkpoint(128); final=self.checkpoint(256,first)
        record=api.reference_record(self.folder,self.sample,self.policy,final,self.build)
        index={"schema_version":1,"kind":"fixed_budget_references","policy":self.policy,
               "build":self.build,"references":{self.sample["key"]:record}}
        path=self.folder/"reference-index.json"; save_json(path,index)
        result=api.load_references(path,[self.sample],expected_policy=self.policy,expected_build=self.build)
        self.assertTrue(result[self.sample["key"]]["ready"])
        self.assertFalse(result[self.sample["key"]]["precision_verified"])
        self.assertIsNone(result[self.sample["key"]]["converged"])
        for field,value in (("seeds",[1001,2001]),("precision_checks","passed"),("samples",512),("converged",True)):
            bad=copy.deepcopy(index);bad["references"][self.sample["key"]][field]=value;save_json(path,bad)
            with self.subTest(field=field),self.assertRaises(ValueError):
                api.load_references(path,[self.sample],expected_policy=self.policy)

    def test_adaptive_timeout_covers_remaining_iterations(self):
        self.assertGreaterEqual(api.reference_timeout(4096,1024,{"iterations":64,"seconds":120}),4*3072*120/64)
        with self.assertRaises(ValueError):
            api.reference_timeout(1024,1024,None)

    def test_incomplete_checkpoint_is_never_silently_restarted(self):
        attempt=self.folder/self.sample["key"]/"seed-1001/checkpoint-128/attempt-1"
        attempt.mkdir(parents=True)
        save_json(attempt/"manifest.json",{"status":"failed"})
        with patch.object(api,"run_one") as run, self.assertRaisesRegex(RuntimeError,"diagnos"):
            api.ensure_reference(self.folder,self.sample,self.policy,self.build,{"sha256":"assets"})
        run.assert_not_called()


if __name__=="__main__":
    unittest.main()
