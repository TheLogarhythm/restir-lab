"""Profile the fixed-view production PT graph, optionally exporting missing HDR."""
import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from . import spatial_capture as capture, capture_lifecycle, run
from .process_utils import exclusive_operation, check_renderer_idle
from .adapted_reference_runner import isolated_python_environment

ROOT = capture.ROOT


def instrument(source, schedule, save_hdr, *, drain_last_frame=False):
    """Optionally render one extra frame to retrieve the final GPU timestamps."""
    if type(drain_last_frame) is not bool or (drain_last_frame and save_hdr):
        raise ValueError("Final-frame drainage is supported only for timing-only runs")
    if drain_last_frame:
        last = schedule[-1]
        for before, after in (
            (f"for frame in range(1, {last + 1}):", f"for frame in range(1, {last + 2}):"),
            (f"if frame == {last}: records['last_frame']", f"if frame == {last + 1}: records['last_frame']"),
        ):
            if source.count(before) != 1:
                raise ValueError("Unexpected drain boundary")
            source = source.replace(before, after, 1)
    source = source.replace("import json, contextlib", "import json, contextlib, time", 1)
    loop = "for frame in range(1, "
    if source.count(loop) != 1:
        raise ValueError("Unexpected capture loop")
    source = source.replace(loop, "m.profiler.enabled = True\ntiming_records = []\n" + loop, 1)
    render = "    m.renderFrame()"
    if source.count(render) != 1:
        raise ValueError("Unexpected render call")
    source = source.replace(render, """    wall_begin = time.perf_counter()
    m.renderFrame()
    render_wall_ms = 1000 * (time.perf_counter() - wall_begin)
    timing_records.append({'rendered_frame': frame, 'gpu_measured_frame': frame - 1,
                           'render_wall_ms_current_frame': render_wall_ms,
                           'events_previous_frame': m.profiler.events})""", 1)
    export = "    if frame in " + repr(list(schedule)) + ": m.frameCapture.capture()"
    if source.count(export) != 1:
        raise ValueError("Unexpected HDR export schedule")
    if not save_hdr:
        source = source.replace(export, "", 1)
    tail = "exit()"
    if source.count(tail) != 1:
        raise ValueError("Unexpected script end")
    return source.replace(tail, "Path('timings.json').write_text(json.dumps(timing_records, indent=2), encoding='utf8')\nexit()", 1)


def validate_timings(path, schedule, *, drain_last_frame=False):
    records = json.loads(Path(path).read_text(encoding="utf8"))
    if [r["rendered_frame"] for r in records] != list(range(1, schedule[-1] + 1 + int(drain_last_frame))):
        raise ValueError("Timing render sequence differs")
    selected = []
    for row in records:
        if row["gpu_measured_frame"] != row["rendered_frame"] - 1:
            raise ValueError("Profiler delay was mislabelled")
        if row["gpu_measured_frame"] not in schedule:
            continue
        events = row["events_previous_frame"]
        if not events or not any("/tracePass/gpu_time" in k for k in events):
            raise ValueError("Missing actual GPU trace timings")
        for lane in events.values():
            value = lane["value"]
            if not isinstance(value, (float, int)) or not 0 <= value < 1e8:
                raise ValueError("Invalid timing sample")
        selected.append(row["gpu_measured_frame"])
    if selected != list(schedule if drain_last_frame else schedule[:-1]):
        raise ValueError("Missing steady-state GPU timing frames")
    return {"measured_gpu_frames": selected, "unmeasured_last_gpu_frame": None if drain_last_frame else schedule[-1],
            "units": "milliseconds", "profiler_latency_frames": 1,
            "sha256": run.sha(path)}


