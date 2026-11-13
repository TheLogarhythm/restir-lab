"""One- or two-frame 1080p resource check for the M=1 paper-style CGNS path."""

from pathlib import Path
import argparse
import json
import time
from . import cgns_paper_capture as paper, cgns_1080p_preflight as gpu, run

ROOT = Path(__file__).resolve().parents[2]


def validate_count(count):
    if type(count) is not int or count not in (1, 2):
        raise ValueError("Resource preflight requires one or two frames")


def launch(config, runtime, output, *, count=2, timeout=1800):
    validate_count(count)
    output = Path(output).resolve()
    runs = (ROOT / "runs").resolve()
    sidecar = output.parent / (output.name + ".resources.json")
    if not output.is_relative_to(runs) or output == runs or output.exists() or sidecar.exists():
        raise ValueError("Expected a new output directory below runs")
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    state = {
        "status": "running",
        "method": "cgns",
        "neighbors": 1,
        "resolution": [1920, 1080],
        "warmup": 0,
        "captured_frames": count,
        "purpose": "resource preflight; not formal experiment",
        "validation_script_sha256": run.sha(Path(__file__)),
    }
    with gpu.GpuMonitor() as monitor:
        try:
            manifest = paper.launch(
                config,
                output,
                runtime,
                method="cgns",
                width=1920,
                height=1080,
                warmup=0,
                count=count,
                timeout=timeout,
                resource_preflight=True,
            )
            state.update(
                status="completed",
                manifest=Path(manifest).relative_to(sidecar.parent).as_posix(),
                path_base="sidecar_directory",
                manifest_sha256=run.sha(manifest),
            )
        except BaseException as exc:
            state.update(status="failed", error=str(exc))
            raise
        finally:
            monitor.stop.set()
            monitor.thread.join(timeout=6)
            state["elapsed_seconds_including_outer_checks"] = time.monotonic() - started
            state["gpu_monitor"] = monitor.result()
            with sidecar.open("x", encoding="utf8") as f:
                json.dump(state, f, indent=2, allow_nan=False)
    return sidecar


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--runtime", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--count", type=int, choices=(1, 2), default=2)
    p.add_argument("--timeout", type=int, default=1800)
    a = p.parse_args()
    print(launch(a.config, a.runtime, a.output, count=a.count, timeout=a.timeout))


if __name__ == "__main__":
    main()
