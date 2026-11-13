"""Run one bounded Falcor reference realization with explicit per-frame seeds."""
import argparse
import contextlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

if __package__:
    from . import run
    from .process_utils import check_renderer_idle, exclusive_operation
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import run
    from process_utils import check_renderer_idle, exclusive_operation

ROOT = Path(__file__).resolve().parents[2]
SAMPLES_PER_SEED = 1024


def sample_seeds(seed_index, count):
    if type(seed_index) is not int or not 0 <= seed_index < 8:
        raise ValueError('seed_index must be in [0, 7]')
    if type(count) is not int or not 1 <= count <= SAMPLES_PER_SEED:
        raise ValueError('count must be in [1, 1024]')
    start = seed_index * SAMPLES_PER_SEED
    return range(start, start + count)


def validate_scene_qualification(config, *, scout=False):
    if not scout and config.get('ready_for_reference') is not True:
        raise ValueError('Scene is not qualified for reference rendering')


def validate_render_budget(count, width, height, *, scout):
    if type(count) is not int or type(width) is not int or type(height) is not int:
        raise ValueError('Render budget must be integers')
    if scout:
        if not (1 <= count <= 16 and 1 <= width <= 640 and 1 <= height <= 360):
            raise ValueError('Scout is limited to 640x360 and 16 samples')
    elif (count, width, height) != (1024, 1920, 1080):
        raise ValueError('Formal reference requires 1024 spp at 1920x1080')


def asset_inventory(config, root=ROOT):
    from urllib.parse import unquote, urlsplit
    root = Path(root).resolve()
    entries = config.get('asset_roots')
    if not isinstance(entries, list) or not entries:
        raise ValueError('asset_roots must list scene dependencies')
    files = set()
    for entry in [config['scene_source'], *entries]:
        path = (root / entry).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Asset outside workspace: ' + str(path))
        if not path.exists():
            raise FileNotFoundError(path)
        candidates = [path] if path.is_file() else list(path.rglob('*'))
        for item in candidates:
            if item.is_file():
                resolved = item.resolve()
                if not resolved.is_relative_to(root):
                    raise ValueError('Asset outside workspace: ' + str(resolved))
                files.add(resolved)
    if not files:
        raise ValueError('No scene files found')
    for path in tuple(files):
        if path.suffix.lower() != '.gltf':
            continue
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        for item in data.get('buffers', []) + data.get('images', []):
            uri = item.get('uri', '')
            if not uri or uri.startswith('data:'):
                continue
            parsed = urlsplit(uri)
            if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                raise ValueError('Unsupported glTF asset URI: ' + uri)
            dependency = (path.parent / unquote(parsed.path)).resolve()
            if dependency not in files:
                raise ValueError('glTF dependency not inventoried: ' + str(dependency))
    return {p.relative_to(root).as_posix(): run.sha(p) for p in sorted(files)}


def validate_accumulation(raw, accumulated):
    import numpy as np
    if len(raw) != len(accumulated) or len(raw) < 2:
        raise ValueError('Expected matching sets of at least two frames')
    total = np.zeros_like(raw[0], dtype=np.float64)
    errors = []
    for i, (sample, actual) in enumerate(zip(raw, accumulated), 1):
        if sample.shape != total.shape or actual.shape != total.shape:
            raise ValueError('Mismatched frame dimensions')
        if not np.isfinite(sample).all() or not np.isfinite(actual).all():
            raise ValueError('Nonfinite frame values')
        total += sample
        expected = total / i
        error = float(np.max(np.abs(actual - expected)))
        errors.append(error)
        if not np.allclose(actual, expected, rtol=2e-5, atol=1e-6):
            raise ValueError(f'accumulation mismatch at frame {i}: {error}')
    if any(np.array_equal(raw[0], sample) for sample in raw[1:]):
        raise ValueError('repeated raw output across random samples')
    return errors