def launch(config_path, output, runtime, method, *, save_hdr=False, scout=False, scout_budget=None,
           experiment_path=None, temporal_reuse=True, drain_last_frame=False):
    capture_lifecycle.check_shader_environment()
    output, runtime = Path(output).resolve(), Path(runtime).resolve(strict=True)
    config_path = Path(config_path).resolve(strict=True)
    experiment_path = Path(experiment_path or capture.settings.DEFAULT_CONFIG).resolve(strict=True)
    experiment, digest = capture.settings.load_config_snapshot(experiment_path)
    entry = capture.views.frozen_views()
    config = capture.views.load_config(config_path)
    key = config["scene_id"], config["view_id"]
    entry = entry[key]
    if scout_budget is not None and not scout:
        raise ValueError('A custom scout budget requires --scout')
    budget = experiment["render"]
    width, height, warmup, count = ((scout_budget or (96, 64, 2, 4)) if scout else
                                  tuple(budget[k] for k in ("width", "height", "warmup_frames", "capture_count")))
    if scout and drain_last_frame and warmup + count >= 64:
        raise ValueError("Profiler drain exceeds the scout frame budget")
    from . import cgns_cached_runtime
    cached_cgns = method == 'cgns' and runtime.parent.name.startswith(cgns_cached_runtime.PREFIX)
    verify_ids = cached_cgns and os.environ.get('RESTIR_LAB_CGNS_VERIFY_IDS') == '1'
    if verify_ids and not scout:
        raise ValueError('CGNS ID verification requires a scout')
    capture.validate_budget(width, height, warmup, count, scout=scout, experiment=experiment)
    schedule = capture.capture_schedule(warmup, count)
    options = capture.graph_options(method, experiment, temporal_reuse=temporal_reuse)
    scene = (ROOT / config["scene_source"]).resolve(strict=True)
    raw = capture.render_script(scene, config["camera"], output, warmup, count, method,
                                adapted=entry["adapted"], temporal_reuse=temporal_reuse,
                                experiment=experiment, portable=True)
    source = instrument(raw, schedule, save_hdr, drain_last_frame=drain_last_frame).encode("utf8")
    rendered_frames = schedule[-1] + int(drain_last_frame)
    deps = {p.relative_to(ROOT).as_posix(): run.sha(p)
            for p in (*capture.dependency_files(method), Path(__file__), Path(capture.__file__))}
    command = [str(runtime / "Mogwai.exe"), "--device-type", "d3d12", "--width", str(width),
               "--height", str(height), "--script", str(output / "render.py"), "--headless"]
    with exclusive_operation(ROOT / "build/falcor/.operation.lock"):
        check_renderer_idle()
        parameters = experiment["methods"][method]["shader"] if method == "pdf-similarity" or cached_cgns else None
        # A retained default CGNS runtime is verified with its exact frozen selector.
        built, ref, receipt = capture.verify_launch_inputs(
            config, entry, runtime, method, experiment, parameters, require_reference_image=True)
        gpu = subprocess.check_output(["nvidia-smi", "--query-gpu=name,driver_version",
                                       "--format=csv,noheader"], text=True).strip()
        metadata = {**capture.portable_paths(experiment_path, runtime, command, ROOT),
                    "kind": "falcor_fixed_view_profiled_capture" if save_hdr else "falcor_fixed_view_timing_supplement",
                    "scene_id": key[0], "view_id": key[1], "requested_method": method,
                    "temporal_reuse": temporal_reuse, "resolution": [width, height], "warmup_frames": warmup,
                    "capture_frames": schedule, "seed_policy": capture.seed_policy(temporal_reuse),
                    "drain_last_frame": drain_last_frame, "rendered_frames": rendered_frames,
                    "spp_per_frame": 1, "image_accumulation": False, "adapted": entry["adapted"],
                    "requested_graph_options": options, "reference": ref,
                    "clock_policy": {"paused": True, "framerate": 0, "time": 0},
                    "scene_config_sha256": run.sha(config_path), "scene_config_path": config_path.relative_to(ROOT).as_posix(),
                    "asset_sha256": entry["asset_sha256"], "source_sha256": entry["source_sha256"],
                    "experiment_config": experiment, "experiment_config_sha256": digest,
                    "runtime_verification": receipt, "gpu_driver": gpu, "build_commit": built["commit"],
                    "source_files_sha256": deps, "render_script_sha256": hashlib.sha256(source).hexdigest(),
                    "save_hdr": save_hdr, "scout": scout, "timing_boundary": "Falcor hierarchical GPU timestamps; frame N-1 read after render N"}
        if cached_cgns:
            metadata["cgns_verify_ids"] = verify_ids
        if method == "pdf-similarity":
            metadata.update(pdf_profile="normal", pdf_shader_parameters=parameters)

        def prepare(directory):
            (directory / "render.py").write_bytes(source)

        def verify(directory):
            if verify_ids:
                # Every in-bounds pixel, including background, gets an ID or the sentinel.
                text = (directory / 'renderer.log').read_text(encoding='utf8', errors='replace')
                checks = [tuple(map(int, row)) for row in re.findall(
                    r'CGNS ID check frame=(\d+) round=(\d+) pixels=(\d+) accepted=(\d+) mismatches=(\d+)', text)]
                rounds = options['reSTIRPathTracingOptions']['spatialIterations']
                if ([(f, r) for f, r, *_ in checks] != [(f, r) for f in range(rendered_frames) for r in range(rounds)]
                        or any(n != width * height or not 0 <= accepted <= n or mismatches
                               for _, _, n, accepted, mismatches in checks)
                        or not any(row[3] for row in checks)):
                    raise ValueError('Missing or failed per-pixel CGNS ID comparisons')
                run.save(directory / 'cgns-id-checks.json',
                         {'columns': ['frame_index', 'round', 'pixels', 'accepted', 'mismatches'], 'rows': checks})
            timing = validate_timings(directory / "timings.json", schedule, drain_last_frame=drain_last_frame)
            if save_hdr:
                artifacts = capture._verify_captures(directory, config, options, schedule,
                                                     width, height, temporal_reuse, entry["adapted"])
            else:
                if list(directory.glob("*.exr")):
                    raise ValueError("Timing-only run unexpectedly exported HDR")
                capture.verify_scene_records(directory, config, options, rendered_frames, entry["adapted"])
                artifacts = []
            if any(run.sha(ROOT / p) != h for p, h in deps.items()) or (directory / "render.py").read_bytes() != source:
                raise ValueError("Measurement implementation changed")
            if capture.validate_runtime(runtime, method, entry["adapted"], parameters) != receipt:
                raise ValueError("Measurement runtime changed")
            capture.reference_extension_batch.recheck_view(entry, config)
            if run.sha(experiment_path) != digest:
                raise ValueError("Measurement configuration changed")
            run.save(directory / "timing-validation.json", timing)
            return artifacts

        with isolated_python_environment():
            return run.execute(command, output, 1200, prepare=prepare, verify=verify, metadata=metadata)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "runtime", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--method", choices=("baseline", "cgns", "pdf-similarity"), required=True)
    parser.add_argument("--experiment-config", dest="experiment_path", type=Path)
    parser.add_argument("--temporal-off", dest="temporal_reuse", action="store_false")
    parser.add_argument("--drain-last-frame", action="store_true")
    parser.add_argument("--save-hdr", action="store_true")
    parser.add_argument("--scout", action="store_true")
    parser.add_argument("--scout-budget", nargs=4, type=int, metavar=("WIDTH", "HEIGHT", "WARMUP", "COUNT"),
                        help="Override the bounded scout dimensions and schedule")
    args = vars(parser.parse_args())
    print(launch(args.pop("config"), **args))


if __name__ == "__main__":
    main()
