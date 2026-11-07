"""Frozen plans, external references, detached ownership and historical boundaries."""
from contextlib import nullcontext
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tests.fixtures.comparison import ROOT, save_json, sha
from experiment import comparison_batch as batch, comparison, comparison_plan as plan_api, batch_process
from experiment.comparison_config import load_spec, resolve_configs
from experiment.reference import target


class ComparisonPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def gate(self, builds, code=None):
        evidence = self.folder / "evidence.txt";evidence.write_text("passed")
        gate = {"status":"passed","unresolved_blockers":[],"builds":builds,"code_sha256":code or {},
                "target_compatibility":{a:"direct" if a == "DI" else "full" for a in builds if a != "reference"},
                "checks":{name:{"status":"passed","evidence":[{"path":"evidence.txt","sha256":sha(evidence)}]}
                          for name in plan_api.REQUIRED_CHECKS}}
        path = self.folder / "gate.json";save_json(path,gate)
        return path

    def test_prepare_freezes_reused_timings_and_start_is_idempotent(self):
        spec = load_spec();jobs = resolve_configs(spec)
        root = self.folder / "campaign"
        builds = {"DI":{"id":"old"},"GI":{"id":"transport"},"PT":{"id":"transport"},"reference":{"id":"path"}}
        reused,receipt = {},{"status":"verified","views":{}}
        for view in spec["views"]:
            config = next(j["config"] for j in jobs if j["view"] == view)
            physical = target(config,config["frames"][-1],"asset")
            preview = self.folder / (view + ".png");preview.write_bytes(b"preview")
            receipt["views"][view] = {"visual_checked":True,"nonblack":True,
                "target":dict(physical,resolution=[320,180]),"preview":str(preview),"preview_sha256":sha(preview)}
            for method in ("di-original","di-cgns"):
                directory = self.folder / f"{view}-{method}";directory.mkdir()
                for name in ("manifest.json","config.json","resolved.json","timings.csv","resolved-frames.jsonl","frame-0041.pfm.gz"):
                    (directory / name).write_bytes(b"historical-input")
                reused[(view,method,1)] = {"directory":directory,"manifest":{"build":builds["DI"]}}
        preview_path = self.folder / "preview.json";save_json(preview_path,receipt)
        config_path = self.folder / "config.json";save_json(config_path,spec)
        origin = self.folder / "old.json";save_json(origin,{})
        origins = {str(origin):{"path":str(origin),"sha256":sha(origin)}}
        gate = self.gate(builds)
        with patch.object(comparison,"reused_runs",return_value=(reused,origins)), \
             patch.object(batch,"validate_assets",return_value={"sha256":"asset"}), \
             patch.object(batch,"preflight",side_effect=lambda d,e:builds["reference" if "PathReference" in e.name else "GI"]), \
             patch.object(batch,"query",return_value="fixture"), \
             patch.object(batch,"source_hashes",return_value={}), patch.object(plan_api,"source_hashes",return_value={}):
            plan = batch.prepare(config_path,root,preview_path,gate)
            self.assertEqual(plan_api.validate_plan(root),plan)
            self.assertTrue(any(key.endswith("timings.csv") for key in plan["external_inputs"]))
            with patch.object(batch,"renderer_idle"), patch.object(batch_process,"exclusive",side_effect=lambda *a,**k:nullcontext()), \
                 patch.object(batch_process,"alive",side_effect=[False,True]), \
                 patch.object(batch_process,"launch",return_value={"pid":123,"created":456}) as launch:
                self.assertEqual(batch.start(root),batch.start(root))
                self.assertEqual(launch.call_count,1)
                self.assertIn("rtxdi_comparison.py",launch.call_args.args[0][2])
            next(iter(reused.values()))["directory"].joinpath("timings.csv").write_text("changed")
            with self.assertRaisesRegex(ValueError,"external"): plan_api.validate_plan(root)

    def test_changed_conformance_evidence_is_rejected(self):
        builds = {"GI":{},"reference":{}}
        gate = self.gate(builds)
        plan_api.validate_gate(gate,builds,{})
        (self.folder / "evidence.txt").write_text("changed")
        with self.assertRaisesRegex(ValueError,"evidence changed"): plan_api.validate_gate(gate,builds,{})

    def test_historical_plan_inspection_does_not_authorize_resume(self):
        config = {"definition_file":str(self.folder / "definition.json")}
        for name,data in (("config.json",config),("definition.json",{}),("preview-check.json",{})):
            save_json(self.folder / name,data)
        plan = {"schema_version":1,"config_sha256":sha(self.folder / "config.json"),
                "definition_sha256":sha(self.folder / "definition.json"),"preview_check_sha256":sha(self.folder / "preview-check.json"),
                "code_sha256":{}}
        save_json(self.folder / "plan.json",plan)
        self.assertEqual(plan_api.read_artifact_plan(self.folder),plan)
        with self.assertRaisesRegex(ValueError,"does not authorize resume"): plan_api.validate_plan(self.folder)

    def test_status_is_read_only_and_does_not_launch(self):
        save_json(self.folder / "state.json",{"status":"running","phase":"methods"})
        before = {p.name:p.read_bytes() for p in self.folder.iterdir()}
        with patch.object(batch_process,"alive",return_value=False),patch.object(batch_process,"launch") as launch:
            result = batch.status(self.folder)
            self.assertIn("attention",result);launch.assert_not_called()
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.folder.iterdir()})

    def test_inventory_includes_configs_templates_and_core(self):
        inventory = plan_api.source_hashes()
        for name in ("scripts/analysis/comparison_report.html","scripts/run/rtxdi_comparison.py",
                     "experiments/configs/cgns-di-gi-pt-static.json","experiments/configs/di-comparison-static.json",
                     "scripts/assets/gltf.py","src/metrics/comparison_metrics.py","scenes/manifest.yaml"):
            self.assertIn(name,inventory)

    def test_shared_input_inventory_preserves_first_observation(self):
        inventory = {"reference-index.json":"old"}
        comparison.merge_inventory(inventory,{"reference-index.json":"old","method.pfm":"image"})
        with self.assertRaisesRegex(ValueError,"between observations"):
            comparison.merge_inventory(inventory,{"reference-index.json":"new"})
        self.assertEqual(inventory["reference-index.json"],"old")

    def test_existing_completed_record_is_never_rendered_again(self):
        spec = load_spec();jobs = resolve_configs(spec)
        builds = {a:{} for a in spec["groups"]}
        for m in spec["methods"].values(): m["source"] = {"kind":"render"}
        root = self.folder / "methods";root.mkdir()
        first = jobs[0]
        save_json(root / "comparison.json",{"schema_version":3,"spec":spec,"builds":builds,"reuse_sources":{},"reference_build":None,"reference_inputs":{},
            "status":"incomplete","runs":[{"view":first["view"],"method":first["method"],"seed":first["seed"]}]})
        with patch.object(comparison,"run_one") as run:
            with self.assertRaisesRegex(ValueError,"refusing to render again"):
                comparison.collect(spec,root,builds,{j["config"]["scene_id"]:{} for j in jobs},input_guard=lambda:None)
            run.assert_not_called()
