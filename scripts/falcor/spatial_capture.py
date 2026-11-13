"""Capture fixed-view Falcor ReSTIR PT frames with an explicit reuse policy."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess

from scripts.analysis import relative_paths
from . import (
    adapted_reference_runner,
    build,
    cgns_pt_six_view_smoke as views,
    cgns_pt_smoke,
    cgns_single_runtime,
    prepare_gltf_composite_runtime_v3,
    reference_catalog,
    reference_extension_batch,
    reference_extension_gallery,
    reference_extension_provenance,
    reference_runner,
    run,
    scene_inputs,
    spatial_experiment_config as settings,
    spatial_render_script,
    process_utils,
)

ROOT = Path(__file__).resolve().parents[2]
SEED_POLICIES = {
    True: "path fixedSeed=frame-1; ReSTIR reuse seed=max(0,frame-2); first temporal pass skipped",
    False: "fixedSeed=frame-1; temporal reuse disabled",
}


def dependencies():
    return (
        cgns_pt_smoke,
        views,
        reference_runner,
        reference_extension_batch,
        reference_extension_provenance,
        adapted_reference_runner,
        settings,
        relative_paths,
        spatial_render_script,
        scene_inputs,
        reference_catalog,
        reference_extension_gallery,
        cgns_single_runtime,
        prepare_gltf_composite_runtime_v3,
        run,
        build,
        process_utils,
    )


def portable_paths(experiment_path, runtime, command, root):
    saved = list(command)
    script_index = saved.index("--script") + 1
    for index in (0, script_index):
        saved[index] = relative_paths.relative_to_document(saved[index], root)
    return {
        "path_format": "workspace-relative-v1",
        "experiment_config_path": relative_paths.relative_to_document(experiment_path, root),
        "runtime": relative_paths.relative_to_document(runtime, root),
        "command": saved,
        "command_path_base": "workspace",
    }


def graph_options(method, experiment=None, *, temporal_reuse=True):
    if type(temporal_reuse) is not bool:
        raise ValueError("Temporal reuse must be a boolean")
    mode = "temporal-on" if temporal_reuse else "temporal-off"
    value = settings.load_config() if experiment is None else experiment
    return settings.graph_options(value, mode, method)


def seed_record(frame, *, temporal_reuse=True):
    if type(frame) is not int or frame < 1:
        raise ValueError("Frame must be a positive integer")
    result = {"frame": frame, "seed": frame - 1}
    if temporal_reuse:
        # Falcor copies the previous path seed before updating this frame.
        result["reuse_seed"] = max(0, frame - 2)
    return result


def capture_schedule(warmup, count):
    if (
        type(warmup) is not int
        or type(count) is not int
        or not 0 <= warmup <= 512
        or not 1 <= count <= 128
    ):
        raise ValueError("Invalid warmup or single-frame capture count")
    return list(range(warmup + 1, warmup + count + 1))


def validate_budget(
    width, height, warmup, count, *, scout=False, resource_preflight=False, experiment=None
):
    capture_schedule(warmup, count)
    if type(width) is not int or type(height) is not int:
        raise ValueError("Resolution must be integer")
    if scout and resource_preflight:
        raise ValueError("Select a single validation profile")
    if scout:
        if not (1 <= width <= 640 and 1 <= height <= 360 and warmup + count <= 64):
            raise ValueError("Scout budget exceeded")
        return
    if resource_preflight:
        if (width, height, warmup) != (1920, 1080, 0) or count not in (1, 2):
            raise ValueError(
                "Resource preflight requires 1080p and one or two frames without warmup"
            )
        return
    value = settings.load_config() if experiment is None else settings.validate_config(experiment)
    budget = value["render"]
    expected = (budget["width"], budget["height"], budget["warmup_frames"], budget["capture_count"])
    if (width, height, warmup, count) != expected:
        raise ValueError("Comparison budget differs from experiment configuration")


def render_script(
    scene,
    camera,
    output,
    warmup,
    count,
    method,
    *,
    adapted,
    temporal_reuse=True,
    experiment=None,
    portable=False,
):
    if portable:
        scene, output = Path(relative_paths.relative_to_document(scene, output)), Path(".")
    return spatial_render_script.build_script(
        scene,
        camera,
        output,
        warmup + count,
        graph_options(method, experiment, temporal_reuse=temporal_reuse),
        adapted=adapted,
        capture_frames=capture_schedule(warmup, count),
        static_clock=True,
        record_scene_state=True,
        portable=portable,
    )


def validate_runtime(runtime, method, adapted, shader_parameters=None):
    if method == "baseline":
        return views._validate_runtime(runtime, method, adapted)
    if method != "cgns":
        raise ValueError("Unknown method")
    result = cgns_single_runtime.verify_prepared(runtime, expected_parameters=shader_parameters)
    if result.get("source_kind") != ("gltf-v3" if adapted else "reference"):
        raise ValueError("CGNS single-neighbor runtime source mismatch")
    return result


def _verify_captures(output, config, options, schedule, width, height, temporal_reuse, adapted):
    camera = json.loads((output / "resolved-camera.json").read_text(encoding="utf8"))
    reference_runner.validate_camera_records(config["camera"], camera, schedule[-1])
    if "near_plane" in config["camera"]:
        expected = config["camera"]["near_plane"]
        if any(
            not math.isclose(camera[key]["nearPlane"], expected, rel_tol=1e-6, abs_tol=1e-6)
            for key in ("initial", "first_frame", "last_frame")
        ):
            raise ValueError("Near plane differs")
    resolved = (output / "resolved.py").read_text(encoding="utf8")
    cgns_pt_smoke.validate_resolved_graph(resolved, options)
    cgns_pt_smoke.validate_resolved_graph(
        resolved, spatial_render_script.VBUFFER_OPTIONS, "VBufferRT"
    )
    state = json.loads((output / "scene-state.json").read_text(encoding="utf8"))
    audit_path = output / "scene-audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf8")) if adapted else None
    views.validate_current_scene_state(config, state, audit)
    if adapted:
        audit_path.write_text(
            json.dumps(views.portable_adapted_audit(audit, ROOT), indent=2) + "\n", encoding="utf8"
        )
    files = list(output.glob("capture.PathTracer.color.*.exr"))
    frames = run.capture_frames(files, schedule)
    artifacts = []
    for frame, path in sorted(zip(frames, files)):
        run.inspect_hdr(path, width, height)
        artifacts.append(
            {
                **seed_record(frame, temporal_reuse=temporal_reuse),
                "hdr": path.name,
                "sha256": run.sha(path),
            }
        )
    return artifacts


def launch(
    config_path,
    output,
    runtime,
    *,
    method="baseline",
    temporal_reuse=True,
    width=None,
    height=None,
    warmup=None,
    count=None,
    timeout=7200,
    scout=False,
    resource_preflight=False,
    experiment=None,
    experiment_path=None,
    experiment_sha256=None,
):
    experiment_path = Path(experiment_path or settings.DEFAULT_CONFIG).resolve(strict=True)
    selected, digest = settings.load_config_snapshot(experiment_path)
    if experiment_sha256 is not None and experiment_sha256 != digest:
        raise ValueError("Experiment configuration changed before render")
    if experiment is not None and settings.validate_config(experiment) != selected:
        raise ValueError("Experiment snapshot differs from config file")
    budget = selected["render"]
    width = budget["width"] if width is None else width
    height = budget["height"] if height is None else height
    warmup = budget["warmup_frames"] if warmup is None else warmup
    count = budget["capture_count"] if count is None else count
    validate_budget(
        width,
        height,
        warmup,
        count,
        scout=scout,
        resource_preflight=resource_preflight,
        experiment=selected,
    )
    options = graph_options(method, selected, temporal_reuse=temporal_reuse)
    schedule = capture_schedule(warmup, count)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Invalid timeout")
    if os.environ.get("FALCOR_DEVMODE") == "1":
        raise RuntimeError("FALCOR_DEVMODE overrides isolated shaders")
    config_path = Path(config_path).resolve(strict=True)
    requested_sha256 = run.sha(config_path)
    config = views.load_config(config_path)
    key = (config["scene_id"], config["view_id"])
    entry = views.frozen_views()[key]
    adapted = entry["adapted"]
    if not adapted:
        reference_runner.validate_scene_qualification(config)
    scene = (ROOT / config["scene_source"]).resolve(strict=True)
    if not scene.is_relative_to(ROOT):
        raise ValueError("Scene escapes workspace")
    runtime, output = Path(runtime).resolve(strict=True), Path(output).resolve()
    executable = (runtime / "Mogwai.exe").resolve(strict=True)
    shader = (runtime / "shaders/ReSTIRPathTracing/SpatialResampling.cs.slang").resolve(strict=True)
    command = [
        str(executable),
        "--device-type",
        "d3d12",
        "--width",
        str(width),
        "--height",
        str(height),
        "--script",
        str(output / "render.py"),
        "--headless",
    ]
    parameters = selected["methods"]["cgns"]["shader"] if method == "cgns" else None
    with process_utils.exclusive_operation(ROOT / "build/falcor/.operation.lock"):
        process_utils.check_renderer_idle()
        build_record = build.verify_build()
        reference_extension_batch.recheck_view(entry, config)
        views.validate_reference_for_view(key, experiment=selected, config=config, entry=entry)
        if adapted and scene.relative_to(ROOT).as_posix() not in entry["source_sha256"]:
            raise ValueError("Bistro scene missing from inventory")
        runtime_receipt = validate_runtime(runtime, method, adapted, parameters)
        shader_hash = run.sha(shader)
        gpu = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"], text=True
        ).strip()
        transform, exposure = reference_extension_gallery.RECIPES[key]
        source = render_script(
            scene,
            config["camera"],
            output,
            warmup,
            count,
            method,
            temporal_reuse=temporal_reuse,
            adapted=adapted,
            experiment=selected,
            portable=True,
        ).encode("utf8")
        dependency_hashes = {
            Path(module.__file__).resolve().relative_to(ROOT).as_posix(): run.sha(module.__file__)
            for module in dependencies()
        }
        scene_hash = run.sha(views.scene_manifest_path())
        kind = (
            "cgns_pt_temporal_single_frame"
            if temporal_reuse
            else "cgns_pt_paper_setting_single_frame"
        )
        if scout:
            kind += "_scout"
        elif resource_preflight:
            kind += "_resource_preflight"
        metadata = {
            **portable_paths(experiment_path, runtime, command, ROOT),
            "kind": kind,
            "requested_method": method,
            "scene_id": key[0],
            "view_id": key[1],
            "requested_scene_config_path": config_path.relative_to(ROOT).as_posix(),
            "requested_scene_config_sha256": requested_sha256,
            "scene_config_path": Path(entry["config_path"]).relative_to(ROOT).as_posix(),
            "scene_config_sha256": entry["config_sha256"],
            "reference_baseline_sha256": scene_hash,
            "scene_manifest_sha256": scene_hash,
            "reference_catalog_sha256": run.sha(views.reference_catalog_path(selected)),
            "asset_sha256": entry["asset_sha256"],
            "source_sha256": entry["source_sha256"],
            "resolution": [width, height],
            "warmup_frames": warmup,
            "capture_frames": schedule,
            "seed_policy": SEED_POLICIES[temporal_reuse],
            "spp_per_frame": 1,
            "image_accumulation": False,
            "temporal_reuse": temporal_reuse,
            "clock_policy": {"paused": True, "framerate": 0, "time": 0},
            "requested_graph_options": options,
            "display_transform": {"method": transform, "ev": exposure, "encoding": "sRGB"},
            "experiment_config_sha256": digest,
            "experiment_config": selected,
            "cgns_shader_parameters": parameters,
            "adapted": adapted,
            "retrace_schedule": "Compact default in pinned Falcor; not exposed in serialized options",
            "runtime_verification": runtime_receipt,
            "runtime_spatial_shader_sha256": shader_hash,
            "build_commit": build_record["commit"],
            "gpu_driver": gpu,
            "driver_sha256": run.sha(__file__),
            "dependency_sha256": dependency_hashes,
            "render_script_sha256": hashlib.sha256(source).hexdigest(),
        }

        def prepare(directory):
            (directory / "render.py").write_bytes(source)

        def verify(directory):
            artifacts = _verify_captures(
                directory, config, options, schedule, width, height, temporal_reuse, adapted
            )
            if (directory / "render.py").read_bytes() != source or run.sha(__file__) != metadata[
                "driver_sha256"
            ]:
                raise ValueError("Capture driver or generated script changed")
            if any(
                run.sha(ROOT / path) != expected for path, expected in dependency_hashes.items()
            ):
                raise ValueError("Capture dependency changed")
            if (
                run.sha(shader) != shader_hash
                or validate_runtime(runtime, method, adapted, parameters) != runtime_receipt
            ):
                raise ValueError("Runtime changed during render")
            if run.sha(config_path) != requested_sha256:
                raise ValueError("Requested view configuration changed")
            if (
                run.sha(experiment_path) != digest
                or run.sha(views.scene_manifest_path()) != scene_hash
            ):
                raise ValueError("Experiment or scene manifest changed")
            if (
                run.sha(views.reference_catalog_path(selected))
                != metadata["reference_catalog_sha256"]
            ):
                raise ValueError("Reference catalog changed")
            reference_extension_batch.recheck_view(entry, config)
            return artifacts

        try:
            with adapted_reference_runner.isolated_python_environment():
                return run.execute(
                    command, output, timeout, prepare=prepare, verify=verify, metadata=metadata
                )
        finally:
            if adapted and method == "baseline":
                prepare_gltf_composite_runtime_v3.quarantine_transients()


def main(*, temporal_reuse=True):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "output", "runtime"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument(
        "--experiment-config", dest="experiment_path", type=Path, default=settings.DEFAULT_CONFIG
    )
    parser.add_argument("--method", choices=("baseline", "cgns"), required=True)
    for name in ("width", "height", "warmup", "count"):
        parser.add_argument("--" + name, type=int)
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--scout", action="store_true")
    args = vars(parser.parse_args())
    config = args.pop("config")
    print(launch(config, temporal_reuse=temporal_reuse, **args))


if __name__ == "__main__":
    main()
