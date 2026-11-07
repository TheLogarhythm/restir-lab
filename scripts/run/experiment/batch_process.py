"""Small Windows process/lock primitives for durable local batches."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import threading
import time


@contextmanager
def exclusive(path, *, timeout=0):
    """Byte-range OS lock: released by the OS on process exit, including crashes."""
    if os.name != "nt":
        raise RuntimeError("This renderer batch requires Windows")
    import msvcrt
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0");stream.flush()
        stream.seek(0)
        deadline=time.monotonic()+timeout
        while True:
            try:
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                break
            except OSError as exc:
                if time.monotonic()>=deadline:
                    raise RuntimeError(f"Another process owns {path.name}") from exc
                time.sleep(.05)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)


def process_identity(pid):
    """PID plus Windows creation time avoids treating a recycled PID as our worker."""
    kernel = ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD,wintypes.BOOL,wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4))
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD))
    handle = kernel.OpenProcess(0x1000,False,pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # ERROR_INVALID_PARAMETER: exited PID
            return None
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        code=wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle,ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        if code.value != 259:
            return None
        times=[wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle,*(ctypes.byref(t) for t in times)):
            raise ctypes.WinError(ctypes.get_last_error())
        return {"pid":pid,"created":(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime}
    finally:
        kernel.CloseHandle(handle)


def alive(identity):
    return bool(identity) and process_identity(identity["pid"]) == identity


def claim_worker(root, token):
    """Bind the executing worker, including a live Windows venv redirector child.

    The launcher holds this lock until its PID and token are durable. A different
    PID may claim only when its parent still has that exact PID/creation time;
    preserving sys.executable also preserves the selected virtual environment.
    """
    from .artifacts import save_json
    root = Path(root)
    with exclusive(root / ".launch.lock", timeout=10):
        state = json.loads((root / "state.json").read_text(encoding="utf-8"))
        process = json.loads((root / "process.json").read_text(encoding="utf-8"))
        worker = process_identity(os.getpid())
        launcher = process.get("identity")
        if (state.get("status") != "launching" or state.get("launch_token") != token
                or process.get("token") != token or not worker or not launcher):
            raise RuntimeError("Worker does not own the persisted launch")
        if worker != launcher:
            if process_identity(os.getppid()) != launcher:
                raise RuntimeError("Worker does not own the persisted launcher process")
            process.update(launcher_identity=launcher, identity=worker)
            save_json(root / "process.json", process)
        timestamp = datetime.now(timezone.utc).isoformat()
        state.update(status="running", started_utc=timestamp, updated_utc=timestamp)
        save_json(root / "state.json", state)
        return state


def launch(command, directory, log):
    """No visible terminal; PID identity is persisted by the caller before unlocking."""
    with Path(log).open("ab",buffering=0) as output:
        process = subprocess.Popen(command,cwd=directory,stdin=subprocess.DEVNULL,stdout=output,
            stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW|
            subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.DETACHED_PROCESS)
    identity=process_identity(process.pid)
    if identity is None:
        process.wait()
        raise RuntimeError("Background worker exited during startup; inspect worker.log")
    # Retain/reap the handle without blocking the caller or owning child lifetime.
    threading.Thread(target=process.wait, name="detached-worker-reaper", daemon=True).start()
    return identity
