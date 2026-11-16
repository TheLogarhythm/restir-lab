"""Scene/reference bindings, saved captures, and runtime inputs shared by PT runners."""

from pathlib import Path
import re

from . import spatial_capture as capture, spatial_experiment_config as experiment_config
from . import cgns_pt_six_view_smoke as six, reference_catalog as reference_sets, run

ROOT = capture.ROOT
RUNTIME = {
    ("baseline", False): ROOT / "build/falcor-reference-runtime/runtime",
    ("baseline", True): ROOT / "build/falcor-gltf-composite-runtime-v3/runtime",
    ("cgns", False): ROOT / "build/falcor-cgns-single-reference/runtime",
    ("cgns", True): ROOT / "build/falcor-cgns-single-gltf-v3/runtime",
}


def validate_artifacts(directory, artifacts, schedule, width, height, *, temporal_reuse=True, seed_offset=0):
    directory = Path(directory).resolve(strict=True)
    if not isinstance(artifacts, list) or len(artifacts) != len(schedule):
        raise ValueError("Unexpected capture artifact count")
    expected_names = set()
    by_frame = {}
    for record in artifacts:
        if not isinstance(record, dict) or type(record.get("frame")) is not int:
            raise ValueError("Invalid capture artifact")
        frame = record["frame"]
        expected_seed = capture.seed_record(frame, temporal_reuse=temporal_reuse, seed_offset=seed_offset)
        name = record.get("hdr")
        if (
            frame not in schedule
            or frame in by_frame
            or record.get("seed") != expected_seed["seed"]
            or (temporal_reuse and record.get("reuse_seed") != expected_seed["reuse_seed"])
            or (not isinstance(name, str))
            or (Path(name).name != name)
            or (
                not re.fullmatch(
                    "capture\\.PathTracer\\.color\\." + str(frame) + "(?:\\.RGBA)?\\.exr", name
                )
            )
        ):
            raise ValueError("Capture frame, seed or path mismatch")
        digest = record.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("Invalid capture hash")
        path = (directory / name).resolve(strict=True)
        if not path.is_relative_to(directory) or not path.is_file() or run.sha(path) != digest:
            raise ValueError("Capture hash or location mismatch")
        run.inspect_hdr(path, width, height)
        if run.sha(path) != digest:
            raise ValueError("Capture changed while inspecting")
        expected_names.add(name)
        by_frame[frame] = {**expected_seed, "hdr": name, "sha256": digest}
    actual = {p.name for p in directory.glob("capture.PathTracer.color.*.exr")}
    if actual != expected_names or sorted(by_frame) != list(schedule):
        raise ValueError("Unexpected capture set")
    return [by_frame[n] for n in schedule]


def reference_catalog(experiment=None, *, require_images=False, image_views=None, root=None):
    """Lock all view metadata while reading EXRs only for the requested image scope."""
    experiment = (
        experiment_config.load_config()
        if experiment is None
        else experiment_config.validate_config(experiment)
    )
    entries = six.frozen_views()
    root = Path(ROOT if root is None else root).resolve(strict=True)
    manifest = (root / experiment["reference_catalog"]).resolve(strict=True)
    if not manifest.is_relative_to(root):
        raise ValueError("Reference catalog escapes workspace")
    references = reference_sets.load_catalog(manifest, root, require_images=False)
    if set(references) != set(entries):
        raise ValueError("Reference view set differs")
    if image_views is not None and not require_images:
        raise ValueError("Reference image selection requires image validation")
    selected_images = set(entries) if image_views is None else set(image_views)
    if not selected_images or not selected_images.issubset(entries):
        raise ValueError("Reference image selection must contain known views")
    catalog = {}
    for key, entry in entries.items():
        item = references[key]
        path = (root / item["path"]).resolve()
        if require_images and key in selected_images:
            if run.sha(path) != item["sha256"]:
                raise ValueError("Reference image hash mismatch")
            run.inspect_hdr(path, experiment["render"]["width"], experiment["render"]["height"])
            if run.sha(path) != item["sha256"]:
                raise ValueError("Reference image changed while inspecting")
        config = Path(entry["config_path"]).resolve(strict=True)
        if run.sha(config) != entry["config_sha256"]:
            raise ValueError("Scene config hash differs")
        resolved_config = six.load_config(config)
        reference_sets.validate_binding(item, resolved_config, entry, experiment)
        catalog[key] = {
            "entry": entry,
            "config": resolved_config,
            "config_path": config,
            "reference": {"path": str(path), "sha256": item["sha256"]},
        }
    return catalog


def prepare_runtimes(experiment, *, compare_method='cgns', runtime_paths=None):
    from . import cgns_cached_runtime

    runtime_paths = RUNTIME if runtime_paths is None else runtime_paths

    if compare_method == 'pdf-similarity':
        from . import pdf_pt_runtime
        paths = {key: path for key, path in runtime_paths.items() if key[0] == 'baseline'}
        for adapted, kind in ((False, 'reference'), (True, 'gltf-v3')):
            paths[compare_method, adapted] = pdf_pt_runtime.ensure_variant(
                kind, experiment['methods'][compare_method]['shader'], profile='normal')
        return paths
    if compare_method != 'cgns':
        raise ValueError('Unknown comparison method')
    paths = dict(runtime_paths)
    for adapted, kind in ((False, "reference"), (True, "gltf-v3")):
        paths["cgns", adapted] = cgns_cached_runtime.ensure_variant(
            kind, experiment["methods"]["cgns"]["shader"]
        )
    return paths


def runtime_snapshots(experiment=None, runtime_paths=None):
    experiment = (
        experiment_config.load_config()
        if experiment is None
        else experiment_config.validate_config(experiment)
    )
    runtime_paths = RUNTIME if runtime_paths is None else runtime_paths
    snapshots = {}
    for (method, adapted), runtime in runtime_paths.items():
        rt = runtime.resolve(strict=True)
        parameters = experiment['methods'][method]['shader'] if method in ('cgns', 'pdf-similarity') else None
        snapshots[method, adapted] = capture.validate_runtime(rt, method, adapted, parameters)
    return snapshots
