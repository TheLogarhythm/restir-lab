"""Resumable conventional references for explicitly selected controlled runs."""
from collections import defaultdict
from functools import partial
import json
from pathlib import Path
import shutil

from rtxdi_common import RENDERER, sha
from .artifacts import save_json
from .controlled_reference import ControlledAssessment
from .reference import (CONVERGENCE_METRIC, REFERENCE_SCHEMA_VERSION, ImageCache,
                        pfm_path, reference_config, validate_lighting)
from .reference_runner import BUILD_FIELDS, checkpoint_image, run_pose, validate_checkpoint
from .reference_allocation import PROGRESS_UNIT, allocation_totals
from .runner import relative_path, run_one
from .scenes import validate_assets

REFERENCE_EXE = RENDERER / "build/bin/FullSampleReference.exe"
REFERENCE_SEEDS = (1001, 2001)
BATCH_SAMPLES = 64
CLASS_COUNTS = {"local": 64, "environment": 8, "infinite": 4}
CHECKPOINTS = tuple(128 * 2**i for i in range(14))


def checkpoint_schedule(values):
    try:
        values = tuple(values)
    except TypeError as error:
        raise ValueError("Invalid reference checkpoint schedule") from error
    if (not values or any(type(n) is not int or n < 2 * BATCH_SAMPLES
                          or n % BATCH_SAMPLES or n > 1048576 for n in values)
            or any(b != 2 * a for a, b in zip(values, values[1:]))):
        raise ValueError("Reference checkpoints must double within supported batch limits")
    return values


