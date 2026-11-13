"""Compose reusable Falcor scene profiles with independent fixed camera records.

Legacy schema-1 view files stay readable. New records share one deduplicated
inventory per scene, and a lock fingerprints every transitive JSON input.
Loading metadata never requires generated assets, renderer builds or runs/.
"""

from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative_name(value, *, description="Scene input"):
    """Validate a serialized relative name without touching generated assets."""
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(description + " path must be workspace-relative")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if posix.is_absolute() or windows.drive or windows.root or ".." in posix.parts:
        raise ValueError(description + " path must be workspace-relative")
    return posix


def relative_path(name, root, *, strict=False):
    name = relative_name(name)
    root = Path(root).resolve(strict=True)
    path = (root / name).resolve(strict=strict)
    if not path.is_relative_to(root):
        raise ValueError("Scene input escapes workspace")
    return path


def inventory_map(records):
    if not isinstance(records, list):
        raise ValueError("Invalid scene inventory")
    result = {}
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("Invalid inventory record")
        name = relative_name(item.get("path"), description="Inventory")
        digest = item.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("Invalid inventory hash")
        key = PurePosixPath(name).as_posix()
        if key in result:
            raise ValueError("Duplicate or conflicting inventory record: " + key)
        result[key] = digest
    return dict(sorted(result.items()))


def load_view(path, root, *, expected_adapted=None):
    """Return an expanded config plus hashes of consumed view/profile/inventory JSON."""
    root = Path(root).resolve(strict=True)
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError("View config escapes workspace")
    inputs = {}

    def read(target):
        raw = target.read_bytes()
        inputs[target.relative_to(root).as_posix()] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw.decode("utf-8-sig"))

    view = read(path)
    if view.get("schema_version") != 2:
        return deepcopy(view), inputs
    allowed = {
        "schema_version",
        "scene_id",
        "view_id",
        "scene_profile",
        "camera",
        "notes",
    }
    if set(view) - allowed or not all(k in view for k in allowed - {"notes"}):
        raise ValueError("Invalid reusable view fields")
    profile = read(relative_path(view["scene_profile"], root, strict=True))
    if (
        profile.get("schema_version") != 1
        or profile.get("kind") != "falcor_scene_profile"
        or profile.get("scene_id") != view["scene_id"]
        or type(profile.get("adapted")) is not bool
    ):
        raise ValueError("Invalid scene profile identity")
    adapted = profile["adapted"]
    if expected_adapted is not None and adapted is not expected_adapted:
        raise ValueError(
            "Scene profile adapter differs from the selected reference runtime"
        )
    runtime_kind = "gltf-v3" if adapted else "reference"
    if profile.get("reference_runtime", runtime_kind) != runtime_kind:
        raise ValueError("Scene profile runtime is inconsistent with its adapter")
    if adapted:
        receipt = profile.get("runtime_receipt_sha256")
        if not isinstance(receipt, str) or not re.fullmatch("[0-9a-f]{64}", receipt):
            raise ValueError("Adapted scene profile requires a pinned runtime receipt")
    elif "runtime_receipt_sha256" in profile:
        raise ValueError(
            "Native scene profile cannot select an adapted runtime receipt"
        )
    if "camera" in profile or "view_id" in profile:
        raise ValueError("Scene profile must not fix a camera")
    inventory = read(relative_path(profile["inventory"], root, strict=True))
    if (
        inventory.get("schema_version") != 1
        or inventory.get("kind") != "falcor_scene_inventory"
    ):
        raise ValueError("Unsupported scene inventory")
    inventory_map(inventory.get("resources"))
    inventory_map(inventory.get("sources"))
    metadata = {"schema_version", "kind", "profile_id", "adapted", "inventory"}
    result = {k: deepcopy(v) for k, v in profile.items() if k not in metadata}
    result.update(
        {
            "schema_version": 1,
            "view_id": view["view_id"],
            "camera": deepcopy(view["camera"]),
            "resources": deepcopy(inventory["resources"]),
            "sources": deepcopy(inventory["sources"]),
        }
    )
    if "notes" in view:
        result["notes"] = deepcopy(result.get("notes", [])) + deepcopy(view["notes"])
    from .reference_runner import camera_target

    camera_target(result["camera"])
    return result, dict(sorted(inputs.items()))


def load_locked_views(manifest, root, keys):
    root = Path(root).resolve(strict=True)
    record = json.loads(Path(manifest).read_text(encoding="utf-8-sig"))
    if (
        record.get("schema_version") != 2
        or record.get("kind") != "falcor_scene_inputs"
        or record.get("path_base") != "workspace"
        or not isinstance(record.get("views"), list)
    ):
        raise ValueError("Unsupported reusable scene manifest")
    result = {}
    for item in record["views"]:
        key = (item.get("scene_id"), item.get("view_id"))
        if key not in keys or key in result or type(item.get("adapted")) is not bool:
            raise ValueError("Invalid or duplicate scene view")
        path = relative_path(item["config_path"], root, strict=True)
        config, inputs = load_view(path, root, expected_adapted=item["adapted"])
        if inputs != item.get("input_sha256") or sha(path) != item.get("config_sha256"):
            raise ValueError("Reusable scene input hash mismatch")
        if (config.get("scene_id"), config.get("view_id")) != key:
            raise ValueError("View identity differs")
        for field in ("graph_sha256", "runtime_receipt_sha256"):
            if not re.fullmatch("[0-9a-f]{64}", item.get(field, "")):
                raise ValueError("Invalid scene input hash")
        if (
            item["adapted"]
            and config["runtime_receipt_sha256"] != item["runtime_receipt_sha256"]
        ):
            raise ValueError("Scene profile runtime receipt differs from its lock")
        assets = inventory_map(config["resources"])
        sources = inventory_map(config["sources"])
        result[key] = {
            **deepcopy(item),
            "config_path": str(path),
            "asset_sha256": assets,
            "source_sha256": sources,
        }
    if set(result) != set(keys):
        raise ValueError("Need all unique scene views")
    return result


def verify_profile_inventory(config, root, *, adapted):
    """Verify schema-2 pins against disk, including the native dependency closure.

    Reference generation may use a new camera without any existing reference
    image. Its scene bytes must still match the separately selected profile.
    """
    from . import adapted_reference_runner, reference_runner

    expected_assets = inventory_map(config["resources"])
    expected_sources = inventory_map(config["sources"])
    if adapted:
        assets = adapted_reference_runner.inventory_resources(config["resources"], root)
    else:
        assets = reference_runner.asset_inventory(config, root)
    if assets != expected_assets:
        raise ValueError("Scene resource inventory differs from the pinned profile")
    sources = (
        adapted_reference_runner.inventory_resources(config["sources"], root)
        if config["sources"]
        else {}
    )
    if sources != expected_sources:
        raise ValueError("Scene source inventory differs from the pinned profile")
    for record in config["resources"]:
        path = relative_path(record["path"], root, strict=True)
        if record.get("bytes") is not None and path.stat().st_size != record["bytes"]:
            raise ValueError("Scene resource size differs from the pinned inventory")
    return assets, sources