def camera_target(camera):
    position = camera['position']
    direction = camera['direction']
    up = camera['up']
    fov = camera['vertical_fov']
    if any(len(v) != 3 or any(not math.isfinite(float(x)) for x in v)
           for v in (position, direction, up)):
        raise ValueError('Camera vectors must be finite 3-vectors')
    if not 0 < float(fov) < 180:
        raise ValueError('Camera FOV must be between 0 and 180 degrees')
    cross = [direction[1]*up[2]-direction[2]*up[1],
             direction[2]*up[0]-direction[0]*up[2],
             direction[0]*up[1]-direction[1]*up[0]]
    if sum(x*x for x in cross) < 1e-16:
        raise ValueError('Camera direction and up must be nonzero and nonparallel')
    return [float(a) + float(b) for a, b in zip(position, direction)]


def validate_camera_records(camera, records, count):
    """Reject rendered frames whose camera differs from the requested static pose."""
    expected = {
        'position': camera['position'], 'target': camera_target(camera), 'up': camera['up'],
        'frameHeight': 24.0,
        'focalLength': 12.0 / math.tan(math.radians(camera['vertical_fov']) / 2),
        'apertureRadius': 0.0,
    }
    try:
        states = [records[name] for name in ('initial', 'first_frame', 'last_frame')]
        if states[1]['frame'] != 1 or states[2]['frame'] != count:
            raise ValueError('camera frame number mismatch')
        for state in states:
            if state['animated'] is not False:
                raise ValueError('camera animation enabled')
            for key, want in expected.items():
                actual = state[key]
                if isinstance(want, list):
                    if len(actual) != len(want) or any(
                        not math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-5)
                        for a, b in zip(actual, want)
                    ):
                        raise ValueError('camera ' + key + ' mismatch')
                elif not math.isclose(float(actual), float(want), rel_tol=1e-6, abs_tol=1e-5):
                    raise ValueError('camera ' + key + ' mismatch')
            near, far = float(state['nearPlane']), float(state['farPlane'])
            if not math.isfinite(near) or not math.isfinite(far) or not 0 < near < far:
                raise ValueError('camera clipping planes invalid')
            for key in ('nearPlane', 'farPlane'):
                if not math.isclose(float(state[key]), float(states[0][key]), rel_tol=1e-6, abs_tol=1e-5):
                    raise ValueError('camera ' + key + ' changed')
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError('camera records missing or malformed') from exc


def portable_render_paths(scene,output):
    try:
        return Path(os.path.relpath(Path(scene).resolve(),Path(output).resolve())),Path('.')
    except ValueError as exc:
        raise ValueError('Reference scene and output must be on the same volume') from exc


def portable_command(command):
    saved=list(command)
    try:
        script_index=saved.index('--script')+1
        for i in (0,script_index):saved[i]=Path(os.path.relpath(Path(saved[i]).resolve(),ROOT)).as_posix()
    except ValueError as exc:
        raise ValueError('Reference command paths must share the workspace volume') from exc
    return {'path_format':'workspace-relative-v1','command_path_base':'workspace','command':saved}


