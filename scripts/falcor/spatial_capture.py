"""Capture fixed-view Falcor ReSTIR PT frames with an explicit reuse policy."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
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
    capture_lifecycle,
    runtime_common,
)

ROOT = Path(__file__).resolve().parents[2]
SEED_POLICIES = {
    True: "path fixedSeed=frame-1; ReSTIR reuse seed=max(0,frame-2); first temporal pass skipped",
    False: "fixedSeed=frame-1; temporal reuse disabled",
}
PDF_DIAGNOSTIC_OUTPUTS = (
    'PathTracer.nrdEmission',
    'PathTracer.nrdDiffuseRadianceHitDist',
    'PathTracer.nrdSpecularRadianceHitDist',
    'PathTracer.nrdResidualRadianceHitDist',
)


def dependencies(method='baseline'):
    modules = (
        capture_lifecycle,
        runtime_common,
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
    if method == 'pdf-similarity':
        from . import pdf_pt_runtime, pdf_pt_overlay, pdf_pt_shader
        modules += (pdf_pt_runtime, pdf_pt_overlay, pdf_pt_shader)
    return modules


def dependency_files(method='baseline'):
    files = {Path(module.__file__).resolve() for module in dependencies(method)}
    if method == 'pdf-similarity':
        from . import pdf_pt_shader
        files.update(path.resolve() for path in pdf_pt_shader.source_files())
        files.update(runtime_common.implementation_files())
    if method == 'cgns':
        from . import cgns_cached_runtime
        files.update(cgns_cached_runtime.implementation_files())
    return tuple(sorted(files))


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


def seed_record(frame, *, temporal_reuse=True, seed_offset=0):
    if type(frame) is not int or frame < 1:
        raise ValueError("Frame must be a positive integer")
    if type(seed_offset) is not int or not 0 <= seed_offset <= 2**32 - frame:
        raise ValueError("Seed offset and frame exceed uint32 seed range")
    result = {"frame": frame, "seed": seed_offset + frame - 1}
    if temporal_reuse:
        # Falcor copies the previous path seed before updating this frame.
        result["reuse_seed"] = 0 if frame == 1 else seed_offset + frame - 2
    return result


def validate_capture_controls(method, *, scout=False, seed_offset=0, pdf_profile='normal'):
    if method not in ('baseline', 'cgns', 'pdf-similarity'):
        raise ValueError('Unknown comparison method')
    if type(seed_offset) is not int or not 0 <= seed_offset < 2**32:
        raise ValueError('seed_offset must be a uint32 integer')
    if pdf_profile not in ('normal', 'one', 'zero', 'center', 'observe', 'native'):
        raise ValueError('Unknown PDF profile')
    if pdf_profile != 'normal' and (method != 'pdf-similarity' or not scout):
        raise ValueError('PDF diagnostic profiles require a bounded PDF similarity scout')


def seed_policy(temporal_reuse, seed_offset=0):
    if not seed_offset:
        return SEED_POLICIES[temporal_reuse]
    return (f'path fixedSeed={seed_offset}+frame-1; ReSTIR reuse seed=0 on first frame, '
            f'otherwise {seed_offset}+frame-2; first temporal pass skipped'
            if temporal_reuse else
            f'fixedSeed={seed_offset}+frame-1; temporal reuse disabled')


def capture_kind(method, temporal_reuse):
    prefix = 'pdf_similarity' if method == 'pdf-similarity' else 'cgns'
    mode = 'temporal' if temporal_reuse else 'paper_setting'
    return f'{prefix}_pt_{mode}_single_frame'


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
    seed_offset=0,
    pdf_profile='normal',
):
    validate_capture_controls(method, scout=True, seed_offset=seed_offset,
                              pdf_profile=pdf_profile)
    diagnostic_outputs = (() if pdf_profile == 'normal' else
                          PDF_DIAGNOSTIC_OUTPUTS[:2] if pdf_profile == 'native' else
                          PDF_DIAGNOSTIC_OUTPUTS)
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
        seed_offset=seed_offset,
        additional_outputs=diagnostic_outputs,
    )


def validate_runtime(runtime, method, adapted, shader_parameters=None, *, pdf_profile='normal'):
    if method == "baseline":
        return views._validate_runtime(runtime, method, adapted)
    if method == 'pdf-similarity':
        from . import pdf_pt_runtime
        result = pdf_pt_runtime.verify_prepared(runtime, expected_parameters=shader_parameters,
                                                profile=pdf_profile)
        if result.get('source_kind') != ('gltf-v3' if adapted else 'reference'):
            raise ValueError('PDF similarity runtime source mismatch')
        return result
    if method != "cgns":
        raise ValueError("Unknown method")
    from . import cgns_cached_runtime
    verifier = (cgns_cached_runtime if Path(runtime).parent.name.startswith(cgns_cached_runtime.PREFIX)
                else cgns_single_runtime)
    result = verifier.verify_prepared(runtime, expected_parameters=shader_parameters)
    if result.get("source_kind") != ("gltf-v3" if adapted else "reference"):
        raise ValueError("CGNS single-neighbor runtime source mismatch")
    return result


def verify_launch_inputs(config, entry, runtime, method, experiment, shader_parameters,
                         *, pdf_profile='normal', require_reference_image=False):
    """Verify the same scene, reference and private runtime before either run kind."""
    capture_lifecycle.check_shader_environment()
    build_record = build.verify_build()
    reference_extension_batch.recheck_view(entry, config)
    key = config["scene_id"], config["view_id"]
    reference = views.validate_reference_for_view(key, experiment=experiment, config=config,
                                                entry=entry, require_image=require_reference_image)
    receipt = validate_runtime(runtime, method, entry["adapted"], shader_parameters,
                               pdf_profile=pdf_profile)
    return build_record, reference, receipt


def verify_scene_records(output, config, options, last_frame, adapted, *, portable_audit=False):
    """Check the common camera, graph and scene evidence from a capture or timing run."""
    camera = json.loads((output / "resolved-camera.json").read_text(encoding="utf8"))
    reference_runner.validate_camera_records(config["camera"], camera, last_frame)
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
    if adapted and portable_audit:
        audit_path.write_text(
            json.dumps(views.portable_adapted_audit(audit, ROOT), indent=2) + "\n", encoding="utf8"
        )


def _verify_captures(output, config, options, schedule, width, height, temporal_reuse, adapted,
                     seed_offset=0):
    verify_scene_records(output, config, options, schedule[-1], adapted, portable_audit=True)
    files = list(output.glob("capture.PathTracer.color.*.exr"))
    frames = run.capture_frames(files, schedule)
    artifacts = []
    for frame, path in sorted(zip(frames, files)):
        run.inspect_hdr(path, width, height)
        artifacts.append(
            {
                **seed_record(frame, temporal_reuse=temporal_reuse, seed_offset=seed_offset),
                "hdr": path.name,
                "sha256": run.sha(path),
            }
        )
    return artifacts


def verify_pdf_diagnostics(output, schedule, width, height, profile):
    """Require exact FLOAT32 RGBA diagnostic captures, including raw alpha data."""
    if profile == 'normal':
        return []
    import OpenEXR
    import numpy as np
    expected_outputs = PDF_DIAGNOSTIC_OUTPUTS[:2] if profile == 'native' else PDF_DIAGNOSTIC_OUTPUTS
    output = Path(output)
    records = []
    expected_names = set()
    for name in expected_outputs:
        found = {}
        prefix = 'capture.' + name + '.'
        for path in output.glob(prefix + '*.exr'):
            match = re.fullmatch(re.escape(prefix) + r'(\d+)(?:\.RGBA)?\.exr', path.name)
            if not match or int(match[1]) in found:
                raise ValueError('Unexpected or duplicate PDF diagnostic capture: ' + path.name)
            found[int(match[1])] = path
        if sorted(found) != list(schedule):
            raise ValueError('Missing or unexpected PDF diagnostic frames: ' + name)
        for frame, path in sorted(found.items()):
            digest = run.sha(path)
            with OpenEXR.File(str(path), separate_channels=True) as image:
                channels = image.channels()
                if not all(channel in channels for channel in ('R', 'G', 'B', 'A')):
                    raise ValueError('PDF diagnostic EXR requires RGBA channels: ' + path.name)
                for channel in ('R', 'G', 'B', 'A'):
                    pixels = channels[channel].pixels
                    if (pixels.dtype != np.float32 or pixels.shape != (height, width)
                            or not np.isfinite(pixels).all()):
                        raise ValueError('PDF diagnostic requires finite FLOAT32 RGBA: ' + path.name)
            if run.sha(path) != digest:
                raise ValueError('PDF diagnostic changed during verification')
            expected_names.add(path.name)
            records.append({'frame': frame, 'output': name, 'hdr': path.name, 'sha256': digest})
    actual_names = {path.name for name in PDF_DIAGNOSTIC_OUTPUTS
                    for path in output.glob('capture.' + name + '.*.exr')}
    if actual_names != expected_names:
        raise ValueError('Unexpected PDF diagnostic output set')
    return records


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
    seed_offset=0,
    pdf_profile='normal',
):
    capture_lifecycle.check_shader_environment()
    validate_capture_controls(method, scout=scout, seed_offset=seed_offset,
                              pdf_profile=pdf_profile)
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
    seed_record(schedule[-1], seed_offset=seed_offset)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Invalid timeout")
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
    from . import cgns_cached_runtime
    cached_cgns = method == 'cgns' and runtime.parent.name.startswith(cgns_cached_runtime.PREFIX)
    verify_cgns_ids = cached_cgns and os.environ.get('RESTIR_LAB_CGNS_VERIFY_IDS') == '1'
    if verify_cgns_ids and not scout:
        raise ValueError('CGNS ID verification requires a scout')
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
    parameters = selected['methods'][method]['shader'] if method in ('cgns', 'pdf-similarity') else None
    with process_utils.exclusive_operation(ROOT / "build/falcor/.operation.lock"):
        process_utils.check_renderer_idle()
        if adapted and scene.relative_to(ROOT).as_posix() not in entry["source_sha256"]:
            raise ValueError("Bistro scene missing from inventory")
        build_record, _, runtime_receipt = verify_launch_inputs(
            config, entry, runtime, method, selected, parameters, pdf_profile=pdf_profile)
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
            seed_offset=seed_offset,
            pdf_profile=pdf_profile,
        ).encode("utf8")
        dependency_hashes = {
            path.relative_to(ROOT).as_posix(): run.sha(path)
            for path in dependency_files(method)
        }
        scene_hash = run.sha(views.scene_manifest_path())
        kind = capture_kind(method, temporal_reuse)
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
            "seed_policy": seed_policy(temporal_reuse, seed_offset),
            "spp_per_frame": 1,
            "image_accumulation": False,
            "temporal_reuse": temporal_reuse,
            "clock_policy": {"paused": True, "framerate": 0, "time": 0},
            "requested_graph_options": options,
            "display_transform": {"method": transform, "ev": exposure, "encoding": "sRGB"},
            "experiment_config_sha256": digest,
            "experiment_config": selected,
            "cgns_shader_parameters": parameters if method == 'cgns' else None,
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
        if cached_cgns:
            metadata['cgns_verify_ids'] = verify_cgns_ids
        if method == 'pdf-similarity':
            metadata['pdf_shader_parameters'] = parameters
            metadata['pdf_profile'] = pdf_profile
        if seed_offset:
            metadata['seed_offset'] = seed_offset

        def prepare(directory):
            (directory / "render.py").write_bytes(source)

        def verify(directory):
            artifacts = _verify_captures(
                directory, config, options, schedule, width, height, temporal_reuse, adapted,
                seed_offset=seed_offset,
            )
            diagnostic_artifacts = verify_pdf_diagnostics(directory, schedule, width, height, pdf_profile)
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
                or validate_runtime(runtime, method, adapted, parameters,
                                    pdf_profile=pdf_profile) != runtime_receipt
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
            if pdf_profile != 'normal':
                run.save(directory / 'pdf-diagnostics.json',
                         {'profile': pdf_profile, 'artifacts': diagnostic_artifacts})
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
    parser.add_argument("--method", choices=("baseline", "cgns", "pdf-similarity"), required=True)
    for name in ("width", "height", "warmup", "count"):
        parser.add_argument("--" + name, type=int)
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--scout", action="store_true")
    parser.add_argument('--seed-offset', type=int, default=0, help='Independent realization offset; frame and uint32 bounds are validated')
    parser.add_argument('--pdf-profile', choices=('normal', 'one', 'zero', 'center', 'observe', 'native'),
                        default='normal', help='Non-normal profiles require a PDF similarity scout')
    args = vars(parser.parse_args())
    config = args.pop("config")
    print(launch(config, temporal_reuse=temporal_reuse, **args))


if __name__ == "__main__":
    main()
