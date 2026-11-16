"""Run the six-view spatial/CGNS comparison, or a selected-view temporal contrast.

The capture path is the project's point-reservoir temporal adaptation,
not an exact reproduction of the authors' area-reservoir splatting method.
Each capture is 1 spp, never an accumulated image. Existing attempts are never
overwritten. Explicit --retry-failed creates a new numbered attempt.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
from copy import deepcopy
from . import spatial_capture as capture, cgns_pt_six_view_smoke as six
from . import cgns_pt_smoke as smoke, reference_runner, reference_extension_batch
from . import run, capture_lifecycle, spatial_inputs
from . import build, spatial_experiment_config as experiment_config
from . import reference_catalog as reference_sets
from .process_utils import check_renderer_idle, exclusive_operation
from scripts.analysis import falcor_comparison as analysis
from scripts.analysis.relative_paths import relative_to_document

ROOT = Path(__file__).resolve().parents[2]


def _analysis_file_record(path, digest, manifest):
    return {"path": relative_to_document(path, Path(manifest).parent), "sha256": digest}


RUNTIME = dict(spatial_inputs.RUNTIME)


def _attempt_path(attempt, output):
    return Path(attempt).resolve().relative_to(Path(output).resolve()).as_posix()


def validate_artifacts(directory, artifacts, schedule, width, height, *, temporal_reuse=True, seed_offset=0):
    return spatial_inputs.validate_artifacts(directory, artifacts, schedule, width, height,
                                            temporal_reuse=temporal_reuse, seed_offset=seed_offset)


choose_attempt = capture_lifecycle.choose_attempt


def validate_code_inputs(meta, render_script, driver, root, dependency_names):
    root = Path(root).resolve(strict=True)
    render_script = Path(render_script)
    driver = Path(driver)
    if meta.get("driver_sha256") != run.sha(driver) or meta.get("render_script_sha256") != run.sha(
        render_script
    ):
        raise ValueError("Driver or render script hash mismatch")
    dependencies = meta.get("dependency_sha256")
    if not isinstance(dependencies, dict) or set(dependencies) != set(dependency_names):
        raise ValueError("Dependency set differs")
    for name, digest in dependencies.items():
        path = (root / name).resolve(strict=True)
        if not path.is_relative_to(root) or run.sha(path) != digest:
            raise ValueError("Driver dependency changed: " + name)


def validate_pair(a, ma, b, mb, *, temporal_reuse=True, compare_method='cgns'):
    a = Path(a)
    b = Path(b)
    if (compare_method not in ('cgns', 'pdf-similarity')
            or ma.get("requested_method") != "baseline"
            or mb.get("requested_method") != compare_method):
        raise ValueError("Pair method mismatch")
    fields = (
        "scene_id",
        "view_id",
        "scene_config_sha256",
        "reference_baseline_sha256",
        "scene_manifest_sha256",
        "reference_catalog_sha256",
        "asset_sha256",
        "source_sha256",
        "resolution",
        "warmup_frames",
        "capture_frames",
        "spp_per_frame",
        "image_accumulation",
        "temporal_reuse",
        "clock_policy",
        "seed_policy",
        "requested_graph_options",
        "experiment_config_path",
        "experiment_config_sha256",
        "experiment_config",
        "build_commit",
        "gpu_driver",
    )
    if any((ma.get(k) != mb.get(k) for k in fields)):
        raise ValueError("Pair configuration differs")
    if (a / "resolved.py").read_bytes() != (b / "resolved.py").read_bytes():
        raise ValueError("Pair resolved graph differs")
    for name in ("resolved-camera.json", "scene-state.json"):
        if json.loads((a / name).read_text(encoding="utf8")) != json.loads(
            (b / name).read_text(encoding="utf8")
        ):
            raise ValueError("Pair state differs: " + name)
    aa = a / "scene-audit.json"
    bb = b / "scene-audit.json"
    if aa.exists() != bb.exists() or (
        aa.exists()
        and json.loads(aa.read_text(encoding="utf8")) != json.loads(bb.read_text(encoding="utf8"))
    ):
        raise ValueError("Pair scene audits differ")
    if [_frame_key(x, temporal_reuse) for x in ma["artifacts"]] != [
        _frame_key(x, temporal_reuse) for x in mb["artifacts"]
    ]:
        raise ValueError("Pair capture schedule differs")


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


_atomic = capture_lifecycle.atomic_json


def _dependency_names(method='baseline'):
    return {path.relative_to(ROOT).as_posix() for path in capture.dependency_files(method)}


def _campaign_code_identity(compare_method):
    identity = _code_identity()
    if compare_method == 'pdf-similarity':
        from . import pdf_pt_runtime, pdf_pt_overlay, pdf_pt_shader
        files = [Path(module.__file__).resolve()
                 for module in (pdf_pt_runtime, pdf_pt_overlay, pdf_pt_shader)]
        files.extend(pdf_pt_shader.source_files())
        identity.update({path.relative_to(ROOT).as_posix(): run.sha(path) for path in files})
    return identity


def _code_identity():
    from . import cgns_single_runtime, cgns_single_overlay, cgns_shader_overlay, cgns_runtime

    modules = [
        capture,
        reference_sets,
        *capture.dependencies(),
        cgns_single_runtime,
        cgns_single_overlay,
        cgns_shader_overlay,
        cgns_runtime,
        run,
        build,
        analysis,
        experiment_config,
        spatial_inputs,
    ]
    files = [
        Path(__file__).resolve(),
        *(Path(m.__file__).resolve() for m in modules),
        ROOT / "scripts/falcor/cgns_temporal_campaign.py",
        ROOT / "scripts/falcor/cgns_paper_campaign.py",
        ROOT / "scripts/falcor/cgns_point_selector.slang",
        ROOT / "scripts/falcor/cgns_single_selector.slang",
        ROOT / "scripts/falcor/cgns_single_wrs.h",
        ROOT / "src/image_io/exr.py",
        ROOT / "src/metrics/error_metrics.py",
        ROOT / "scripts/falcor/reference_extension_gallery.py",
    ]
    from . import cgns_cached_runtime
    files.extend(cgns_cached_runtime.implementation_files())
    return {str(p.relative_to(ROOT)).replace("\\", "/"): run.sha(p) for p in sorted(set(files))}


def _reference_catalog(experiment=None, *, require_images=False, image_views=None):
    return spatial_inputs.reference_catalog(experiment, require_images=require_images,
                                           image_views=image_views, root=ROOT)


def _prepare_runtimes(experiment, *, compare_method='cgns'):
    return spatial_inputs.prepare_runtimes(experiment, compare_method=compare_method, runtime_paths=RUNTIME)


def _runtime_snapshots(experiment=None, runtime_paths=None):
    return spatial_inputs.runtime_snapshots(experiment, RUNTIME if runtime_paths is None else runtime_paths)


def _validate_job(
    path,
    key,
    entry,
    config,
    runtime,
    method,
    runtime_snapshot,
    build_commit,
    *,
    experiment=None,
    experiment_path=None,
    experiment_sha256=None,
    temporal_reuse=True,
):
    experiment = (
        experiment_config.load_config()
        if experiment is None
        else experiment_config.validate_config(experiment)
    )
    budget = experiment["render"]
    width, height = (budget["width"], budget["height"])
    warmup, count = (budget["warmup_frames"], budget["capture_count"])
    path = Path(path).resolve(strict=True)
    meta = _json(path / "manifest.json")
    schedule = capture.capture_schedule(warmup, count)
    portable = meta.get("path_format") == "workspace-relative-v1"
    if meta.get("path_format") not in (None, "workspace-relative-v1"):
        raise ValueError("Unknown capture path format")
    expected = {
        "status": "completed",
        "exit_code": 0,
        "kind": capture.capture_kind(method, temporal_reuse),
        "requested_method": method,
        "scene_id": key[0],
        "view_id": key[1],
        "scene_config_sha256": entry["config_sha256"],
        "reference_baseline_sha256": run.sha(six.scene_manifest_path()),
        "scene_manifest_sha256": run.sha(six.scene_manifest_path()),
        "reference_catalog_sha256": run.sha(six.reference_catalog_path(experiment)),
        "asset_sha256": entry["asset_sha256"],
        "source_sha256": entry["source_sha256"],
        "resolution": [width, height],
        "warmup_frames": warmup,
        "capture_frames": schedule,
        "seed_policy": seed_policy(temporal_reuse),
        "spp_per_frame": 1,
        "image_accumulation": False,
        "temporal_reuse": temporal_reuse,
        "clock_policy": {"paused": True, "framerate": 0, "time": 0},
        "requested_graph_options": capture.graph_options(
            method, experiment, temporal_reuse=temporal_reuse
        ),
        "adapted": entry["adapted"],
        "runtime": str(runtime.resolve()),
        "runtime_verification": runtime_snapshot,
        "build_commit": build_commit,
    }
    if experiment_path is not None:
        expected.update(
            {
                "experiment_config_path": str(Path(experiment_path).resolve()),
                "experiment_config_sha256": experiment_sha256,
                "experiment_config": experiment,
                "cgns_shader_parameters": (
                    experiment["methods"]["cgns"]["shader"] if method == "cgns" else None
                ),
            }
        )
    if method == 'pdf-similarity':
        expected['pdf_shader_parameters'] = experiment['methods'][method]['shader']
        expected['pdf_profile'] = 'normal'
        if meta.get('seed_offset', 0) != 0:
            raise ValueError('Campaign requires the default seed offset')
    if portable:
        if "experiment_config_path" in expected:
            expected["experiment_config_path"] = relative_to_document(experiment_path, ROOT)
        expected["runtime"] = relative_to_document(runtime, ROOT)
    for k, v in expected.items():
        if meta.get(k) != v:
            raise ValueError("Job metadata mismatch: " + k + " " + str(path))
    validate_code_inputs(
        meta, path / "render.py", Path(capture.__file__), ROOT, _dependency_names(method)
    )
    scene = Path(config["scene_source"])
    scene = (scene if scene.is_absolute() else ROOT / scene).resolve(strict=True)
    intended = capture.render_script(
        scene,
        config["camera"],
        path,
        warmup,
        count,
        method,
        adapted=entry["adapted"],
        experiment=experiment,
        portable=portable,
        temporal_reuse=temporal_reuse,
    )
    if (path / "render.py").read_bytes() != intended.encode("utf8"):
        raise ValueError("Rendered script differs from frozen plan")
    shader = runtime / "shaders/ReSTIRPathTracing/SpatialResampling.cs.slang"
    if meta.get("runtime_spatial_shader_sha256") != run.sha(shader):
        raise ValueError("Spatial shader differs")
    smoke.validate_resolved_graph(
        (path / "resolved.py").read_text(encoding="utf8"),
        capture.graph_options(method, experiment, temporal_reuse=temporal_reuse),
    )
    smoke.validate_resolved_graph(
        (path / "resolved.py").read_text(encoding="utf8"),
        {"samplePattern": "Center", "sampleCount": 1, "useAlphaTest": True, "useDOF": False},
        "VBufferRT",
    )
    camera = _json(path / "resolved-camera.json")
    reference_runner.validate_camera_records(config["camera"], camera, warmup + count)
    if "near_plane" in config["camera"] and any(
        (
            not math.isclose(
                float(camera[k]["nearPlane"]),
                float(config["camera"]["near_plane"]),
                rel_tol=1e-06,
                abs_tol=1e-06,
            )
            for k in ("initial", "first_frame", "last_frame")
        )
    ):
        raise ValueError("Near plane differs")
    actual_state = _json(path / "scene-state.json")
    actual_audit = _json(path / "scene-audit.json") if entry["adapted"] else None
    six.validate_current_scene_state(config, actual_state, actual_audit)
    frames = validate_artifacts(
        path, meta.get("artifacts"), schedule, width, height, temporal_reuse=temporal_reuse
    )
    meta["artifacts"] = frames
    files = [
        "manifest.json",
        "render.py",
        "resolved.py",
        "resolved-camera.json",
        "scene-state.json",
    ]
    if entry["adapted"]:
        files.append("scene-audit.json")
    return (
        meta,
        {
            "schema_version": 1,
            "files": {name: run.sha(path / name) for name in files},
            "artifacts": frames,
        },
    )


def _identity(
    catalog,
    runtimes,
    build_commit,
    *,
    experiment=None,
    experiment_path=None,
    experiment_sha256=None,
    runtime_paths=None,
    temporal_reuse=True,
    temporal_contrast=False,
    compare_method='cgns',
):
    experiment = (
        experiment_config.load_config()
        if experiment is None
        else experiment_config.validate_config(experiment)
    )
    budget = experiment["render"]
    runtime_paths = RUNTIME if runtime_paths is None else runtime_paths
    records = []
    for key in sorted(catalog):
        v = catalog[key]
        records.append(
            {
                "scene_id": key[0],
                "view_id": key[1],
                "config_path": relative_to_document(v["config_path"], ROOT),
                "config_sha256": v["entry"]["config_sha256"],
                "adapted": v["entry"]["adapted"],
                "reference": _analysis_file_record(
                    v["reference"]["path"], v["reference"]["sha256"], ROOT / "identity.json"
                ),
            }
        )
    return {
        "kind": (
            "falcor_baseline_temporal_contrast"
            if temporal_contrast
            else (
                ('falcor_pdf_similarity_temporal_single_frame' if compare_method == 'pdf-similarity'
                 else "falcor_cgns_temporal_fast_single_frame")
                if temporal_reuse
                else ('falcor_pdf_similarity_spatial_single_frame' if compare_method == 'pdf-similarity'
                      else "falcor_cgns_paper_fast_single_frame")
            )
        ),
        "schema_version": 1,
        "path_format": "workspace-relative-v1",
        "resolution": [budget["width"], budget["height"]],
        "warmup_frames": budget["warmup_frames"],
        "capture_frames": capture.capture_schedule(
            budget["warmup_frames"], budget["capture_count"]
        ),
        "spp_per_frame": 1,
        "temporal_reuse": None if temporal_contrast else temporal_reuse,
        "image_accumulation": False,
        "clock_policy": {"paused": True, "framerate": 0, "time": 0},
        "comparison_kind": "baseline-temporal-on-off" if temporal_contrast else 'spatial-' + compare_method,
        "algorithm": (
            "ordinary spatial reuse, temporal on/off"
            if temporal_contrast
            else ('PDF similarity: first-hop contribution moments from initial PT candidates; vMF similarity '
                  'scales the proposed spatial neighbor\'s effective M.'
                  if compare_method == 'pdf-similarity'
                  else "independent CGNS adaptation; point reservoirs, unpaired")
        ),
        "experiment_config": {
            "path": (
                relative_to_document(experiment_path, ROOT) if experiment_path is not None else None
            ),
            "sha256": experiment_sha256,
            "settings": experiment,
        },
        "limitations": "Point reservoirs and no reservoir splatting; per-frame SMAPE, no RGB accumulation. Not exact author reproduction.",
        "reference_catalog_sha256": run.sha(six.reference_catalog_path(experiment)),
        "scene_manifest_sha256": run.sha(six.scene_manifest_path()),
        "views": records,
        "build_commit": build_commit,
        "code_sha256": _campaign_code_identity(compare_method),
        "runtimes": {
            method
            + ("-gltf" if adapted else "-reference"): {
                "path": relative_to_document(runtime_paths[method, adapted], ROOT),
                "verification": value,
            }
            for (method, adapted), value in runtimes.items()
        },
    }


def _identity_hash(identity):
    return hashlib.sha256(
        json.dumps(
            identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf8")
    ).hexdigest()


def _bind_receipt(path, value):
    path = Path(path)
    if path.exists():
        if _json(path) != value:
            raise ValueError("Saved job validation receipt differs; refusing reuse")
    else:
        with path.open("x", encoding="utf8", newline="\n") as f:
            json.dump(value, f, indent=2, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
    return run.sha(path)


def _next_analysis(output, retry_failed):
    folder = output / "analysis"
    folder.mkdir(exist_ok=True)
    used = set()
    for p in folder.iterdir():
        if p.name.startswith("attempt-"):
            if not p.is_dir() or not re.fullmatch("attempt-\\d{3}", p.name):
                raise ValueError("Unexpected analysis attempt entry")
            used.add(int(p.name[-3:]))
        elif p.name.startswith("input-"):
            if not p.is_file() or not re.fullmatch("input-\\d{3}\\.json", p.name):
                raise ValueError("Unexpected analysis input entry")
            used.add(int(p.stem[-3:]))
    if used and (not retry_failed):
        raise ValueError(
            "Prior incomplete analysis retained; use --retry-failed to create a new report"
        )
    number = max(used, default=0) + 1
    if number > 999:
        raise ValueError("Analysis attempt limit reached")
    return (folder / f"input-{number:03d}.json", folder / f"attempt-{number:03d}")


def _verify_report(output, info):
    if not isinstance(info, dict) or not isinstance(info.get("files"), dict):
        raise ValueError("Completed report receipt missing")
    base = (output / info["directory"]).resolve(strict=True)
    if not base.is_relative_to(output) or not base.is_dir():
        raise ValueError("Report escapes output directory")
    actual = {p.relative_to(base).as_posix(): run.sha(p) for p in base.rglob("*") if p.is_file()}
    input_path = (output / info["analysis_input"]).resolve(strict=True)
    if (
        not input_path.is_relative_to(output)
        or actual != info["files"]
        or run.sha(input_path) != info["analysis_input_sha256"]
    ):
        raise ValueError("Completed report or input changed")
    return base


def _reference_catalog_identity(catalog):
    return {
        key: {
            "config_sha256": item["entry"]["config_sha256"],
            "reference": item["reference"],
            "asset_sha256": item["entry"]["asset_sha256"],
            "source_sha256": item["entry"].get("source_sha256"),
        }
        for key, item in catalog.items()
    }


def seed_policy(temporal_reuse):
    return (
        "path fixedSeed=frame-1; ReSTIR reuse seed=max(0,frame-2); first temporal pass skipped"
        if temporal_reuse
        else "fixedSeed=frame-1; temporal reuse disabled"
    )


def _frame_key(record, temporal_reuse):
    return (
        (record["frame"], record["seed"], record["reuse_seed"])
        if temporal_reuse
        else (record["frame"], record["seed"])
    )


def _contrast_graph(source, temporal_reuse):
    """Compare serialized graphs allowing exactly the intended temporal toggle."""
    import ast

    tree = ast.parse(source)
    found = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for index, key in enumerate(node.keys):
                if isinstance(key, ast.Constant) and key.value == "useTemporalResampling":
                    value = node.values[index]
                    if (
                        not isinstance(value, ast.Constant)
                        or type(value.value) is not bool
                        or value.value != temporal_reuse
                    ):
                        raise ValueError("Contrast resolved temporal option differs")
                    node.values[index] = ast.Constant(False)
                    found += 1
    if found != 1:
        raise ValueError("Contrast must contain exactly one resolved temporal option")
    return ast.dump(tree, include_attributes=False)


def validate_temporal_contrast(on, ma, off, mb):
    """Bind both ordinary-spatial jobs to identical conditions and frame seeds."""
    if (ma.get("requested_method"), mb.get("requested_method")) != ("baseline", "baseline"):
        raise ValueError("Temporal contrast requires ordinary spatial reuse")
    if ma.get("temporal_reuse") is not True or mb.get("temporal_reuse") is not False:
        raise ValueError("Temporal contrast mode mismatch")
    fields = (
        "scene_id",
        "view_id",
        "scene_config_sha256",
        "reference_baseline_sha256",
        "scene_manifest_sha256",
        "reference_catalog_sha256",
        "asset_sha256",
        "source_sha256",
        "resolution",
        "warmup_frames",
        "capture_frames",
        "spp_per_frame",
        "image_accumulation",
        "clock_policy",
        "experiment_config_path",
        "experiment_config_sha256",
        "experiment_config",
        "build_commit",
        "gpu_driver",
        "runtime",
        "runtime_verification",
        "runtime_spatial_shader_sha256",
        "runtime_executable_sha256",
        "runtime_falcor_dll_sha256",
    )
    if any((ma.get(key) != mb.get(key) for key in fields)):
        raise ValueError("Temporal contrast conditions differ")
    if ma.get("clock_policy") != {"paused": True, "framerate": 0, "time": 0}:
        raise ValueError("Temporal contrast requires a static clock")
    graphs = []
    for meta, expected in ((ma, True), (mb, False)):
        if meta.get("seed_policy") != seed_policy(expected):
            raise ValueError("Temporal contrast seed policy differs")
        graph = deepcopy(meta["requested_graph_options"])
        options = graph["reSTIRPathTracingOptions"]
        if (
            options.pop("useTemporalResampling", None) is not expected
            or options.get("useSpatialResampling") is not True
        ):
            raise ValueError("Temporal contrast graph mode differs")
        graphs.append(graph)
        for artifact in meta["artifacts"]:
            if artifact["seed"] != artifact["frame"] - 1 or (
                expected and artifact.get("reuse_seed") != max(0, artifact["frame"] - 2)
            ):
                raise ValueError("Temporal contrast seed differs")
    if graphs[0] != graphs[1]:
        raise ValueError("Temporal contrast graph conditions differ")
    on, off = (Path(on), Path(off))
    if _contrast_graph((on / "resolved.py").read_text(encoding="utf8"), True) != _contrast_graph(
        (off / "resolved.py").read_text(encoding="utf8"), False
    ):
        raise ValueError("Temporal contrast resolved graphs differ")
    for name in ("resolved-camera.json", "scene-state.json", "scene-audit.json"):
        left, right = (on / name, off / name)
        if left.exists() != right.exists() or (left.exists() and _json(left) != _json(right)):
            raise ValueError("Temporal contrast state differs: " + name)
    if [_frame_key(x, False) for x in ma["artifacts"]] != [
        _frame_key(x, False) for x in mb["artifacts"]
    ]:
        raise ValueError("Temporal contrast capture schedule differs")


def _select_catalog(catalog, temporal_contrast, view):
    if type(temporal_contrast) is not bool:
        raise ValueError("Invalid temporal contrast flag")
    if not temporal_contrast:
        if view is not None:
            raise ValueError("--view is only supported with --temporal-contrast")
        return catalog
    if (
        not isinstance(view, str)
        or len(view.split("/")) != 2
        or any((not part for part in view.split("/")))
    ):
        raise ValueError("Temporal contrast requires exactly one --view SCENE/VIEW")
    key = tuple(view.split("/"))
    if key not in catalog:
        raise ValueError("Unknown contrast view: " + view)
    return {key: catalog[key]}


def _job_specs(temporal_reuse, temporal_contrast, *, compare_method='cgns'):
    if compare_method not in ('cgns', 'pdf-similarity'):
        raise ValueError('Unknown comparison method')
    if temporal_contrast and compare_method != 'cgns':
        raise ValueError('Temporal contrast compares ordinary spatial reuse only')
    return (
        (("temporal-on", "baseline", True), ("temporal-off", "baseline", False))
        if temporal_contrast
        else (("baseline", "baseline", temporal_reuse), (compare_method, compare_method, temporal_reuse))
    )


def run_campaign(
    output,
    *,
    retry_failed=False,
    experiment_path=None,
    temporal_reuse=True,
    temporal_contrast=False,
    view=None,
    compare_method='cgns',
):
    capture_lifecycle.check_shader_environment()
    if type(retry_failed) is not bool or type(temporal_reuse) is not bool:
        raise ValueError("Invalid campaign flag")
    experiment_path = Path(experiment_path or experiment_config.DEFAULT_CONFIG).resolve(strict=True)
    experiment, experiment_sha256 = experiment_config.load_config_snapshot(experiment_path)
    _job_specs(temporal_reuse, temporal_contrast, compare_method=compare_method)
    capture.graph_options(compare_method, experiment, temporal_reuse=temporal_reuse)
    budget = experiment["render"]
    capture.validate_budget(
        budget["width"],
        budget["height"],
        budget["warmup_frames"],
        budget["capture_count"],
        experiment=experiment,
    )
    catalog = _select_catalog(_reference_catalog(experiment), temporal_contrast, view)
    with exclusive_operation(ROOT / "build/falcor/.spatial-campaign.lock"):
        if temporal_contrast:
            adapted = next(iter(catalog.values()))["entry"]["adapted"]
            runtime_paths = {("baseline", adapted): RUNTIME["baseline", adapted]}
        else:
            runtime_paths = (_prepare_runtimes(experiment) if compare_method == 'cgns' else
                             _prepare_runtimes(experiment, compare_method=compare_method))
        return _run_campaign(
            output,
            retry_failed=retry_failed,
            experiment=experiment,
            experiment_path=experiment_path,
            experiment_sha256=experiment_sha256,
            runtime_paths=runtime_paths,
            catalog=catalog,
            temporal_reuse=temporal_reuse,
            temporal_contrast=temporal_contrast,
            view=view,
            compare_method=compare_method,
        )


def _run_campaign(
    output,
    *,
    retry_failed=False,
    experiment,
    experiment_path,
    experiment_sha256,
    runtime_paths,
    catalog=None,
    temporal_reuse=True,
    temporal_contrast=False,
    view=None,
    compare_method='cgns',
):
    _job_specs(temporal_reuse, temporal_contrast, compare_method=compare_method)
    if run.sha(experiment_path) != experiment_sha256:
        raise ValueError("Experiment configuration changed before campaign")
    budget = experiment["render"]
    width, height = (budget["width"], budget["height"])
    warmup, count = (budget["warmup_frames"], budget["capture_count"])
    output = Path(output).resolve()
    if output.exists() and (not (output / "campaign.json").is_file()):
        raise ValueError("Existing output has no campaign receipt; refusing reuse")
    with exclusive_operation(ROOT / "build/falcor/.operation.lock"):
        check_renderer_idle()
        build_record = build.verify_build()
        catalog = (
            _select_catalog(_reference_catalog(experiment), temporal_contrast, view)
            if catalog is None
            else catalog
        )
        runtimes = _runtime_snapshots(experiment, runtime_paths)
        identity = _identity(
            catalog,
            runtimes,
            build_record["commit"],
            experiment=experiment,
            experiment_path=experiment_path,
            experiment_sha256=experiment_sha256,
            runtime_paths=runtime_paths,
            temporal_reuse=temporal_reuse,
            temporal_contrast=temporal_contrast,
            compare_method=compare_method,
        )
        fingerprint = _identity_hash(identity)
    if output.exists():
        campaign = _json(output / "campaign.json")
        if campaign.get("job_path_base") not in (None, "campaign"):
            raise ValueError("Unknown campaign job path base")
        if campaign.get("identity_sha256") != fingerprint or campaign.get("identity") != identity:
            raise ValueError(
                "Campaign settings, source code, assets, runtime or references differ; refusing reuse"
            )
    else:
        output.mkdir(parents=True, exist_ok=False)
        campaign = {
            "schema_version": 1,
            "status": "initialized",
            "identity": identity,
            "identity_sha256": fingerprint,
            "job_path_base": "campaign",
            "jobs": {},
        }
        _atomic(output / "campaign.json", campaign)
    previous_status = campaign.get("status")
    campaign["status"] = "running"
    campaign.pop("error", None)
    _atomic(output / "campaign.json", campaign)
    try:
        done = {}
        specs = _job_specs(temporal_reuse, temporal_contrast, compare_method=compare_method)
        for key in sorted(catalog):
            item = catalog[key]
            entry, config = (item["entry"], item["config"])
            done[key] = {}
            reference_extension_batch.recheck_view(entry, config)
            for label, method, reuse_temporal in specs:
                runtime = runtime_paths[method, entry["adapted"]].resolve(strict=True)
                job_key = "/".join((*key, label))
                attempt, reuse = choose_attempt(
                    output / "jobs" / key[0] / key[1] / label, retry_failed=retry_failed
                )
                stored_attempt = _attempt_path(attempt, output)
                previous = campaign["jobs"].get(job_key)
                if previous and previous.get("attempt") not in (str(attempt), stored_attempt):
                    if (
                        previous.get("receipt_sha256")
                        or previous.get("status") == "completed"
                        or (not retry_failed)
                    ):
                        raise ValueError("Recorded job attempt differs")
                if not reuse:
                    campaign["jobs"][job_key] = {
                        "attempt": stored_attempt,
                        "status": "running",
                        "method": method,
                        "temporal_reuse": reuse_temporal,
                    }
                    _atomic(output / "campaign.json", campaign)
                    print(f"Rendering {key[0]}/{key[1]} {label}: {attempt.name}", flush=True)
                    try:
                        capture.launch(
                            item["config_path"],
                            attempt,
                            runtime,
                            method=method,
                            width=width,
                            height=height,
                            warmup=warmup,
                            count=count,
                            experiment=experiment,
                            experiment_path=experiment_path,
                            experiment_sha256=experiment_sha256,
                            temporal_reuse=reuse_temporal,
                        )
                    except BaseException as exc:
                        capture_lifecycle.preserve_failure(attempt, exc, receipt_name="campaign-failure.json")
                        raise
                else:
                    print(f"Rechecking {key[0]}/{key[1]} {label}: {attempt.name}", flush=True)
                if (
                    _campaign_code_identity(compare_method) != identity["code_sha256"]
                    or run.sha(experiment_path) != experiment_sha256
                ):
                    raise ValueError("Campaign code or configuration changed during render")
                meta, receipt = _validate_job(
                    attempt,
                    key,
                    entry,
                    config,
                    runtime,
                    method,
                    runtimes[method, entry["adapted"]],
                    build_record["commit"],
                    experiment=experiment,
                    experiment_path=experiment_path,
                    experiment_sha256=experiment_sha256,
                    temporal_reuse=reuse_temporal,
                )
                receipt_sha = _bind_receipt(attempt / "campaign-validation.json", receipt)
                if (
                    previous
                    and previous.get("receipt_sha256")
                    and previous["receipt_sha256"] != receipt_sha
                ):
                    raise ValueError("Recorded job validation receipt changed")
                campaign["jobs"][job_key] = {
                    "attempt": stored_attempt,
                    "receipt_sha256": receipt_sha,
                    "status": "completed",
                    "method": method,
                    "temporal_reuse": reuse_temporal,
                }
                _atomic(output / "campaign.json", campaign)
                done[key][label] = (attempt, meta)
            if temporal_contrast:
                validate_temporal_contrast(*done[key]["temporal-on"], *done[key]["temporal-off"])
            else:
                validate_pair(
                    *done[key]['baseline'], *done[key][compare_method],
                    temporal_reuse=temporal_reuse, compare_method=compare_method,
                )
        with exclusive_operation(ROOT / "build/falcor/.operation.lock"):
            check_renderer_idle()
            if (
                _runtime_snapshots(experiment, runtime_paths) != runtimes
                or _campaign_code_identity(compare_method) != identity["code_sha256"]
                or run.sha(experiment_path) != experiment_sha256
            ):
                raise ValueError("Runtime or code changed before analysis")
            if (
                run.sha(six.reference_catalog_path(experiment))
                != identity["reference_catalog_sha256"]
                or run.sha(six.scene_manifest_path()) != identity["scene_manifest_sha256"]
            ):
                raise ValueError("Scene or reference manifest changed before analysis")
            fresh = _select_catalog(
                _reference_catalog(experiment, require_images=True, image_views=set(catalog)),
                temporal_contrast,
                view,
            )
            if _reference_catalog_identity(catalog) != _reference_catalog_identity(fresh):
                raise ValueError("Reference or frozen inputs changed before analysis")
            for item in catalog.values():
                reference_extension_batch.recheck_view(item["entry"], item["config"])
        if previous_status == "completed":
            report = _verify_report(output, campaign.get("report"))
            campaign["status"] = "completed"
            _atomic(output / "campaign.json", campaign)
            return report
        input_path, report = _next_analysis(output, retry_failed)
        payload = _analysis_payload(
            catalog,
            done,
            input_path,
            experiment_sha256,
            warmup,
            count,
            temporal_reuse,
            temporal_contrast,
            compare_method=compare_method,
        )
        with input_path.open("x", encoding="utf8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, allow_nan=False)
            handle.write("\n")
        report = analysis.analyze(
            input_path, report, temporal_required=temporal_reuse, contrast=temporal_contrast
        )
        files = {
            p.relative_to(report).as_posix(): run.sha(p) for p in report.rglob("*") if p.is_file()
        }
        campaign["report"] = {
            "directory": report.relative_to(output).as_posix(),
            "analysis_input": input_path.relative_to(output).as_posix(),
            "analysis_input_sha256": run.sha(input_path),
            "files": files,
        }
        campaign["status"] = "completed"
        _atomic(output / "campaign.json", campaign)
        return report
    except BaseException as exc:
        campaign["status"] = "failed"
        campaign["error"] = str(exc)
        for job in campaign["jobs"].values():
            if job.get("status") == "running":
                job["status"] = "failed"
                job["error"] = str(exc)
        _atomic(output / "campaign.json", campaign)
        raise


def _analysis_payload(
    catalog, done, input_path, experiment_sha256, warmup, count, temporal_reuse, temporal_contrast,
    *, compare_method='cgns',
):
    labels = ("temporal-on", "temporal-off") if temporal_contrast else ('baseline', compare_method)
    pair_fields = ("temporal_on", "temporal_off") if temporal_contrast else labels
    views = []
    for key in sorted(catalog):
        a, ma = done[key][labels[0]]
        b, mb = done[key][labels[1]]
        by_a = {x["frame"]: x for x in ma["artifacts"]}
        by_b = {x["frame"]: x for x in mb["artifacts"]}
        pairs = [
            {
                "id": frame,
                pair_fields[0]: _analysis_file_record(
                    a / by_a[frame]["hdr"], by_a[frame]["sha256"], input_path
                ),
                pair_fields[1]: _analysis_file_record(
                    b / by_b[frame]["hdr"], by_b[frame]["sha256"], input_path
                ),
            }
            for frame in capture.capture_schedule(warmup, count)
        ]
        ref = catalog[key]["reference"]
        views.append(
            {
                "scene_id": key[0],
                "view_id": key[1],
                "reference": _analysis_file_record(ref["path"], ref["sha256"], input_path),
                "pairs": pairs,
            }
        )
    return {
        "settings": {
            "comparison_kind": "baseline-temporal-on-off" if temporal_contrast else 'spatial-' + compare_method,
            "temporal_reuse": None if temporal_contrast else temporal_reuse,
            "spp_per_frame": 1,
            "image_accumulation": False,
            "warmup_frames": warmup,
            "capture_frames": capture.capture_schedule(warmup, count),
            "experiment_config_sha256": experiment_sha256,
            "provenance": (
                "Ordinary spatial reuse; selected-view temporal on/off contrast"
                if temporal_contrast
                else ('PDF similarity: first-hop contribution moments from initial PT candidates; vMF similarity '
                      'scales the proposed spatial neighbor\'s effective M.'
                      if compare_method == 'pdf-similarity'
                      else "CGNS Fast-inspired point-reservoir adaptation; not author area/splatting")
            ),
        },
        "views": views,
    }


def main(argv=None, *, temporal_reuse=True, legacy=False):
    description = (
        (
            "Run the six-view temporal-"
            + ("on" if temporal_reuse else "off")
            + " spatial/CGNS comparison."
        )
        if legacy
        else __doc__
    )
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--experiment-config", type=Path, default=experiment_config.DEFAULT_CONFIG)
    parser.add_argument('--compare-method', choices=('cgns', 'pdf-similarity'), default='cgns',
                        help='Pair ordinary spatial reuse with this method; default: cgns')
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Preserve incomplete attempts and create new numbered attempts",
    )
    if not legacy:
        parser.add_argument(
            "--temporal-contrast",
            action="store_true",
            help="Compare ordinary spatial reuse with temporal on/off for one explicitly selected view",
        )
        parser.add_argument("--view", help="Exactly one SCENE/VIEW; requires --temporal-contrast")
    args = parser.parse_args(argv)
    contrast = getattr(args, "temporal_contrast", False)
    view = getattr(args, "view", None)
    if contrast != (view is not None):
        parser.error(
            "--temporal-contrast and exactly one --view SCENE/VIEW must be supplied together"
        )
    if contrast and args.compare_method != 'cgns':
        parser.error('--temporal-contrast uses ordinary spatial reuse and cannot select a comparison method')
    print(
        run_campaign(
            args.output,
            retry_failed=args.retry_failed,
            experiment_path=args.experiment_config,
            temporal_reuse=temporal_reuse,
            temporal_contrast=contrast,
            view=view,
            compare_method=args.compare_method,
        )
    )


if __name__ == "__main__":
    main()
