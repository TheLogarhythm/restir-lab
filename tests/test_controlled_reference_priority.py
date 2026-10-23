"""Execution priority must never change sparse target identity or launch safety."""
import copy
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/run"))
from test_controlled_sparse_selection import captures_for
from test_pdf_sparse_resume import worker_module
from experiment.controlled_suite import conditions
from experiment import controlled_evaluation as evaluation


class ReferencePriorityTests(unittest.TestCase):
    def order(self, states, priority=()):
        self.assertTrue(hasattr(evaluation, "reference_execution_order"), "execution ordering helper required")
        return evaluation.reference_execution_order(states, priority)

    def test_default_order_and_input_mapping_are_unchanged(self):
        states = [{"key": "b1", "target": {"scene_id": "bistro"}},
                  {"key": "a1", "target": {"scene_id": "arcade"}},
                  {"key": "b2", "target": {"scene_id": "bistro"}},
                  {"key": "a2", "target": {"scene_id": "arcade"}}]
        original = copy.deepcopy(states)
        self.assertEqual(self.order(states), original)
        self.assertEqual([s["key"] for s in self.order(states, ["arcade"])], ["a1", "a2", "b1", "b2"])
        self.assertEqual(states, original)

    def test_priority_preserves_all_fifteen_targets_and_logical_selections(self):
        selected = []
        for condition in conditions():
            selected.extend(evaluation.select_reference_captures(captures_for(condition)))
        inventory = evaluation.target_inventory(selected)
        frozen = json.dumps(inventory, sort_keys=True)
        ordered = self.order(inventory["states"], ["arcade"])
        self.assertEqual(len(ordered), 15)
        self.assertEqual([s["target"]["scene_id"] for s in ordered[:4]], ["arcade"] * 4)
        self.assertEqual({s["key"]: s for s in ordered}, {s["key"]: s for s in inventory["states"]})
        self.assertEqual(json.dumps(inventory, sort_keys=True), frozen)

    def test_rejects_invalid_duplicate_or_malformed_priority(self):
        for priority in (["missing"], ["arcade", "arcade"], "arcade", None, [1], [True], {}):
            with self.subTest(priority=priority), self.assertRaises(ValueError):
                self.order([], priority)

    def test_cli_passes_valid_priority_to_worker_before_claim(self):
        worker = worker_module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            instance = Mock()
            instance.reference_priority_scenes = ()
            instance.budget.record = {"authorization": {"not_before_utc": "start", "deadline_utc": "end"}}
            plan = {"reference_priority_scenes": ["arcade"], "not_before_utc": "start", "deadline_utc": "end"}
            seen = []
            def claim(path):
                seen.append(tuple(instance.reference_priority_scenes))
            with patch.object(sys, "argv", ["worker", "--references-only", "--reference-window", "window.json", "--launch-plan", str(root / "plan.json")]), patch.object(worker, "suite_path", return_value=root), patch.object(worker, "exclusive_worker", return_value=nullcontext()), patch.object(worker, "validate_launch_plan", return_value=plan), patch.object(worker, "ControlledExperiment", return_value=instance), patch.object(worker, "claim_launch", side_effect=claim):
                worker.main()
            self.assertEqual(seen, [("arcade",)])

    def test_invalid_launch_priority_rejected_before_worker_or_claim(self):
        worker = worker_module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(sys, "argv", ["worker", "--references-only", "--reference-window", "window.json", "--launch-plan", str(root / "plan.json")]), patch.object(worker, "suite_path", return_value=root), patch.object(worker, "exclusive_worker", return_value=nullcontext()), patch.object(worker, "validate_launch_plan", return_value={"reference_priority_scenes": ["arcade", "arcade"], "not_before_utc": "start", "deadline_utc": "end"}), patch.object(worker, "ControlledExperiment", side_effect=AssertionError("Invalid priority reached worker construction")) as constructor, patch.object(worker, "claim_launch") as claim, self.assertRaises(ValueError):
                worker.main()
            constructor.assert_not_called()
            claim.assert_not_called()

    def test_sparse_target_loop_honors_arcade_priority(self):
        worker = worker_module()
        instance = worker.ControlledExperiment.__new__(worker.ControlledExperiment)
        with tempfile.TemporaryDirectory() as folder:
            instance.root = Path(folder)
            bistro = {"id": "bistro-static", "scenario": "static", "rois": []}
            arcade = {"id": "arcade-static", "scenario": "static", "rois": []}
            ablation = {**bistro, "id": "ablation"}
            instance.matrix = {c["id"]: c for c in (bistro, arcade)}
            def report(condition, key):
                return {**condition, "runs": [{"off_dir": Path(key), "on_dir": Path(key)}]}
            raw = {"bistro-static": report(bistro, "b"), "arcade-static": report(arcade, "a")}
            instance.references = Mock(index={"references": {}})
            seen = []
            def ensure(captures, rois):
                key = captures[0]["key"]
                seen.append(key)
                instance.references.index["references"][key] = {"converged": True}
            instance.references.ensure.side_effect = ensure
            instance.reference_priority_scenes = ("arcade",)
            instance.reference_quality_captures = []
            instance.budget, instance.notify = Mock(), Mock()
            instance.export, instance.summary = Mock(), Mock()
            instance.condition_report = lambda condition, result, **kwargs: result
            instance.captures = lambda paths: [{"key": paths[0].name}]
            inventory = {"states": [{"key": "b", "target": {"scene_id": "bistro"}}, {"key": "a", "target": {"scene_id": "arcade"}}]}
            instance.sparse_inputs = lambda: (raw, ablation, report(ablation, "b"), [], inventory)
            with patch.object(worker, "select_reference_captures", side_effect=lambda captures, _: captures), patch.object(worker, "quality_captures", side_effect=lambda _, keys: [{"key": next(iter(keys))}]):
                instance.execute_sparse()
            self.assertEqual(seen, ["a", "b"])
            self.assertEqual([r["key"] for r in inventory["states"]], ["b", "a"])


if __name__ == "__main__":
    unittest.main()
