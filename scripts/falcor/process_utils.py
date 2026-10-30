"""Process exclusion and bounded cleanup for the Falcor adapters."""

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import signal
import subprocess


@contextmanager
def exclusive_operation(path):
    """Serialize this checkout's adapters, including preflight and artifact writes.

    Keep the lock file in place: deleting it would let new callers lock a different
    inode. Closing its handle (also on process exit) releases the OS-owned lock.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        try:
            if os.name == "nt":
                import msvcrt

                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            raise RuntimeError(
                "Another Falcor build or run is active in this checkout"
            ) from exc
        yield


def check_renderer_idle():
    """Detect renderers outside the lock, including children of a killed launcher."""
    if os.name != "nt":
        return
    busy = subprocess.check_output(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-Process -Name 'FullSample*','Mogwai*' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id",
        ],
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if busy.strip():
        raise RuntimeError("Another renderer is active; leave it untouched and wait")


def stop_process(proc):
    """Stop the owned tree; return cleanup diagnostics without masking its error.

    POSIX callers must launch with start_new_session=True. On Windows, a failed
    tree kill falls back to the process handle, but cannot prove child cleanup.
    """
    errors = []
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=5,
                check=True,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"Process tree termination failed: {exc}")

    try:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"Owned process could not be reaped: {exc}")
    return "; ".join(errors) or None
