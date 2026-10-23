"""Fixed Bistro routing preserves legacy references and completed reports."""
import copy
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment import controlled_reference_run as controlled
from experiment.bistro_fixed_reference import policy_metadata
from experiment.controlled_evaluation import selection_spec
from experiment.controlled_outputs import generate_versioned

BUILD = {"renderer_commit": "renderer", "executable_sha256": "exe", "shader_sha256": {}, "integration_sha256": {}}


def worker_module():
    spec = importlib.util.spec_from_file_location("bistro_worker", ROOT / "scripts/run/rtxdi_pdf_controlled.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixed_record():
    return {"policy_id": "user_fixed_single_stream_262144_v1", "reference_policy": policy_metadata(),
            "target": {"scene_id": "bistro", "resolution": [1920, 1080]}, "seeds": [1001],
            "samples": 262144, "ready": True, "converged": None, "precision_verified": False}


class BistroFixedWorkerTests(unittest.TestCase):
    def test_readiness_separates_fixed_completion_from_precision_passes(self):
        self.assertTrue(hasattr(controlled, "reference_is_ready"), "reference readiness must distinguish fixed policy")
        self.assertTrue(controlled.reference_is_ready({"converged": True}))
        self.assertTrue(controlled.reference_is_ready(fixed_record()))
        for field, value in (("ready", False), ("converged", True), ("precision_verified", True),
                             ("samples", 262145), ("samples", 262144.), ("seeds", [1001, 2001]),
                             ("target", {"scene_id": "arcade"}), ("reference_policy", {})):
            bad = fixed_record()
            bad[field] = value
            with self.subTest(field=field, value=value):
                self.assertFalse(controlled.reference_is_ready(bad))
        manager = controlled.ReferenceManager.__new__(controlled.ReferenceManager)
        manager.index = {"references": {"old": {"converged": True}, "fixed": fixed_record(),
                                       "unfinished": {"converged": False}}}
        self.assertEqual(manager.accepted_count, 1)
        self.assertEqual(manager.ready_count, 2)
        self.assertEqual(manager.fixed_budget_count, 1)

    def test_manager_routes_only_enabled_bistro_to_single_stream_and_rejects_refinement(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = controlled.ReferenceManager(Path(folder), BUILD, lambda **_: None,
                scene_policies={"bistro": policy_metadata()})
            capture = {"key": "b", "target": {"scene_id": "bistro"}, "config": {"scene_id": "bistro"}}
            with patch.object(controlled, "ensure_fixed_bistro", return_value={"b": {"image": Path("one.pfm.gz")}}) as fixed, \
                 patch.object(controlled, "run_pose", side_effect=AssertionError("dual stream forbidden")):
                result = manager.ensure([capture])
                self.assertEqual(result["b"]["image"], Path("one.pfm.gz"))
                self.assertEqual(fixed.call_args.args, (manager, [capture]))
                with self.assertRaisesRegex(ValueError, "fixed|Fixed|refin"):
                    manager.ensure([capture], min_samples=262144)
                self.assertEqual(fixed.call_count, 1)
            record = fixed_record()
            manager.index["references"]["b"] = record
            with patch.object(controlled, "fixed_record_paths", return_value={"image": Path("one.pfm.gz")}) as paths:
                self.assertEqual(manager.paths("b")["image"], Path("one.pfm.gz"))
                self.assertEqual(paths.call_args.args, (manager.directory, record))

    def test_scene_policy_resume_cannot_silently_fall_back_to_dual_stream(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manager = controlled.ReferenceManager(root, BUILD, lambda **_: None,
                scene_policies={"bistro": policy_metadata()})
            manager.index["references"]["cornell"] = {"converged": True, "samples": 512}
            controlled.save_json(manager.index_path, manager.index)
            before = manager.index_path.read_bytes()
            with self.assertRaisesRegex(ValueError, "policy|polic"):
                controlled.ReferenceManager(root, BUILD, lambda **_: None)
            self.assertEqual(manager.index_path.read_bytes(), before)
            resumed = controlled.ReferenceManager(root, BUILD, lambda **_: None,
                scene_policies={"bistro": policy_metadata()})
            self.assertEqual(resumed.index["references"]["cornell"], {"converged": True, "samples": 512})
            for policies in ({"arcade": policy_metadata()}, {"bistro": {}}):
                with self.assertRaises(ValueError):
                    controlled.ReferenceManager(root, BUILD, lambda **_: None, scene_policies=policies)

    def test_enabled_policy_never_reuses_a_legacy_bistro_average_as_fixed_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manager = controlled.ReferenceManager(root, BUILD, lambda **_: None,
                scene_policies={"bistro": policy_metadata()})
            image = root / "legacy.pfm.gz"
            image.write_bytes(b"old dual-stream average")
            digest = controlled.sha(image)
            old = {"target": {"scene_id": "bistro"}, "converged": True,
                   "image": image.name, "convergence": image.name, "previous_image": image.name,
                   "stream_images": [image.name, image.name], "stream_sha256": [digest, digest],
                   **{f"{name}_sha256": digest for name in ("image", "convergence", "previous_image")}}
            manager.index["references"] = {"bistro": old, "cornell": {"converged": True}}
            self.assertEqual(manager.ready_count, 1)
            with self.assertRaisesRegex(ValueError, "fixed|Fixed|policy"):
                manager.paths("bistro")
            self.assertEqual(image.read_bytes(), b"old dual-stream average")

    def test_default_manager_keeps_legacy_seed_pair_for_bistro(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = controlled.ReferenceManager(Path(folder), BUILD, lambda **_: None)
            capture = {"key": "b", "target": {"scene_id": "bistro", "asset_sha256": "asset"},
                       "config": {"scene_id": "bistro", "scene": {}}, "manifest": {"scene": {"registry": "fixture"}}}
            with patch.object(controlled, "validate_lighting"), \
                 patch.object(controlled, "validate_assets", return_value={"sha256": "asset"}), \
                 patch.object(controlled, "run_pose", side_effect=RuntimeError("legacy path")) as legacy:
                with self.assertRaisesRegex(RuntimeError, "legacy path"):
                    manager.ensure([capture])
                self.assertEqual(legacy.call_args.args[4], (1001, 2001))

    def test_condition_reports_use_single_reference_and_never_call_old_uncertainty_gates(self):
        worker = worker_module()
        for scenario in ("static", "motion", "lighting"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as folder:
                instance = worker.ControlledExperiment.__new__(worker.ControlledExperiment)
                instance.root, instance.references_only = Path(folder), True
                instance.reference_policies = {"bistro": policy_metadata()}
                condition = {"id": f"bistro-{scenario}", "scenario": scenario, "rois": [],
                             "scene": {"scene_id": "bistro", "preview": {"exposure_ev": 0}}}
                runs = [{"seed": seed, "off_dir": Path(f"off-{seed}"), "on_dir": Path(f"on-{seed}")} for seed in (1, 2, 3)]
                captures = [{"key": f"k-{frame}", "frame": {"frame": frame},
                             "config": {"scenario": scenario, "seed": seed, "scene_id": "bistro", "definition": {"pdf_similarity": on}}}
                            for seed in (1, 2, 3) for on in (False, True) for frame in selection_spec(scenario)["reference_frames"]]
                instance.captures = lambda _: captures
                instance.references = Mock()
                instance.references.paths.side_effect = lambda key: {"image": Path(f"{key}.pfm.gz")}
                with patch.object(worker, "check_temporal_references", side_effect=AssertionError("old temporal gate")), \
                     patch.object(worker, "assess_static_reference_differences", side_effect=AssertionError("old static gate")):
                    report = instance.condition_report(condition, {"runs": runs})
                self.assertEqual(report["reference_policy"], policy_metadata())
                self.assertEqual(sorted(report["references"]), selection_spec(scenario)["reference_frames"])
                self.assertEqual({run["seed"] for run in report["runs"]}, {1, 2, 3})
                for receipt in report["reference_assessment"].values():
                    self.assertEqual(receipt["status"], "not_evaluated")
                    self.assertIsNone(receipt["passed"])
                instance.references.ensure.assert_not_called()
                instance.state = {}
                instance.product = lambda destination, reports, generate, **_: generate(destination)
                with patch.object(worker, "export_condition", return_value={}) as export:
                    instance.export(condition, report, Path(folder) / "export")
                self.assertEqual(export.call_args.kwargs["reference_policy"], policy_metadata())
                self.assertFalse(export.call_args.kwargs["write_videos"])

    def test_fixed_lighting_skips_influence_refinement_and_records_not_evaluated(self):
        worker = worker_module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            instance = worker.ControlledExperiment.__new__(worker.ControlledExperiment)
            instance.root, instance.state, instance.references_only = root, {}, True
            instance.reference_policies = {"bistro": policy_metadata()}
            condition = {"id": "bistro-lighting", "scenario": "lighting", "rois": [], "scene": {"scene_id": "bistro"}}
            instance.matrix = {condition["id"]: condition}
            runs = [{"seed": seed, "off_dir": Path(f"off-{seed}"), "on_dir": Path(f"on-{seed}")} for seed in (1, 2, 3)]
            raw = {"id": condition["id"], "scenario": "lighting", "runs": runs}
            captures = []
            refs = {}
            for frame in selection_spec("lighting")["reference_frames"]:
                refs[frame] = root / f"reference-{frame}.pfm.gz"
                refs[frame].write_bytes(b"single conventional HDR")
                for seed in (1, 2, 3):
                    for on in (False, True):
                        captures.append({"key": str(frame), "frame": {"frame": frame},
                            "config": {"scenario": "lighting", "seed": seed, "definition": {"pdf_similarity": on}}})
            instance.captures = lambda _: captures
            instance.reference_quality_captures = captures
            instance.references = Mock(index={"references": {str(frame): fixed_record() for frame in refs}})
            instance.references.paths.side_effect = lambda key: {"image": refs[int(key)]}
            instance.budget, instance.notify, instance.export = Mock(), Mock(), Mock()
            instance.summary = Mock(return_value=root / "summary")
            inventory = {"states": [{"key": "31", "target": {"scene_id": "bistro"}}]}
            instance.sparse_inputs = lambda: ({condition["id"]: raw}, condition, raw, [], inventory)
            with patch.object(worker, "lighting_influence", side_effect=AssertionError("old influence gate")), \
                 patch.object(worker, "check_temporal_references", side_effect=AssertionError("old temporal gate")), \
                 patch.object(worker, "quality_captures", side_effect=lambda current, keys: [row for row in current if row["key"] in keys]):
                instance.execute_sparse()
            receipt = json.loads((root / "sparse-lighting-influence.json").read_text())
            self.assertEqual(receipt["status"], "not_evaluated")
            self.assertIsNone(receipt["passed"])
            self.assertEqual(len(receipt["reference_inputs"]), 2)
            self.assertEqual(instance.references.ensure.call_count, 1)
            self.assertNotIn("min_samples", instance.references.ensure.call_args.kwargs)
            self.assertEqual(instance.export.call_count, 1)

    def test_notify_reports_ready_fixed_and_precision_counts_separately(self):
        worker = worker_module()
        with tempfile.TemporaryDirectory() as folder:
            instance = worker.ControlledExperiment.__new__(worker.ControlledExperiment)
            instance.state, instance.state_path = {}, Path(folder) / "state.json"
            manager = controlled.ReferenceManager.__new__(controlled.ReferenceManager)
            manager.scene_policies = {"bistro": policy_metadata()}
            manager.index = {"references": {"accepted": {"converged": True}, "fixed": fixed_record()}}
            instance.references = manager
            instance.notify(stage="checked")
            state = json.loads(instance.state_path.read_text())
            self.assertEqual({key: state[key] for key in ("accepted_references", "precision_passed_references",
                                                        "ready_references", "fixed_budget_references")},
                             {"accepted_references": 1, "precision_passed_references": 1,
                              "ready_references": 2, "fixed_budget_references": 1})

    def retained(self, worker, root, name, scene):
        source = root / "inputs" / name
        source.mkdir(parents=True)
        runs, inputs = [], {}
        for seed in (1, 2, 3):
            run = {"seed": seed}
            for method in ("off", "on"):
                directory = source / f"{method}-{seed}"
                directory.mkdir()
                run[f"{method}_dir"] = directory
                for filename in ("manifest.json", "config.json", "captures.json", "timings.csv"):
                    path = directory / filename
                    path.write_text("original input")
                    inputs[str(path)] = worker.sha(path)
            runs.append(run)
        reference = source / "reference.pfm.gz"
        reference.write_bytes(b"accepted HDR")
        inputs[str(reference)] = worker.sha(reference)
        report = {"id": name, "scenario": "static", "runs": runs, "references": {128: reference}, "rois": [],
                  "evaluation": selection_spec("static"), "reference_assessment": {"differences": {"passed": True}}}
        identity = {"reports": json.loads(json.dumps([report], default=str)), "inputs": inputs,
                    "sources": {"historical-worker.py": "original code hash"}}
        def produce(path):
            path.mkdir(parents=True)
            (path / "summary.md").write_text("original completed report")
        output = generate_versioned(root / "analysis" / name, identity, produce)
        condition = {"id": name, "scenario": "static", "rois": [], "scene": {"scene_id": scene}}
        return condition, report, output

    def test_retained_report_validates_exact_output_and_inputs_without_requiring_current_source_hash(self):
        worker = worker_module()
        self.assertTrue(hasattr(worker, "load_retained_condition_report"), "retained report loader required")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            condition, report, output = self.retained(worker, root, "cornell-static", "cornell-box")
            before = (output / worker.RECEIPT_NAME).read_bytes()
            loaded = worker.load_retained_condition_report(output, condition, report, root=root)
            self.assertEqual(loaded["runs"], report["runs"])
            self.assertEqual(loaded["references"], report["references"])
            self.assertEqual((output / worker.RECEIPT_NAME).read_bytes(), before)
            with self.assertRaises(ValueError):
                worker.load_retained_condition_report(output, {**condition, "id": "arcade-static"}, report, root=root)
            summary_path = output / "summary.md"
            original_text = summary_path.read_bytes()
            summary_path.write_bytes(b"modified completed output")
            with self.assertRaises(ValueError):
                worker.load_retained_condition_report(output, condition, report, root=root)
            summary_path.write_bytes(original_text)
            report["references"][128].write_bytes(b"changed HDR")
            with self.assertRaisesRegex(ValueError, "input|changed|modified"):
                worker.load_retained_condition_report(output, condition, report, root=root)
            self.assertEqual((output / worker.RECEIPT_NAME).read_bytes(), before)

    def test_fixed_sparse_execution_prefills_cornell_arcade_and_only_ensures_bistro(self):
        worker = worker_module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            instance = worker.ControlledExperiment.__new__(worker.ControlledExperiment)
            instance.root, instance.reference_policies = root, {"bistro": policy_metadata()}
            raw, matrix, products, snapshots, keys = {}, {}, {}, {}, {}
            for name, scene, key in (("cornell-static", "cornell-box", "c"), ("arcade-static", "arcade", "a"),
                                     ("bistro-interior-static", "bistro", "b")):
                condition, report, output = self.retained(worker, root, name, scene)
                raw[name], matrix[name], keys[name] = report, condition, key
                if scene != "bistro":
                    products[f"analysis/{name}"] = output.relative_to(root).as_posix()
                    snapshots[output / worker.RECEIPT_NAME] = (output / worker.RECEIPT_NAME).read_bytes()
            instance.matrix, instance.state = matrix, {"products": products}
            spatial = {**matrix["bistro-interior-static"], "id": "bistro-spatial"}
            spatial_raw = {**raw["bistro-interior-static"], "id": spatial["id"]}
            instance.captures = lambda paths: [{"key": keys[Path(paths[0]).parent.name], "frame": {"frame": 128}}]
            inventory = {"states": [{"key": key, "target": {"scene_id": matrix[name]["scene"]["scene_id"]}}
                                    for name, key in keys.items()]}
            instance.sparse_inputs = lambda: (raw, spatial, spatial_raw, [], inventory)
            instance.reference_quality_captures = []
            instance.references = Mock(index={"references": {"c": {"converged": True}, "a": {"converged": True}}})
            def ensure(captures, _):
                self.assertEqual([capture["key"] for capture in captures], ["b"])
                instance.references.index["references"]["b"] = fixed_record()
            instance.references.ensure.side_effect = ensure
            instance.budget, instance.notify = Mock(), Mock()
            instance.export, instance.summary = Mock(), Mock(return_value=root / "new-summary")
            instance.condition_report = lambda condition, report, **_: {**report, "reference_policy": policy_metadata()}
            with patch.object(worker, "select_reference_captures", side_effect=lambda captures, _: captures), \
                 patch.object(worker, "quality_captures", side_effect=lambda _, selected: [{"key": next(iter(selected))}]):
                instance.execute_sparse()
            self.assertEqual(instance.references.ensure.call_count, 1)
            self.assertEqual({call.args[0]["id"] for call in instance.export.call_args_list},
                             {"bistro-interior-static", "bistro-spatial"})
            mains = [call.args[1] for call in instance.summary.call_args_list if call.args[0] == "main"]
            self.assertTrue(mains)
            self.assertEqual({report["id"] for report in mains[-1]}, set(raw))
            for path, before in snapshots.items():
                self.assertEqual(path.read_bytes(), before)

    def test_explicit_policy_execution_requires_validation_or_pinned_launch(self):
        worker = worker_module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            instance = Mock()
            argv = ["worker", "--references-only", "--reference-window", "window.json", "--reference-policy", "policy.json"]
            with patch.object(sys, "argv", argv), patch.object(worker, "suite_path", return_value=root), \
                 patch.object(worker, "exclusive_worker", return_value=nullcontext()), \
                 patch.object(worker, "load_scene_reference_policies", return_value={"bistro": policy_metadata()}), \
                 patch.object(worker, "ControlledExperiment", return_value=instance) as constructor, \
                 self.assertRaises(SystemExit) as caught:
                worker.main()
            self.assertEqual(caught.exception.code, 2)
            constructor.assert_not_called()

    def test_main_loads_policy_before_constructor_and_consumed_claim_skips_loader(self):
        worker = worker_module()
        self.assertTrue(hasattr(worker, "load_scene_reference_policies"), "main must validate the policy before state writes")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            argv = ["worker", "--references-only", "--reference-window", "window.json", "--validate-only", "--reference-policy", "policy.json"]
            instance = Mock()
            with patch.object(sys, "argv", argv), patch.object(worker, "suite_path", return_value=root), \
                 patch.object(worker, "exclusive_worker", return_value=nullcontext()), \
                 patch.object(worker, "load_scene_reference_policies", return_value={"bistro": policy_metadata()}) as load, \
                 patch.object(worker, "ControlledExperiment", return_value=instance) as constructor:
                worker.main()
            self.assertEqual(load.call_args.kwargs["policy_path"], Path("policy.json"))
            self.assertEqual(constructor.call_args.kwargs["reference_policies"], {"bistro": policy_metadata()})
            plan = root / "launch.json"
            plan.with_name(plan.name + ".started.json").write_text("{}")
            with patch.object(sys, "argv", ["worker", "--references-only", "--reference-window", "window.json", "--launch-plan", str(plan)]), \
                 patch.object(worker, "suite_path", return_value=root), patch.object(worker, "exclusive_worker", return_value=nullcontext()), \
                 patch.object(worker, "load_scene_reference_policies", side_effect=AssertionError("duplicate read policy")), \
                 patch.object(worker, "ControlledExperiment", side_effect=AssertionError("duplicate constructed worker")):
                worker.main()


if __name__ == "__main__":
    unittest.main()
