"""Generate independent conventional direct-lighting references for a saved baseline."""
import argparse
from collections import defaultdict
from pathlib import Path
import json
import math

from rtxdi_common import ROOT, RENDERER, sha
from experiment.artifacts import save_json
from experiment.reference import (suite_captures, reference_config, pfm_path, ImageCache,
                                  CONVERGENCE_METRIC, REFERENCE_SCHEMA_VERSION, validate_lighting)
from experiment.reference_runner import (BUILD_FIELDS, run_pose, validate_checkpoint, validate_resume)
from experiment.runner import output_directory, preflight, run_one, relative_path
from experiment.scenes import ACTIVE_SCENES, validate_assets

EXE = RENDERER / "build/bin/FullSampleReference.exe"


def scene_noise_ratios(default, overrides, scenes):
    """Resolve explicit scene exceptions without changing the global default."""
    ratios = dict.fromkeys(scenes, default)
    seen = set()
    for value in overrides:
        scene, separator, raw = value.partition("=")
        try:
            ratio = float(raw)
        except ValueError as exc:
            raise ValueError("Use --scene-noise-ratio SCENE=RATIO with 0 < RATIO < 1") from exc
        if not separator or not 0 < ratio < 1:
            raise ValueError("Use --scene-noise-ratio SCENE=RATIO with 0 < RATIO < 1")
        if scene not in ratios or scene in seen:
            raise ValueError(f"Unused or duplicate scene noise override: {scene}")
        ratios[scene] = ratio
        seen.add(scene)
    return ratios


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--scene", nargs="+", help="Limit to scene IDs; omission uses active scenes")
    parser.add_argument("--scenario", choices=["static", "motion", "reset"])
    parser.add_argument("--checkpoints", nargs="+", type=int, default=[256, 512, 1024, 2048, 4096],
                        help="Doubling sample counts per light class per independent stream")
    parser.add_argument("--batch-samples", type=int, default=16)
    parser.add_argument("--seeds", nargs=2, type=int, default=[1001, 2001])
    parser.add_argument("--local-sampling", choices=["POWER_RIS", "UNIFORM"], default="POWER_RIS",
                        help="Direct PDF sampling; UNIFORM enables an estimator cross-check; neither uses RIS pools")
    parser.add_argument("--noise-ratio", type=float, default=0.1)
    parser.add_argument("--scene-noise-ratio", action="append", default=[], metavar="SCENE=RATIO",
                        help="Override acceptance for one selected scene; repeat for other scenes. Recorded per reference.")
    parser.add_argument("--output-name")
    parser.add_argument("--resume", type=Path, help="Continue/reassess an existing reference suite")
    parser.add_argument("--reassess-only", action="store_true", help="Reevaluate paired checkpoints without rendering")
    parser.add_argument("--timeout", type=float, default=3600, help="Seconds per pose/seed process")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.seeds[0] == args.seeds[1] or not 0 < args.noise_ratio < 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("Use distinct seeds, a noise ratio between zero and one, and a positive finite timeout")
    if args.resume and args.output_name or args.reassess_only and not args.resume:
        parser.error("--resume replaces --output-name; --reassess-only requires --resume")
    captures = suite_captures(args.baseline.resolve(), args.scene or ACTIVE_SCENES, args.scenario)
    try:
        ratios = scene_noise_ratios(args.noise_ratio, args.scene_noise_ratio,
                                   {c["config"]["scene_id"] for c in captures})
    except ValueError as exc:
        parser.error(str(exc))
    groups = defaultdict(list)
    for capture in captures:
        groups[capture["key"]].append(capture)
    jobs, validated_assets = [], {}
    # Validate every target and its current assets before launching or writing anything.
    for key, group in groups.items():
        sample = group[0]
        source = sample["config"]["scene"]["source"]
        asset_key = (source["root"], source["path"], sample["target"]["asset_sha256"])
        if asset_key not in validated_assets:
            validated_assets[asset_key] = validate_assets({**sample["config"]["scene"], "registry": sample["manifest"]["scene"]["registry"]})
        assets = validated_assets[asset_key]
        if assets["sha256"] != sample["target"]["asset_sha256"]:
            raise ValueError("Current assets differ from the baseline target")
        configs = [reference_config(sample["config"], sample["frame"], args.checkpoints,
                                    args.batch_samples, seed, args.local_sampling) for seed in args.seeds]
        jobs.append((key, group, assets, configs))
    output = args.resume.resolve() if args.resume else output_directory(args.output_name)
    if args.resume and (not output.is_relative_to(ROOT / "runs") or not (output / "reference-index.json").is_file()):
        parser.error("--resume must identify a reference suite inside runs/")
    existing = json.loads((output / "reference-index.json").read_text()) if args.resume else None
    if existing is not None:
        validate_resume(existing, args.seeds, args.checkpoints, args.batch_samples, args.local_sampling)
    print(f"Validated {len(captures)} captures -> {len(jobs)} unique reference views, two streams each", flush=True)
    if args.check:
        return
    build = existing["build"] if args.reassess_only else preflight(jobs[0][3][0]["definition"], EXE)
    if existing and any(existing["build"][k] != build[k] for k in BUILD_FIELDS):
        raise ValueError("Reference renderer/shaders changed; use a new suite")
    if build and any(job[3][0]["definition"]["renderer_commit"] != build["renderer_commit"] for job in jobs):
        raise ValueError("All baseline targets must match the reference renderer revision")
    validate_lighting(captures, build)
    if not args.resume:
        output.mkdir(parents=True, exist_ok=False)
    index = existing or {"schema_version": REFERENCE_SCHEMA_VERSION, "baseline": relative_path(args.baseline.resolve(), output),
                         "seeds": args.seeds, "references": {}}
    index.update(status="running", convergence_metric=CONVERGENCE_METRIC, convergence_regions=["full"], build=build,
                 checkpoint_settings={"checkpoints": args.checkpoints, "batch_samples": args.batch_samples,
                                      "local_sampling": args.local_sampling},
                 script_sha256=sha(Path(__file__)), samples_per_class_per_stream=args.checkpoints[-1])
    index_path = output / "reference-index.json"
    save_json(index_path, index)
    try:
        for key, group, assets, configs in jobs:
            directory = output / group[0]["config"]["scene_id"] / key
            directory.mkdir(parents=True, exist_ok=True)
            sample = group[0]
            cache = ImageCache()
            def run_stream(seed, samples, previous_samples, previous_image, previous_rgb):
                config = reference_config(sample["config"], sample["frame"], [samples],
                                          args.batch_samples, seed, args.local_sampling,
                                          previous_samples=previous_samples, resume_image=previous_image)
                if previous_image:
                    config["reference"]["resume_image_sha256"] = sha(previous_image)
                checkpoint = directory / f"seed-{seed}/checkpoint-{samples}"
                attempt = checkpoint / "attempt-0"
                number = 0
                while attempt.exists():
                    number += 1
                    attempt = checkpoint / f"attempt-{number}"
                run_one(config, attempt, build, assets, args.timeout, executable=EXE,
                        resume_rgb=previous_rgb)
                return pfm_path(attempt / f"frame-{samples // args.batch_samples:04d}")
            def validate(image, seed, samples, previous_samples, previous_image):
                validate_checkpoint(image, sample, seed, samples, args.batch_samples, build,
                                    previous_samples=previous_samples, previous_image=previous_image,
                                    sampling=args.local_sampling)
            result = run_pose(directory, group, args.checkpoints, args.batch_samples, args.seeds,
                              ratios[sample["config"]["scene_id"]], None if args.reassess_only else run_stream, validate, cache)
            index["references"][key] = {"target": group[0]["target"],
                "image": relative_path(directory / "reference.pfm.gz", output),
                "image_sha256": sha(directory / "reference.pfm.gz"),
                "convergence": relative_path(directory / "convergence.json", output),
                "convergence_sha256": sha(directory / "convergence.json"), "converged": result["converged"],
                "convergence_metric": CONVERGENCE_METRIC,
                "samples_per_class_per_stream": result["samples_per_class_per_stream"]}
            save_json(index_path, index)
            print(f"{group[0]['config']['scene_id']} {key}: {'converged' if result['converged'] else 'NOT converged; increase budget'}", flush=True)
        index["status"] = "completed"
    except BaseException:
        index["status"] = "incomplete"
        raise
    finally:
        save_json(index_path, index)
    print(f"References: {output}")


if __name__ == "__main__":
    main()
