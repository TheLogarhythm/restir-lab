"""Frozen plans, external references, detached ownership and historical boundaries."""
from contextlib import nullcontext
import copy
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tests.fixtures.comparison import ROOT, save_json, sha
from experiment import comparison_batch as batch, comparison, comparison_plan as plan_api, batch_process, saved_runs
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
             patch.object(batch,"source_hashes",return_value={}), patch.object(plan_api,"source_hashes",return_value={}), \
             patch.object(saved_runs,"ROOT",self.folder):
            plan = batch.prepare(config_path,root,preview_path,gate)
            self.assertEqual(plan_api.validate_plan(root),plan)
            self.assertEqual(plan["path_schema"], "repository_root_v1")
            self.assertTrue(all(v["path_base"] == "repository_root" for v in plan["external_inputs"].values()))
            previews = json.loads((root / "preview-check.json").read_text())["views"]
            self.assertTrue(all(v["preview_path_base"] == "repository_root" for v in previews.values()))
            self.assertTrue(any(key.endswith("timings.csv") for key in plan["external_inputs"]))
            with patch.object(batch,"renderer_idle"), patch.object(batch_process,"exclusive",side_effect=lambda *a,**k:nullcontext()), \
                 patch.object(batch_process,"alive",side_effect=[False,True]), \
                 patch.object(batch_process,"launch",return_value={"pid":123,"created":456}) as launch:
                self.assertEqual(batch.start(root),batch.start(root))
                self.assertEqual(launch.call_count,1)
                self.assertIn("rtxdi_comparison.py",launch.call_args.args[0][2])
                actual = launch.call_args.args[0]
                process = json.loads((root/'process.json').read_text())
                self.assertEqual(process['command_kind'], 'path_normalized_copy_of_executed_argv')
                for index in (0, 2, 5):
                    self.assertEqual(saved_runs.resolve_source(process['command'][index], process['command_path_bases'][str(index)]), Path(actual[index]).resolve())
            next(iter(reused.values()))["directory"].joinpath("timings.csv").write_text("changed")
            with self.assertRaisesRegex(ValueError,"external"): plan_api.validate_plan(root)

    def test_portable_plan_rebinds_after_checkout_move_and_checks_hashes(self):
        import shutil
        from experiment import saved_runs
        workspace = self.folder / 'checkout-a'
        root = workspace / 'runs' / 'campaign'
        root.mkdir(parents=True)
        (root / 'definition.json').write_text('{}')
        (root / 'preview-check.json').write_text('{}')
        save_json(root / 'config.json', {'definition_file':'runs/campaign/definition.json'})
        source = workspace / 'frozen-input'
        source.write_text('original')
        plan = {'schema_version': 3, 'path_schema':'repository_root_v1',
                'config_sha256':sha(root/'config.json'), 'definition_sha256':sha(root/'definition.json'),
                'preview_check_sha256':sha(root/'preview-check.json'), 'code_sha256':{}, 'builds':{},
                'external_inputs':{'source':{'path':'frozen-input','path_base':'repository_root','sha256':sha(source)},
                                   'conformance':{'path':'frozen-input','path_base':'repository_root','sha256':sha(source)}}}
        save_json(root/'plan.json',plan)
        with patch.object(saved_runs,'ROOT',workspace), patch.object(plan_api,'ROOT',workspace), patch.object(plan_api,'validate_gate'):
            self.assertEqual(plan_api.read_artifact_plan(root),plan)
        moved = self.folder/'checkout-b'; shutil.copytree(workspace,moved)
        with patch.object(saved_runs,'ROOT',moved), patch.object(plan_api,'ROOT',moved), patch.object(plan_api,'validate_gate'):
            self.assertEqual(plan_api.read_artifact_plan(moved/'runs/campaign'),plan)
            (moved/'frozen-input').write_text('changed')
            with self.assertRaisesRegex(ValueError,'external'):
                plan_api.read_artifact_plan(moved/'runs/campaign')
            plan['external_inputs']['source']['path'] = '../outside'
            save_json(moved/'runs/campaign/plan.json',plan)
            with self.assertRaises(ValueError):
                plan_api.read_artifact_plan(moved/'runs/campaign')

    def test_spec_sources_normalize_only_project_internal_paths(self):
        project = self.folder / 'project'
        project.mkdir()
        inside = project / 'runs' / 'index.json'
        outside = self.folder / 'outside.json'
        spec = {'methods': {'m': {'source': {'kind':'comparison', 'index':str(inside), 'method':'m'}}},
                'references': {'direct': {'source': {'kind':'indices', 'indices': {'view':str(inside), 'external':str(outside)}}}}}
        with patch.object(batch, 'ROOT', project):
            normalized = batch.portable_spec_sources(spec)
        self.assertEqual(normalized['methods']['m']['source']['index'], 'runs/index.json')
        self.assertEqual(normalized['references']['direct']['source']['indices']['view'], 'runs/index.json')
        self.assertEqual(normalized['references']['direct']['source']['indices']['external'], str(outside))
        self.assertEqual(normalized['source_path_base'], 'repository_root_for_relative_paths; external_inputs_are_absolute')
        self.assertEqual(spec['methods']['m']['source']['index'], str(inside))

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

    def test_status_and_confirmation_accept_portable_and_legacy_paths(self):
        report = self.folder / 'report' / 'comparison.html'
        report.parent.mkdir()
        report.write_text('verified')
        source = self.folder / 'references' / 'checkpoint'
        source.mkdir(parents=True)
        (source / 'timings.csv').write_text('frame,gpu_ms\n10,50\n')
        progress = {'status':'rendering','directory':'references/checkpoint','directory_path_base':'batch_root',
                    'component':'full','view':'v','spp_target':100}
        state = {'schema_version':3,'status':'running','phase':'references','progress':progress}
        save_json(self.folder/'state.json',state)
        with patch.object(batch_process,'alive',return_value=False):
            self.assertEqual(batch.status(self.folder)['live_progress']['completed_spp'],10)
            import shutil
            with tempfile.TemporaryDirectory() as moved_parent:
                moved = Path(moved_parent) / 'campaign'
                shutil.copytree(self.folder, moved)
                self.assertEqual(batch.status(moved)['live_progress']['completed_spp'],10)
            state['progress']['directory'] = str(source)
            state['progress'].pop('directory_path_base')
            save_json(self.folder/'state.json',state)
            self.assertEqual(batch.status(self.folder)['live_progress']['completed_spp'],10)
            state['progress'].update(directory='../outside',directory_path_base='batch_root')
            save_json(self.folder/'state.json',state)
            with self.assertRaises(ValueError): batch.status(self.folder)
        save_json(self.folder/'verification.json',{'html_sha256':sha(report)})
        for value, base in (('report/comparison.html','batch_root'),(str(report),None)):
            state = {'schema_version':3,'status':'awaiting_ui','report':value}
            if base: state['report_path_base']=base
            save_json(self.folder/'state.json',state)
            with patch.object(batch_process,'exclusive',side_effect=lambda *a,**k:nullcontext()):
                self.assertEqual(batch.confirm_ui(self.folder,'checked')['status'],'completed')

    def test_process_command_is_recorded_as_portable_derivative_of_actual_argv(self):
        command = [sys.executable,'-B',str(ROOT/'scripts/run/rtxdi_comparison.py'),'work','--root',str(self.folder),'--token','abc']
        record = batch.record_command(command)
        self.assertEqual(record['command_kind'],'path_normalized_copy_of_executed_argv')
        for index in (0,2,5):
            field = record['command_path_bases'][str(index)]
            self.assertEqual(saved_runs.resolve_source(record['command'][index],field),Path(command[index]).resolve())
        self.assertEqual(record['command'][1],'-B')
        self.assertEqual(record['command'][-1],'abc')

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
