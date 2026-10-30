"""Exercise the actual Windows PowerShell supervisor with CPU-only stand-ins."""
from datetime import datetime, timedelta, timezone
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/run/start_pdf_reference.ps1"
POWERSHELL = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


@unittest.skipUnless(os.name == "nt" and POWERSHELL.is_file(), "Windows supervisor")
class SupervisorTests(unittest.TestCase):
    def setUp(self):
        probe = "if (@(Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'FullSample*' -or ($_.Name -eq 'python.exe' -and $_.CommandLine -match 'rtxdi_pdf_controlled.py') }).Count) { exit 42 }"
        if subprocess.run([str(POWERSHELL), "-NoProfile", "-Command", probe], capture_output=True).returncode == 42:
            self.skipTest("Live controlled worker requires an idle fixture test environment")

    def exercise(self, seconds, sleep_seconds):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            suite = repo / "runs/pdf-controlled-fixture"
            for path in (suite, repo / "scripts/run", repo / "build/pdf-controlled", repo / "renderers/rtxdi/build/bin"):
                path.mkdir(parents=True, exist_ok=True)
            state = suite / "state.json"
            state.write_text(json.dumps({"evaluation_scope": "sparse-v1", "status": "paused",
                "worker_pid": None, "stage": "ready", "updated_utc": "fixture"}))
            fake = repo / "scripts/run/rtxdi_pdf_controlled.py"
            fake.write_text("import json,os,sys,time\nfrom pathlib import Path\np=Path('runs/pdf-controlled-fixture/state.json')\n"
                "print('fixture-worker-stdout',flush=True);print('fixture-worker-stderr',file=sys.stderr,flush=True)\n"
                "s=json.loads(p.read_text());s.update(status='running',worker_pid=os.getpid());p.write_text(json.dumps(s))\n"
                f"time.sleep({sleep_seconds})\n"
                "s.update(status='completed');p.write_text(json.dumps(s))\n")
            # Required only for identity resolution; this file is never executed.
            (repo / "renderers/rtxdi/build/bin/FullSampleReference.exe").write_text("unused fixture")
            now = datetime.now(timezone.utc)
            window = repo / "window.json"
            values = {"not_before_utc": (now - timedelta(seconds=5)).isoformat(),
                      "deadline_utc": (now + timedelta(seconds=seconds)).isoformat()}
            window.write_text(json.dumps(values))
            plan = repo / "plan.json"
            plan.write_text(json.dumps({**values, "suite_root": str(suite)}))
            def quoted(value):
                return "'" + str(value).replace("'", "''") + "'"
            invocation = "& " + quoted(SCRIPT) + " -RepositoryRoot " + quoted(repo) + " -LaunchPlan " + quoted(plan) + " -ReferenceWindow " + quoted(window) + " -PythonExecutable " + quoted(sys.executable)
            command = [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                       "try { " + invocation + " } catch { Write-Output $_.ScriptStackTrace; throw }"]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                record = json.loads((repo / "build/pdf-controlled/worker-process.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(record.get("containment"), "windows_job_kill_on_close")
                self.assertIs(record.get("containment_verified"), True)
                for name, sentinel in (("stdout", "fixture-worker-stdout"), ("stderr", "fixture-worker-stderr")):
                    log = repo / "build/pdf-controlled" / record[name]
                    self.assertIn(sentinel, log.read_text(encoding="utf-8"))
                saved = json.loads(state.read_text(encoding="utf-8"))
                return saved
            finally:
                record = repo / "build/pdf-controlled/worker-process.json"
                if record.exists():
                    pid = json.loads(record.read_text(encoding="utf-8-sig"))["pid"]
                    # Own fixture only; never stop an unrelated real worker.
                    check = "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=" + str(pid) + "'; if ($p -and $p.CommandLine.Contains('" + str(window).replace("'", "''") + "')) { Stop-Process -Id " + str(pid) + " -Force -ErrorAction SilentlyContinue }"
                    subprocess.run([str(POWERSHELL), "-NoProfile", "-Command", check], capture_output=True)

    def test_fifteen_hour_window_allows_short_lived_worker(self):
        self.assertEqual(self.exercise(15 * 3600, .2)["status"], "completed")

    def test_short_deadline_stops_cpu_worker_and_writes_readable_state(self):
        saved = self.exercise(4, 120)
        self.assertEqual(saved["status"], "budget_exhausted")
        self.assertEqual(saved["stage"], "stopped_at_approved_deadline")
        self.assertIsNone(saved["worker_pid"])

    def abrupt_exit_fixture(self, nested_job=False, launch_failure=False):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
        kernel.CreateJobObjectW.restype = ctypes.c_void_p
        kernel.AssignProcessToJobObject.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        kernel.AssignProcessToJobObject.restype = ctypes.c_int
        kernel.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel.WaitForSingleObject.restype = ctypes.c_uint32
        kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            suite = repo / "runs/pdf-controlled-fixture"
            for path in (suite, repo / "scripts/run", repo / "build/pdf-controlled",
                         repo / "renderers/rtxdi/build/bin"):
                path.mkdir(parents=True, exist_ok=True)
            (suite / "state.json").write_text(json.dumps({"evaluation_scope": "sparse-v1",
                "status": "paused", "worker_pid": None, "stage": "ready", "updated_utc": "fixture"}))
            original_state = (suite / "state.json").read_bytes()
            (repo / "renderers/rtxdi/build/bin/FullSampleReference.exe").write_text("unused fixture")
            marker = repo / "fixture-owned-processes.json"
            (repo / "scripts/run/rtxdi_pdf_controlled.py").write_text(
                "import ctypes,json,os,subprocess,sys,time\nfrom pathlib import Path\n"
                "api=ctypes.WinDLL('kernel32',use_last_error=True)\n"
                "api.IsProcessInJob.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(ctypes.c_int)]\n"
                "member=ctypes.c_int();assert api.IsProcessInJob(ctypes.c_void_p(-1),None,ctypes.byref(member))\n"
                "marker=Path('fixture-owned-processes.json')\n"
                "child_code='import time;time.sleep(120)'\n"
                "child=None;generation=0\n"
                "while True:\n"
                " if child is None or child.poll() is not None:\n"
                "  child=subprocess.Popen([sys.executable,'-c',child_code,'--fixture-renderer',str(Path.cwd())])\n"
                "  generation+=1\n"
                "  marker.write_text(json.dumps(dict(worker_pid=os.getpid(),renderer_pid=child.pid,generation=generation,in_job_at_entry=bool(member.value))))\n"
                " time.sleep(.05)\n")
            now = datetime.now(timezone.utc)
            values = {"not_before_utc": (now - timedelta(seconds=5)).isoformat(),
                      "deadline_utc": (now + timedelta(seconds=90)).isoformat()}
            window, plan = repo / "window.json", repo / "plan.json"
            window.write_text(json.dumps(values))
            plan.write_text(json.dumps({**values, "suite_root": str(suite)}))
            command = [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                       "-File", str(SCRIPT), "-RepositoryRoot", str(repo), "-LaunchPlan", str(plan),
                       "-ReferenceWindow", str(window), "-PythonExecutable", sys.executable]
            if launch_failure:
                command[-1] = str(repo / "missing-python.exe")
            supervisor = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            outer_job, handles, owned = None, [], []
            try:
                if launch_failure:
                    stdout, stderr = supervisor.communicate(timeout=15)
                    self.assertNotEqual(supervisor.returncode, 0, (stdout + stderr).decode(errors="replace"))
                    self.assertFalse(marker.exists(), "Failed launch executed the fixture worker")
                    self.assertFalse((repo / "build/pdf-controlled/worker-process.json").exists())
                    self.assertEqual((suite / "state.json").read_bytes(), original_state)
                    check = ("@(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' "
                             "-and $_.CommandLine.Contains('" + str(repo).replace("'", "''") + "') }).Count")
                    result = subprocess.run([str(POWERSHELL), "-NoProfile", "-Command", check],
                                            capture_output=True, text=True, check=True)
                    self.assertEqual(result.stdout.strip(), "0", "Failed launch left a fixture process")
                    return
                if nested_job:
                    outer_job = kernel.CreateJobObjectW(None, None)
                    self.assertTrue(outer_job, ctypes.get_last_error())
                    self.assertTrue(kernel.AssignProcessToJobObject(outer_job, int(supervisor._handle)),
                                    ctypes.get_last_error())
                ready_deadline = time.monotonic() + 15
                while not marker.exists() and time.monotonic() < ready_deadline and supervisor.poll() is None:
                    time.sleep(.05)
                self.assertTrue(marker.exists(), "CPU worker did not start under supervisor")
                record = json.loads(marker.read_text())
                self.assertIs(record["in_job_at_entry"], True)
                original_marker = marker.read_bytes()
                owned = [record["worker_pid"], record["renderer_pid"]]
                for pid in owned:
                    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE; retains exact identity.
                    self.assertTrue(handle, f"Missing fixture process {pid}")
                    handles.append(handle)
                stopped = subprocess.run([str(POWERSHELL), "-NoProfile", "-Command",
                    f"Stop-Process -Id {supervisor.pid} -Force -ErrorAction Stop"], capture_output=True)
                self.assertEqual(stopped.returncode, 0, stopped.stderr.decode(errors="replace"))
                supervisor.wait(timeout=5)
                for pid, handle in zip(owned, handles):
                    self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0,
                                     f"Owned fixture {pid} survived abrupt supervisor exit")
                time.sleep(.3)
                self.assertEqual(marker.read_bytes(), original_marker, "Fixture worker respawned a renderer")
            finally:
                if supervisor.poll() is None:
                    supervisor.kill()
                    supervisor.wait(timeout=5)
                # Exact fixture identities only; retain cleanup even for the red run.
                quoted_repo = str(repo).replace("'", "''")
                for pid in owned:
                    check = (f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; "
                             f"if ($p -and $p.CommandLine.Contains('{quoted_repo}')) "
                             f"{{ Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue }}")
                    subprocess.run([str(POWERSHELL), "-NoProfile", "-Command", check], capture_output=True)
                supervisor.communicate(timeout=5)
                for handle in handles:
                    kernel.CloseHandle(handle)
                if outer_job:
                    kernel.CloseHandle(outer_job)

    def test_abrupt_supervisor_exit_reaps_worker_and_renderer(self):
        self.abrupt_exit_fixture()

    def test_abrupt_exit_reaps_descendants_when_supervisor_already_belongs_to_a_job(self):
        self.abrupt_exit_fixture(nested_job=True)

    def test_failed_worker_creation_does_not_execute_or_leave_a_fixture_process(self):
        self.abrupt_exit_fixture(launch_failure=True)


if __name__ == "__main__":
    unittest.main()