def render_script(scene, camera, output, seed_index, count, *, validation=False, portable=False):
    if portable:scene,output=portable_render_paths(scene,output)
    seeds = sample_seeds(seed_index, count)
    target = camera_target(camera)
    focal = 12.0 / math.tan(math.radians(camera['vertical_fov']) / 2)
    output_dir="str(Path('.').resolve())" if portable else repr(str(output))
    return f'''import sys, json, contextlib
from pathlib import Path
from falcor import float3
sys.path.insert(0, {str(output)!r})
from reference_graph import build_graph
g = build_graph(validation={validation!r})
m.addGraph(g)
m.loadScene({str(scene)!r})
m.scene.animated = False
camera = m.scene.camera
camera.animated = False
camera.position = float3(*{camera['position']!r})
camera.target = float3(*{target!r})
camera.up = float3(*{camera['up']!r})
camera.frameHeight = 24
camera.focalLength = {focal!r}
camera.apertureRadius = 0
m.clock.pause()
m.clock.time = 0
m.frameCapture.outputDir = {output_dir}
m.frameCapture.baseFilename = 'capture'
m.frameCapture.captureAllOutputs = False
with Path({str(Path(output) / 'resolved.py')!r}).open('w', encoding='utf-8') as f, contextlib.redirect_stdout(f):
    g.print()
def camera_state():
    return {{'position': [camera.position.x, camera.position.y, camera.position.z],
            'target': [camera.target.x, camera.target.y, camera.target.z],
            'up': [camera.up.x, camera.up.y, camera.up.z], 'frameHeight': camera.frameHeight,
            'focalLength': camera.focalLength, 'apertureRadius': camera.apertureRadius,
            'nearPlane': camera.nearPlane, 'farPlane': camera.farPlane,
            'animated': camera.animated}}
camera_records = {{'initial': camera_state()}}
tracer = g['PathTracer']
tracer.useFixedSeed = True
for sample in range({count}):
    tracer.fixedSeed = {seeds.start} + sample
    m.clock.frame = sample + 1
    m.renderFrame()
    if sample == 0:
        camera_records['first_frame'] = {{**camera_state(), 'frame': sample + 1}}
    if sample == {count} - 1:
        camera_records['last_frame'] = {{**camera_state(), 'frame': sample + 1}}
    if {validation!r}: m.frameCapture.capture()
Path({str(Path(output) / 'resolved-camera.json')!r}).write_text(json.dumps(camera_records, indent=2))
if not {validation!r}: m.frameCapture.capture()
exit()
'''


