"""Load an isolated script module so patched globals cannot leak between tests."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def worker_module(component="experiment/controlled_runner.py"):
    path = ROOT / "scripts/run" / component
    name = "experiment._fixture_runner" if path.parent.name == "experiment" else "_fixture_worker"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
