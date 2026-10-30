"""Sparse restarts must consume existing captures and fail closed."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts/run")]


from tests.fixtures.modules import worker_module


class SparseResumeTests(unittest.TestCase):
    def test_references_only_missing_method_never_renders(self):
        worker = worker_module()
        with tempfile.TemporaryDirectory() as folder:
            instance = worker.ControlledExperiment.__new__(worker.ControlledExperiment)
            instance.root = Path(folder)
            instance.references_only = True
            instance.assets = {"cornell-box": {"sha256": "asset"}}
            condition = worker.conditions()[0]
            with patch.object(worker, "run_one") as render, self.assertRaisesRegex(ValueError, "Completed method"):
                instance.render(condition, 1, False)
            render.assert_not_called()

    def test_sparse_execute_skips_pilot_method_and_raw_export_stages(self):
        worker = worker_module()
        instance = worker.ControlledExperiment.__new__(worker.ControlledExperiment)
        with patch.object(instance, "execute_sparse") as sparse, \
             patch.object(instance, "technical_pilot") as pilot, \
             patch.object(instance, "export_raw") as raw:
            instance.execute(references_only=True)
        sparse.assert_called_once_with(validate_only=False)
        pilot.assert_not_called()
        raw.assert_not_called()

    def test_old_dense_entry_cannot_resume_sparse_prepared_state(self):
        worker = worker_module()
        instance = worker.ControlledExperiment.__new__(worker.ControlledExperiment)
        instance.state = {"evaluation_scope": "sparse-v1"}
        with patch.object(instance, "technical_pilot") as pilot, self.assertRaisesRegex(ValueError, "references-only"):
            instance.execute()
        pilot.assert_not_called()

    def test_ready_static_products_survive_later_reference_budget_exhaustion(self):
        worker = worker_module()
        instance = worker.ControlledExperiment.__new__(worker.ControlledExperiment)
        with tempfile.TemporaryDirectory() as folder:
            instance.root = Path(folder)
            static = {"id": "static", "scenario": "static", "rois": []}
            dynamic = {"id": "motion", "scenario": "motion", "rois": []}
            ablation = {**static, "id": "ablation"}
            instance.matrix = {c["id"]: c for c in (static, dynamic)}
            def report(condition, key):
                return {**condition, "runs": [{"off_dir": Path(key), "on_dir": Path(key)}]}
            raw = {"static": report(static, "k1"), "motion": report(dynamic, "k2")}
            instance.references = Mock(index={"references": {}})
            def ensure(captures, rois):
                key = captures[0]["key"]
                if key == "k2":
                    raise worker.BudgetExceeded("deadline")
                instance.references.index["references"][key] = {"converged": True}
            instance.references.ensure.side_effect = ensure
            instance.reference_quality_captures = []
            instance.budget = Mock()
            instance.notify = Mock()
            instance.export, instance.summary = Mock(), Mock()
            instance.condition_report = lambda condition, result, **kwargs: result
            instance.captures = lambda paths: [{"key": paths[0].name}]
            inventory = {"states": [{"key": "k1"}, {"key": "k2"}]}
            instance.sparse_inputs = lambda: (raw, ablation, report(ablation, "k1"), [], inventory)
            with patch.object(worker, "select_reference_captures", side_effect=lambda captures, _: captures), \
                 patch.object(worker, "quality_captures", side_effect=lambda _, keys: [{"key": next(iter(keys))}]), \
                 self.assertRaises(worker.BudgetExceeded):
                instance.execute_sparse()
            self.assertEqual(instance.export.call_args_list[0].args[0]["id"], "static")
            self.assertTrue(instance.summary.called)

    def test_duplicate_one_shot_returns_before_worker_mutates_state(self):
        from contextlib import nullcontext
        worker = worker_module("rtxdi_pdf_controlled.py")
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            plan = directory / "launch.json"
            plan.with_name(plan.name + ".started.json").write_text("{}")
            with patch.object(sys, "argv", ["worker", "--references-only", "--reference-window", "window.json", "--launch-plan", str(plan)]), \
                 patch.object(worker, "suite_path", return_value=directory), \
                 patch.object(worker, "exclusive_worker", return_value=nullcontext()), \
                 patch.object(worker, "ControlledExperiment") as constructor:
                worker.main()
            constructor.assert_not_called()

    def test_raw_product_reuse_matches_current_runs_and_original_timings(self):
        worker = worker_module("experiment/controlled_reports.py")
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            timing = output / "timings.csv"
            timing.write_text("original")
            report = {"id": "same", "runs": [{"off_dir": Path("off"), "on_dir": Path("on")}], "references": {}}
            identity = {"reports": json.loads(json.dumps([report], default=str)), "inputs": {str(timing): worker.sha(timing)}}
            (output / worker.RECEIPT_NAME).write_text(json.dumps({"identity": identity, "identity_sha256": "identity"}))
            with patch.object(worker, "_matches", return_value=True):
                worker.validate_retained_raw_product(output, report)
                with self.assertRaisesRegex(ValueError, "different method"):
                    worker.validate_retained_raw_product(output, {**report, "id": "other"})
                timing.write_text("changed")
                with self.assertRaisesRegex(ValueError, "timings changed"):
                    worker.validate_retained_raw_product(output, report)


if __name__ == "__main__":
    unittest.main()