class ReferenceManager:
    def __init__(self, directory, build, notify, *, timeout=21600, checkpoints=None,
                 before_segment=None):
        self.directory = Path(directory)
        self.build, self.notify, self.timeout = build, notify, timeout
        self.before_segment = before_segment
        self.checkpoints = checkpoint_schedule(CHECKPOINTS if checkpoints is None else checkpoints)
        self.assets = {}
        self.directory.mkdir(parents=True, exist_ok=True)
        self.index_path = self.directory / "reference-index.json"
        self.index = {"schema_version": REFERENCE_SCHEMA_VERSION, "quality_version": 1,
            "convergence_metric": CONVERGENCE_METRIC, "build": build,
            "seeds": list(REFERENCE_SEEDS), "batch_samples": BATCH_SAMPLES,
            "checkpoints": list(self.checkpoints), "references": {}}
        if self.index_path.exists():
            old = json.loads(self.index_path.read_text(encoding="utf-8"))
            for key in ("schema_version", "quality_version", "convergence_metric", "seeds", "batch_samples"):
                if old.get(key) != self.index[key]:
                    raise ValueError(f"Reference resume settings changed: {key}")
            previous = checkpoint_schedule(old.get("checkpoints"))
            if self.checkpoints != previous:
                raise ValueError("Reference checkpoint schedule changed; explicit user approval required")
            if any(old["build"].get(k) != build[k] for k in BUILD_FIELDS):
                raise ValueError("Reference executable or shaders changed")
            self.index = old
        self.index.update(sample_count_unit=PROGRESS_UNIT, default_batch_counts=dict(CLASS_COUNTS))
        self.index["checkpoints"] = list(self.checkpoints)
        save_json(self.index_path, self.index)

    def ensure(self, captures, rois=(), *, min_samples=0):
        """Reassess saved checkpoints against every supplied method before reuse."""
        validate_lighting(captures, self.build)
        groups = defaultdict(list)
        for capture in captures:
            groups[capture["key"]].append(capture)
        for key, group in groups.items():
            sample = group[0]
            asset_hash = sample["target"]["asset_sha256"]
            if asset_hash not in self.assets:
                scene = {**sample["config"]["scene"], "registry": sample["manifest"]["scene"]["registry"]}
                self.assets[asset_hash] = validate_assets(scene)
            assets = self.assets[asset_hash]
            if assets["sha256"] != asset_hash:
                raise ValueError("Reference assets differ from the captured target")
            directory = self.directory / sample["config"]["scene_id"] / key
            directory.mkdir(parents=True, exist_ok=True)
            allocations = {}

            def run_stream(seed, samples, previous_samples, previous_image, previous_rgb):
                if self.before_segment is not None:
                    self.before_segment()
                timeout = self.timeout if self.before_segment is None else lambda: min(
                    self.timeout, self.before_segment())
                self.notify(stage="reference", target=key, scene=sample["config"]["scene_id"],
                            stream_seed=seed, samples=samples, reference_batch_counts=dict(CLASS_COUNTS),
                            reference_sample_count_unit=PROGRESS_UNIT)
                parent = None if previous_image is None else json.loads(
                    previous_image.with_name("config.json").read_text())
                config = reference_config(sample["config"], sample["frame"], [samples],
                    BATCH_SAMPLES, seed, "POWER_RIS", previous_samples=previous_samples,
                    resume_image=previous_image, class_counts=CLASS_COUNTS,
                    previous_class_samples=None if parent is None else allocation_totals(parent))
                if previous_image:
                    config["reference"]["resume_image_sha256"] = sha(previous_image)
                    config["reference"]["resume_config_sha256"] = sha(previous_image.with_name("config.json"))
                checkpoint = directory / f"seed-{seed}/checkpoint-{samples}"
                attempt_number = 0
                while (checkpoint / f"attempt-{attempt_number}").exists():
                    attempt_number += 1
                attempt = checkpoint / f"attempt-{attempt_number}"
                run_one(config, attempt, self.build, assets, timeout,
                        executable=REFERENCE_EXE, resume_rgb=previous_rgb)
                return pfm_path(attempt / f"frame-{samples // BATCH_SAMPLES:04d}")

            def validate(image, seed, samples, previous_samples, previous_image):
                validate_checkpoint(image, sample, seed, samples, BATCH_SAMPLES, self.build,
                    previous_samples=previous_samples, previous_image=previous_image, sampling="POWER_RIS")
                config = json.loads(image.with_name("config.json").read_text())
                allocations.setdefault(samples, {})[str(seed)] = allocation_totals(config)

            previous_record = self.index["references"].get(key, {})
            # Two passing checkpoints end at the stored sample count; never regress
            # an accepted target when a later condition reuses the same state.
            floor = max(min_samples, previous_record.get("samples", 0) // 2)
            result = run_pose(directory, group, self.checkpoints, BATCH_SAMPLES, REFERENCE_SEEDS,
                .1, run_stream, validate, ImageCache(),
                assessment_factory=partial(ControlledAssessment, rois=rois, min_samples=floor))
            result.update(sample_count_unit=PROGRESS_UNIT,
                allocation_note="Per-class counts describe requested work; absent lights execute none. "
                                "Full-target batch means have equal weight, including across allocation changes.")
            for row in result["checkpoints"]:
                row["class_samples_by_stream"] = allocations[row["samples_per_class_per_stream"]]
            save_json(directory / "convergence.json", result)
            samples = result["samples_per_class_per_stream"]
            streams = [checkpoint_image(directory, seed, samples, BATCH_SAMPLES) for seed in REFERENCE_SEEDS]
            # Formal figure manifests must continue to identify immutable inputs
            # if another condition later needs a more precise shared reference.
            snapshot = directory / f"accepted-{samples}-{sha(directory / 'convergence.json')[:12]}"
            snapshot.mkdir(exist_ok=True)
            for name in ("reference.pfm.gz", "previous-reference.pfm.gz", "convergence.json"):
                destination = snapshot / name
                if destination.exists() and sha(destination) != sha(directory / name):
                    raise ValueError("Accepted reference snapshot was modified")
                if not destination.exists():
                    shutil.copyfile(directory / name, destination)
            record = {"target": sample["target"], "converged": result["converged"],
                "samples": samples, "sample_count_unit": PROGRESS_UNIT,
                "class_samples_by_stream": allocations[samples],
                "image": relative_path(snapshot / "reference.pfm.gz", self.directory),
                "convergence": relative_path(snapshot / "convergence.json", self.directory),
                "previous_image": relative_path(snapshot / "previous-reference.pfm.gz", self.directory),
                "stream_images": [relative_path(path, self.directory) for path in streams]}
            record["image_sha256"] = sha(directory / "reference.pfm.gz")
            record["convergence_sha256"] = sha(directory / "convergence.json")
            record["previous_image_sha256"] = sha(directory / "previous-reference.pfm.gz")
            record["stream_sha256"] = [sha(path) for path in streams]
            self.index["references"][key] = record
            save_json(self.index_path, self.index)
            if not result["converged"]:
                raise RuntimeError(f"Reference precision not reached at {samples} samples: {key}")
            self.notify(stage="reference_accepted", target=key, samples=samples,
                        accepted_references=len(self.index["references"]))
        return {key: self.paths(key) for key in groups}

    def paths(self, key):
        record = self.index["references"][key]
        if not record["converged"]:
            raise ValueError("Reference has not passed precision checks")
        result = {name: self.directory / record[name] for name in ("image", "convergence", "previous_image")}
        for name, path in result.items():
            if sha(path) != record[f"{name}_sha256"]:
                raise ValueError(f"Reference artifact was modified: {path}")
        result["streams"] = [self.directory / path for path in record["stream_images"]]
        if [sha(path) for path in result["streams"]] != record["stream_sha256"]:
            raise ValueError("Reference stream was modified")
        return result
