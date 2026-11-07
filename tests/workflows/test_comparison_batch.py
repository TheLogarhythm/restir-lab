"""Batch launch idempotence, fail-closed recovery, and independent stage checks."""
import copy
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"scripts/run")]
from experiment.artifacts import save_json
from experiment import batch_process
from experiment import comparison_batch as api


@unittest.skipUnless(os.name == "nt", "Windows process and locking integration")
class ComparisonBatchWindowsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        save_json(self.root/"state.json",{"status":"prepared","batch_id":"fixture"})
        save_json(self.root/"plan.json",{"batch_id":"fixture"})

    def test_process_identity_and_exclusive_lock(self):
        identity=batch_process.process_identity(os.getpid())
        self.assertTrue(batch_process.alive(identity))
        self.assertFalse(batch_process.alive({**identity,"created":identity["created"]+1}))
        with batch_process.exclusive(self.root/"lock"):
            with self.assertRaises(RuntimeError):
                with batch_process.exclusive(self.root/"lock"):pass
        with batch_process.exclusive(self.root/"lock"):pass

    def test_worker_handshake_waits_for_launcher_lock(self):
        import threading
        import time
        entered=threading.Event();errors=[]
        def child():
            try:
                with batch_process.exclusive(self.root/"lock",timeout=2):entered.set()
            except BaseException as exc:errors.append(exc)
        with batch_process.exclusive(self.root/"lock"):
            thread=threading.Thread(target=child);thread.start()
            time.sleep(.15)
            self.assertFalse(entered.is_set())
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors)
        self.assertTrue(entered.is_set())


class ComparisonBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        save_json(self.root / "state.json", {"status": "prepared", "batch_id": "fixture"})
        save_json(self.root / "plan.json", {"batch_id": "fixture"})
        lock = patch.object(batch_process, "exclusive", side_effect=lambda *a, **k: nullcontext())
        lock.start()
        self.addCleanup(lock.stop)

    def test_frozen_inventory_covers_external_asset_and_default_inputs(self):
        hashes = api.source_hashes()
        for name in ("scripts/assets/gltf.py", "experiments/configs/cgns-di-gi-pt-static.json", "scenes/manifest.yaml"):
            with self.subTest(name=name):
                self.assertIn(name, hashes)

    def test_ui_confirmation_records_verification_without_rendering(self):
        from rtxdi_common import sha
        report=self.root/"comparison.html";report.write_text("fixture")
        save_json(self.root/"state.json",{"schema_version":3,"status":"awaiting_ui","batch_id":"fixture","report":str(report)})
        save_json(self.root/"verification.json",{"status":"machine_verified","html_sha256":sha(report),"ui_verified":False})
        with patch.object(api.batch_process,"launch") as launch:
            state=api.confirm_ui(self.root,"User inspected the saved report")
            launch.assert_not_called()
        self.assertEqual(state["status"],"completed")
        self.assertTrue(api.read_json(self.root/"verification.json")["ui_verified"])

    @patch.object(api,"validate_plan")
    @patch.object(api,"renderer_idle")
    @patch.object(api.batch_process,"launch",return_value={"pid":123,"created":456})
    def test_repeated_start_never_launches_second_worker(self, launch, idle, validate):
        api.start(self.root)
        with patch.object(api.batch_process,"alive",return_value=True):
            api.start(self.root)
        self.assertEqual(launch.call_count,1)
        self.assertEqual(api.read_json(self.root/"state.json")["status"],"launching")

    @patch.object(api,"validate_plan")
    @patch.object(api,"renderer_idle")
    @patch.object(api.batch_process,"launch")
    def test_stale_worker_and_failed_state_require_diagnosis(self, launch, idle, validate):
        save_json(self.root/"state.json",{"status":"running","batch_id":"fixture"})
        save_json(self.root/"process.json",{"identity":{"pid":123,"created":456}})
        with patch.object(api.batch_process,"alive",return_value=False), self.assertRaisesRegex(RuntimeError,"diagnos"):
            api.start(self.root)
        launch.assert_not_called()

    @patch.object(api.batch_process,"launch")
    def test_machine_verified_and_complete_never_restart(self, launch):
        for status in ("awaiting_ui","completed"):
            save_json(self.root/"state.json",{"status":status,"batch_id":"fixture"})
            self.assertEqual(api.start(self.root)["status"],status)
        launch.assert_not_called()

    def test_ui_receipt_requires_saved_report_and_machine_verification(self):
        with self.assertRaises(ValueError):
            api.confirm_ui(self.root,"checked")


if __name__=="__main__":
    unittest.main()