def launch(
    config_path,
    output,
    seed_index,
    count,
    width,
    height,
    timeout,
    *,
    scout=False,
    validation=False,
):
    seeds = sample_seeds(seed_index, count)
    if os.environ.get("FALCOR_DEVMODE") == "1":
        raise RuntimeError("FALCOR_DEVMODE overrides isolated shader path")
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    config_inputs = None
    if config.get("schema_version") == 2:
        from scripts.falcor.scene_inputs import load_view

        config, config_inputs = load_view(config_path, ROOT, expected_adapted=False)
    validate_scene_qualification(config, scout=scout)
    validate_render_budget(count, width, height, scout=scout)
    if validation and (not scout or count != 4):
        raise ValueError(
            "Accumulation validation requires scout with exactly 4 samples"
        )
    scene = (ROOT / config["scene_source"]).resolve()
    if not scene.is_file():
        raise FileNotFoundError(scene)
    camera_target(config["camera"])
    sources = None
    if config_inputs is not None:
        from scripts.falcor.scene_inputs import verify_profile_inventory

        assets, sources = verify_profile_inventory(config, ROOT, adapted=False)
    else:
        assets = asset_inventory(config)
    if width < 1 or height < 1 or timeout <= 0:
        raise ValueError("width, height, and timeout must be positive")
    output = Path(output).resolve()
    graph_file = Path(__file__).with_name("reference_graph.py")
    script = render_script(
        scene,
        config["camera"],
        output,
        seed_index,
        count,
        validation=validation,
        portable=True,
    )
    with exclusive_operation(ROOT / "build/falcor/.operation.lock"):
        check_renderer_idle()
        if __package__:
            from .build import verify_build
        else:
            from build import verify_build
        build = verify_build()
        if __package__:
            from . import reference_runtime
        else:
            import reference_runtime
        runtime = reference_runtime.verify()
        executable = reference_runtime.DEST / "runtime" / Path(build["executable"]).name
        gpu = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            text=True,
        ).strip()
        metadata = {
            "kind": (
                "accumulation_validation"
                if validation
                else ("reference_scout" if scout else "reference_seed")
            ),
            "scene_config": config,
            "seed_index": seed_index,
            "samples_per_pixel": count,
            "sample_seed_first": seeds.start,
            "sample_seed_last": seeds.stop - 1,
            "rng": "Falcor Uniform 128-bit; disjoint per-frame sample numbers",
            "resolution": [width, height],
            "asset_sha256": assets,
            "gpu_driver": gpu,
            **(
                {"config_input_sha256": config_inputs, "source_sha256": sources}
                if config_inputs is not None
                else {}
            ),
            "config_sha256": run.sha(config_path),
            "graph_sha256": run.sha(graph_file),
            "runner_sha256": run.sha(Path(__file__)),
            "build": build,
            "isolated_runtime_receipt_sha256": run.sha(
                reference_runtime.DEST / "receipt.json"
            ),
            "isolated_runtime_patch": {
                k: runtime[k]
                for k in (
                    "patch_file",
                    "original_sha256",
                    "patched_sha256",
                    "old",
                    "new",
                )
            },
            "light_tile_ris": "disabled; pinned PathTracer default (not exposed in script properties)",
        }
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
        metadata.update(portable_command(command))

        def prepare(out):
            (out / "reference_graph.py").write_bytes(graph_file.read_bytes())
            (out / "render.py").write_text(script, encoding="utf-8")
            run.save(out / "config.json", config)

        def verify(out):
            if config_inputs is not None:
                from scripts.falcor.scene_inputs import load_view

                if load_view(config_path, ROOT, expected_adapted=False) != (
                    config,
                    config_inputs,
                ):
                    raise ValueError("Scene profile changed during rendering")
                if verify_profile_inventory(config, ROOT, adapted=False) != (
                    assets,
                    sources,
                ):
                    raise ValueError("Pinned scene inventory changed during rendering")
            camera_records = json.loads(
                (out / "resolved-camera.json").read_text(encoding="utf-8")
            )
            validate_camera_records(config["camera"], camera_records, count)
            paths = list(out.glob("capture.AccumulatePass.output.*.exr"))
            if validation:

                def ordered(prefix):
                    pattern = re.compile(
                        re.escape(prefix) + r"\.(\d+)(?:\.RGBA)?\.exr$"
                    )
                    pairs = []
                    for path in out.glob(prefix + ".*.exr"):
                        match = pattern.fullmatch(path.name)
                        if not match:
                            raise ValueError("Unexpected capture filename " + path.name)
                        pairs.append((int(match.group(1)), path))
                    pairs.sort()
                    if [i for i, _ in pairs] != list(range(1, count + 1)):
                        raise ValueError("Capture frame count or numbering mismatch")
                    return [path for _, path in pairs]

                raw_paths = ordered("capture.PathTracer.color")
                acc_paths = ordered("capture.AccumulatePass.output")
                raw = [run.read_exr(path, require_float32=True) for path in raw_paths]
                acc = [run.read_exr(path, require_float32=True) for path in acc_paths]
                if any(img.shape != (height, width, 3) for img in raw + acc):
                    raise ValueError("Unexpected HDR image dimensions")
                errors = validate_accumulation(raw, acc)
                return [
                    {"file": p.name, "sha256": run.sha(p)}
                    for p in raw_paths + acc_paths
                ] + [{"max_abs_errors": errors}]
            if len(paths) != 1:
                raise ValueError(
                    "Expected exactly one accumulated EXR, found " + str(len(paths))
                )
            rgb = run.inspect_hdr(paths[0], width, height)
            return [
                {
                    "file": paths[0].name,
                    "sha256": run.sha(paths[0]),
                    "min": float(rgb.min()),
                    "max": float(rgb.max()),
                }
            ]

        return run.execute(
            command, output, timeout, prepare=prepare, verify=verify, metadata=metadata
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=int, required=True, help='zero-based seed index 0..7')
    parser.add_argument('--samples', type=int, default=1024)
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--timeout', type=float, default=7200)
    parser.add_argument('--scout', action='store_true', help='unqualified preview only, max 640x360 and 16 samples')
    parser.add_argument('--validate-accumulation', action='store_true')
    args = parser.parse_args()
    print(launch(args.config, args.output, args.seed, args.samples,
                 args.width, args.height, args.timeout, scout=args.scout, validation=args.validate_accumulation))


if __name__ == '__main__':
    main()
