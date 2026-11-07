"""Canonical asset mount for deep PT checkpoint directories, with input binding."""
import copy
import json
from pathlib import Path

from rtxdi_common import sha
from .artifacts import save_json

NAME = "runtime-config.json"


def canonical_config(output, config):
    value = copy.deepcopy(config)
    value["repository_root"] = str((Path(output) / config["repository_root"]).resolve())
    return value


def write_runtime_config(output, config):
    """Keep portable config.json; only shorten the actual renderer's asset mount."""
    path = Path(output) / NAME
    if path.exists():
        raise FileExistsError(path)
    save_json(path, canonical_config(output, config))
    return {"path": NAME, "sha256": sha(path)}


def validate_runtime_config(output, config):
    output = Path(output)
    manifest = output / "manifest.json"
    record = json.loads(manifest.read_text()) if manifest.exists() else {}
    binding = record.get("runtime_config")
    path = output / NAME
    if binding is None:
        if path.exists() or record.get("environment", {}).get("RTXDI_EXPERIMENT_CONFIG", "config.json") != "config.json":
            raise ValueError("Runtime configuration is not bound to the run manifest")
        return  # Legacy completed runs retain their original config.json launch.
    if (binding.get("path") != NAME or not path.is_file() or sha(path) != binding.get("sha256")
            or record.get("environment", {}).get("RTXDI_EXPERIMENT_CONFIG") != NAME
            or json.loads(path.read_text()) != canonical_config(output, config)):
        raise ValueError("Runtime configuration differs from the frozen render controls")
