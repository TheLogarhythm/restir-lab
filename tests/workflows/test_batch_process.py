"""Worker ownership across direct and Windows venv-redirected launches."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import tempfile
import sys
import time
import venv
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts/run")]
from experiment import batch_process
from experiment.artifacts import save_json


class WorkerOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.launcher = {"pid": 101, "created": 7}
        self.worker = {"pid": 102, "created": 8}
        save_json(self.root / "state.json", {"status": "launching", "launch_token": "token"})
        save_json(self.root / "process.json", {"identity": self.launcher, "token": "token"})
        self.addCleanup(patch.stopall)
        patch.object(batch_process, "exclusive", side_effect=lambda *a, **k: nullcontext()).start()
        patch.object(batch_process.os, "getpid", return_value=102).start()
        patch.object(batch_process.os, "getppid", return_value=101).start()
        patch.object(batch_process, "process_identity", side_effect=lambda pid: {
            101: self.launcher, 102: self.worker}.get(pid)).start()

    def test_redirected_worker_records_its_actual_identity(self):
        state = batch_process.claim_worker(self.root, "token")
        record = json.loads((self.root / "process.json").read_text())
        self.assertEqual(record["identity"], self.worker)
        self.assertEqual(record["launcher_identity"], self.launcher)
        self.assertEqual(state["status"], "running")

    def test_direct_worker_keeps_matching_identity(self):
        save_json(self.root / "process.json", {"identity": self.worker, "token": "token"})
        batch_process.claim_worker(self.root, "token")
        self.assertEqual(json.loads((self.root / "process.json").read_text())["identity"], self.worker)

    def test_other_process_and_recycled_parent_cannot_claim(self):
        for parent in (None, {"pid": 101, "created": 9}):
            with self.subTest(parent=parent), patch.object(batch_process, "process_identity",
                    side_effect=lambda pid: self.worker if pid == 102 else parent):
                with self.assertRaisesRegex(RuntimeError, "own"):
                    batch_process.claim_worker(self.root, "token")
        self.assertEqual(json.loads((self.root / "state.json").read_text())["status"], "launching")

    def test_wrong_token_and_duplicate_claim_fail(self):
        with self.assertRaisesRegex(RuntimeError, "own"):
            batch_process.claim_worker(self.root, "different")
        batch_process.claim_worker(self.root, "token")
        with self.assertRaisesRegex(RuntimeError, "own"):
            batch_process.claim_worker(self.root, "token")


@unittest.skipUnless(os.name == "nt", "Windows venv redirector integration")
class RedirectedWorkerWindowsTests(unittest.TestCase):
    def test_real_venv_worker_preserves_environment_and_records_child_pid(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            environment = root / "venv"
            venv.EnvBuilder(system_site_packages=True, with_pip=False).create(environment)
            (environment / "Lib/site-packages/review_env_marker.py").write_text("VALUE = 'venv-only'\n")
            script = root / "worker.py"
            script.write_text(
                "import sys, os, json\nfrom pathlib import Path\n"
                f"sys.path.insert(0, {str(ROOT / 'scripts/run')!r})\n"
                "from experiment.batch_process import claim_worker\n"
                "import review_env_marker\n"
                "root = Path(sys.argv[1])\nclaim_worker(root, 'token')\n"
                "(root / 'receipt.json').write_text(json.dumps({'pid':os.getpid(),"
                "'prefix':sys.prefix, 'marker':review_env_marker.VALUE}))\n")
            save_json(root / "state.json", {"status": "launching", "launch_token": "token"})
            with batch_process.exclusive(root / ".launch.lock"):
                launcher = batch_process.launch(
                    [str(environment / "Scripts/python.exe"), "-B", str(script), str(root)],
                    root, root / "worker.log")
                save_json(root / "process.json", {"identity": launcher, "token": "token"})
            deadline = time.monotonic() + 15
            while batch_process.alive(launcher) and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertFalse(batch_process.alive(launcher), "Diagnostic child did not finish")
            self.assertTrue((root / "receipt.json").is_file(), (root / "worker.log").read_text())
            receipt = json.loads((root / "receipt.json").read_text())
            process = json.loads((root / "process.json").read_text())
            self.assertEqual(process["identity"]["pid"], receipt["pid"])
            self.assertNotEqual(launcher["pid"], receipt["pid"])
            self.assertEqual(process["launcher_identity"], launcher)
            self.assertEqual(Path(receipt["prefix"]), environment)
            self.assertEqual(receipt["marker"], "venv-only")
