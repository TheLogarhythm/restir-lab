"""Run qualified Falcor PT comparison reference views serially in stages.

Each view has exactly eight 1024-spp realizations at 1920x1080. A batch owns
its new output directory; failed batches and completed seeds are retained.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
from pathlib import Path, PureWindowsPath
import sys
import tempfile

if __package__:
    from . import reference_runner
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.falcor import reference_runner

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from image_io.reference_average import average_seed_exrs

EXPECTED_VIEWS = {
    ('bistro', 'view-a'), ('bistro', 'view-b'), ('classroom', 'view-a'),
    ('emerald-square', 'view-a'), ('veach-ajar', 'view-a'),
    ('zero-day-measure-seven', 'view-a'),
}
CODE_FIELDS = ('graph_sha256', 'runner_sha256', 'isolated_runtime_receipt_sha256')
SHARED_CODE_FIELDS = ('graph_sha256', 'runner_sha256')
BATCH_LOCK = ROOT / 'build/falcor/.reference-batch.lock'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def save_status(path, record):
    fd, name = tempfile.mkstemp(prefix='.batch-status-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(record, stream, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_config_snapshot(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if data.get("schema_version") == 2:
        from scripts.falcor.scene_inputs import load_view

        return load_view(path, ROOT, expected_adapted=False)
    return data, None


def config_inputs_unchanged(path, config, inputs):
    try:
        if load_config_snapshot(path) != (config, inputs):
            return False
        if inputs is not None:
            from scripts.falcor.scene_inputs import verify_profile_inventory

            verify_profile_inventory(config, ROOT, adapted=False)
        return True
    except (OSError, ValueError):
        return False


def _config_record(key, path, digest, output, version):
    _, inputs = load_config_snapshot(path)
    return {
        "scene_id": key[0],
        "view_id": key[1],
        "path": _config_reference(path, output, version),
        "sha256": digest,
        **({"config_input_sha256": inputs} if inputs is not None else {}),
    }


def validate_configs(config_paths):
    if not 1 <= len(config_paths) <= 6:
        raise ValueError('One to six view configurations are required')
    selected = []
    for path in config_paths:
        path = Path(path).resolve(strict=True)
        obj, _ = load_config_snapshot(path)
        reference_runner.validate_scene_qualification(obj)
        runtime_kind(obj)
        key = (obj.get('scene_id'), obj.get('view_id'))
        selected.append((key, path, sha(path)))
    keys = {row[0] for row in selected}
    if not keys.issubset(EXPECTED_VIEWS) or len(keys) != len(selected):
        raise ValueError('Configurations must contain unique requested views')
    return sorted(selected, key=lambda row: row[0])


def validate_seed(manifest_path, output_dir, seed_index, config, config_hash):
    manifest_path = Path(manifest_path).resolve(strict=True)
    output_dir = Path(output_dir).resolve(strict=True)
    if manifest_path != output_dir / 'manifest.json':
        raise ValueError('Unexpected seed manifest path')
    record = json.loads(manifest_path.read_text(encoding='utf-8'))
    if (record.get('status') != 'completed' or record.get('kind') != 'reference_seed'
            or record.get('seed_index') != seed_index or record.get('samples_per_pixel') != 1024
            or record.get('sample_seed_first') != seed_index * 1024
            or record.get('sample_seed_last') != seed_index * 1024 + 1023
            or record.get('resolution') != [1920, 1080]
            or record.get('scene_config') != config or record.get('config_sha256') != config_hash):
        raise ValueError('Seed result does not match its formal configuration')
    artifacts = record.get('artifacts', [])
    if len(artifacts) != 1 or Path(artifacts[0].get('file', '')).name != artifacts[0].get('file'):
        raise ValueError('Seed must contain one local EXR artifact')
    image = (output_dir / artifacts[0]['file']).resolve(strict=True)
    if image.parent != output_dir or image.suffix.lower() != '.exr' or sha(image) != artifacts[0].get('sha256'):
        raise ValueError('Seed EXR provenance mismatch')
    keys = (*CODE_FIELDS, 'asset_sha256')
    if any(not record.get(key) for key in keys):
        raise ValueError('Seed provenance is incomplete')
    return record, image


def runtime_kind(config):
    kind = config.get('reference_runtime', 'reference')
    if kind == 'filtered':
        raise ValueError('The filtered Bistro FBX runtime is retired')
    if kind != 'reference':
        raise ValueError('Unknown reference runtime')
    if 'runtime_receipt_sha256' in config:
        raise ValueError('Reference runtime receipt override is not supported')
    return kind


def current_provenance(config):
    if __package__:
        from . import reference_runtime
    else:
        import reference_runtime
    runtime_kind(config)
    assets = reference_runner.asset_inventory(config)
    receipt_hash = sha(reference_runtime.DEST / 'receipt.json')
    return {
        'asset_sha256': assets,
        'graph_sha256': sha(Path(__file__).with_name('reference_graph.py')),
        'runner_sha256': sha(Path(__file__).with_name('reference_runner.py')),
        'isolated_runtime_receipt_sha256': receipt_hash,
    }


def completed_attempt(seed_root, seed, config, config_hash, expected):
    found = []
    if not seed_root.exists():
        return None
    for attempt in sorted(seed_root.iterdir()):
        if not attempt.is_dir() or not re.fullmatch(r'attempt-[0-9]{2,}', attempt.name):
            raise ValueError('Unexpected seed attempt entry')
        manifest = attempt / 'manifest.json'
        if not manifest.exists():
            continue
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('status') != 'completed':
            continue
        record, image = validate_seed(manifest, attempt, seed, config, config_hash)
        if any(record[key] != value for key, value in expected.items()):
            raise ValueError('Completed seed provenance differs from current inputs')
        found.append((manifest, image))
    if len(found) > 1:
        raise ValueError('Ambiguous multiple completed seed attempts')
    return found[0] if found else None


def next_attempt(seed_root):
    seed_root.mkdir(parents=True, exist_ok=True)
    existing = []
    for path in seed_root.iterdir():
        match = re.fullmatch(r'attempt-([0-9]{2,})', path.name)
        if not match or not path.is_dir():
            raise ValueError('Unexpected seed attempt entry')
        existing.append(int(match.group(1)))
    return seed_root / f'attempt-{max(existing, default=0) + 1:02d}'


def _config_reference(path, output, version):
    """Serialize a config relative to the batch, preserving legacy records."""
    if version == 1:
        return str(path)
    try:
        return Path(os.path.relpath(path, output)).as_posix()
    except ValueError as exc:
        raise ValueError('Batch and configurations must be on the same volume') from exc


def _read_config_reference(value, output, version):
    if not isinstance(value, str) or not value:
        raise ValueError('Invalid batch configuration path')
    if version == 1:
        return Path(value)
    if Path(value).is_absolute() or PureWindowsPath(value).drive or '\\' in value:
        raise ValueError('Expected a relative batch configuration path')
    return output / value


def _run_batch(config_paths, output, *, timeout=7200, resume=False):
    selected = validate_configs(config_paths)
    if (
        not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("Timeout must be positive and finite")
    for _, path, _ in selected:
        config, inputs = load_config_snapshot(path)
        if inputs is not None:
            from scripts.falcor.scene_inputs import verify_profile_inventory

            verify_profile_inventory(config, ROOT, adapted=False)
    output = Path(output).resolve()
    status_path = output / "manifest.json"
    version = 2
    config_records = [
        _config_record(key, path, digest, output, version)
        for key, path, digest in selected
    ]
    if resume:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        version = status.get("schema_version")
        if version not in (1, 2) or (
            version == 2 and status.get("path_base") != "batch_directory"
        ):
            raise ValueError("Invalid batch path format")
        previous = status.get("configurations", [])
        if not previous:
            raise ValueError("Batch configuration provenance is missing")
        # Every earlier configuration remains fixed and qualified, even when
        # the caller supplies only the newly added views for the next stage.
        prior = validate_configs(
            [
                _read_config_reference(record["path"], output, version)
                for record in previous
            ]
        )
        actual_prior = [
            _config_record(key, path, digest, output, version)
            for key, path, digest in prior
        ]
        if actual_prior != previous:
            raise ValueError("Batch configuration provenance changed")
        if status.get("budget") != {
            "seeds": 8,
            "samples_per_seed": 1024,
            "resolution": [1920, 1080],
        }:
            raise ValueError("Batch budget changed")
        if status.get("status") == "completed":
            raise ValueError("Batch is already completed")
        merged = {row[0]: row for row in prior}
        for row in selected:
            if row[0] in merged and merged[row[0]][1:] != row[1:]:
                raise ValueError("Batch configuration provenance changed")
            merged[row[0]] = row
        selected = sorted(merged.values(), key=lambda row: row[0])
        config_records = [
            _config_record(key, path, digest, output, version)
            for key, path, digest in selected
        ]
        status["configurations"] = config_records
        status.setdefault("resume_history", []).append(
            {
                "previous_status": status.get("status"),
                "previous_error": status.get("error"),
                "resumed_utc": now(),
            }
        )
        status["status"] = "running"
        status.pop("error", None)
    else:
        output.mkdir(parents=True, exist_ok=False)
        status = {
            "schema_version": 2,
            "path_base": "batch_directory",
            "status": "running",
            "started_utc": now(),
            "budget": {
                "seeds": 8,
                "samples_per_seed": 1024,
                "resolution": [1920, 1080],
            },
            "configurations": config_records,
            "views": [],
        }
    save_status(status_path, status)
    try:
        code_provenance = None
        historical = {(v.get("scene_id"), v.get("view_id")) for v in status["views"]}
        completed = {
            (v.get("scene_id"), v.get("view_id"))
            for v in status["views"]
            if v.get("status") == "completed"
        }
        # Validate completed and interrupted historical views before any new render.
        execution_order = sorted(
            selected,
            key=lambda row: (
                0 if row[0] in completed else 1 if row[0] in historical else 2,
                row[0],
            ),
        )
        for (scene, view), config_path, config_hash in execution_order:
            config, config_inputs = load_config_snapshot(config_path)
            if sha(config_path) != config_hash:
                raise ValueError("Configuration changed during batch")
            view_dir = output / scene / view
            view_dir.mkdir(parents=True, exist_ok=True)
            matches = [
                v
                for v in status["views"]
                if (v.get("scene_id"), v.get("view_id")) == (scene, view)
            ]
            if len(matches) > 1:
                raise ValueError("Duplicate view status")
            if matches:
                view_status = matches[0]
                if (
                    view_status.get("config_sha256") != config_hash
                    or view_status.get("config")
                    != _config_reference(config_path, output, version)
                    or view_status.get("config_input_sha256") != config_inputs
                ):
                    raise ValueError("View configuration provenance changed")
            else:
                view_status = {
                    "scene_id": scene,
                    "view_id": view,
                    "config": _config_reference(config_path, output, version),
                    "config_sha256": config_hash,
                    "status": "running",
                    "seeds": [],
                    **(
                        {"config_input_sha256": config_inputs}
                        if config_inputs is not None
                        else {}
                    ),
                }
                status["views"].append(view_status)
            expected = current_provenance(config)
            if config_inputs is not None:
                from scripts.falcor.scene_inputs import verify_profile_inventory

                pinned_assets, pinned_sources = verify_profile_inventory(
                    config, ROOT, adapted=False
                )
                if expected["asset_sha256"] != pinned_assets:
                    raise ValueError(
                        "Scene inventory changed during reference preflight"
                    )
                expected = {**expected, "source_sha256": pinned_sources}
            if config_inputs is not None:
                expected = {**expected, "config_input_sha256": config_inputs}
            current_code = {key: expected[key] for key in SHARED_CODE_FIELDS}
            if code_provenance is None:
                code_provenance = current_code
            if code_provenance != current_code:
                raise ValueError("Renderer code provenance changed during batch")
            # Preflight every prior seed before starting new work. Never discard
            # acknowledged entries if a later seed or invocation fails.
            old_seeds = list(view_status.get("seeds", []))
            if len({item["index"] for item in old_seeds}) != len(old_seeds):
                raise ValueError("Duplicate recorded seed")
            previous_by_seed = {item["index"]: item for item in old_seeds}
            if any(index not in range(8) for index in previous_by_seed):
                raise ValueError("Invalid recorded seed")
            prior_completed = view_status.get("status") == "completed"
            ready = {}
            for seed in range(8):
                seed_root = view_dir / "seeds" / f"seed-{seed + 1:02d}"
                existing = completed_attempt(
                    seed_root, seed, config, config_hash, expected
                )
                previous = previous_by_seed.get(seed)
                if previous:
                    if existing is None:
                        raise ValueError("Previously completed seed is missing")
                    manifest, image = existing
                    if (
                        str(Path(manifest).relative_to(output)) != previous["manifest"]
                        or sha(image) != previous["hdr_sha256"]
                    ):
                        raise ValueError("Previously recorded seed provenance mismatch")
                if prior_completed and existing is None:
                    raise ValueError("Completed view is missing a seed")
                ready[seed] = existing
            view_status["status"] = "running"
            save_status(status_path, status)
            images = []
            for seed in range(8):
                if sha(config_path) != config_hash or not config_inputs_unchanged(
                    config_path, config, config_inputs
                ):
                    raise ValueError("Configuration changed during batch")
                seed_root = view_dir / "seeds" / f"seed-{seed + 1:02d}"
                existing = ready[seed]
                if existing is None:
                    seed_dir = next_attempt(seed_root)
                    print(f"Rendering {scene}/{view}, seed {seed + 1}/8", flush=True)
                    manifest = reference_runner.launch(
                        config_path, seed_dir, seed, 1024, 1920, 1080, timeout
                    )
                    record, image = validate_seed(
                        manifest, seed_dir, seed, config, config_hash
                    )
                    if any(record[key] != value for key, value in expected.items()):
                        raise ValueError("Seed provenance differs from current inputs")
                else:
                    manifest, image = existing
                    print(f"Reusing {scene}/{view}, seed {seed + 1}/8", flush=True)
                images.append(image)
                entry = {
                    "index": seed,
                    "manifest": str(Path(manifest).relative_to(output)),
                    "hdr_sha256": sha(image),
                }
                view_status["seeds"] = [
                    item for item in view_status["seeds"] if item["index"] != seed
                ] + [entry]
                view_status["seeds"].sort(key=lambda item: item["index"])
                save_status(status_path, status)
            if not config_inputs_unchanged(config_path, config, config_inputs):
                raise ValueError("Scene profile changed before averaging")
            if prior_completed:
                destination = (output / view_status["reference"]).resolve(strict=True)
                if (
                    destination.parent != view_dir.resolve()
                    or sha(destination) != view_status["reference_sha256"]
                ):
                    raise ValueError(
                        "Previously completed reference provenance mismatch"
                    )
            else:
                destination = view_dir / "reference.exr"
                if destination.exists():
                    number = 2
                    while (view_dir / f"reference-attempt-{number:02d}.exr").exists():
                        number += 1
                    destination = view_dir / f"reference-attempt-{number:02d}.exr"
                average_seed_exrs(images, destination)
            if not config_inputs_unchanged(config_path, config, config_inputs):
                raise ValueError("Scene profile changed during averaging")
            view_status.update(
                status="completed",
                reference=str(destination.relative_to(output)),
                reference_sha256=sha(destination),
                completed_utc=now(),
            )
            save_status(status_path, status)
        if {row[0] for row in selected} == EXPECTED_VIEWS:
            status.update(status="completed", completed_utc=now())
        else:
            status.update(status="partial", stage_completed_utc=now())
    except BaseException as exc:
        for view_status in status["views"]:
            if view_status.get("status") == "running":
                view_status["status"] = "failed"
        status.update(status="failed", error=str(exc), ended_utc=now())
        save_status(status_path, status)
        raise
    status.pop("error", None)
    save_status(status_path, status)
    return status_path


def run_batch(config_paths, output, *, timeout=7200, resume=False):
    with reference_runner.exclusive_operation(BATCH_LOCK):
        return _run_batch(config_paths, output, timeout=timeout, resume=resume)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configs', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=7200)
    parser.add_argument('--resume', action='store_true', help='verify and reuse completed seed attempts in an incomplete batch')
    args = parser.parse_args()
    print(run_batch(args.configs, args.output, timeout=args.timeout, resume=args.resume))


if __name__ == '__main__':
    main()
