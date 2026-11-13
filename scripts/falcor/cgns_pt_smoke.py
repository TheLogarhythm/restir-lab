# Bounded Classroom ReSTIR PT smoke run using an explicitly supplied runtime.
# The runtime selects the shader variant; both requested modes use the same graph.
import argparse
import ast
import json
import hashlib
import re
import math
import os
from pathlib import Path
import subprocess

from . import reference_runner, reference_runtime, run
from .adapted_reference_runner import isolated_python_environment
from .process_utils import check_renderer_idle, exclusive_operation

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / 'experiments/configs/falcor-pt-spatial-comparison/classroom-reference.json'


def graph_options(method):
    if method not in ('baseline', 'cgns'):
        raise ValueError('Unknown method')
    return {
        'samplesPerPixel': 1,
        'sampleGenerator': 0,  # TinyUniform is required for 32-bit path replay.
        'tracePassMode': 'MinimalPayload',
        'useReSTIRPT': True,
        'useRTXDI': False,
        'emissiveSampler': 'Power',
        'maxSurfaceBounces': 10,
        'maxDiffuseBounces': 10,
        'maxSpecularBounces': 10,
        'maxTransmissionBounces': 10,
        'useRussianRoulette': True,
        'reSTIRPathTracingOptions': {
            'useAreaReservoirs': False,
            'useTemporalResampling': False,
            'useSpatialResampling': True,
            'spatialIterations': 1,
            'spatialNeighborCount': 4,
            'spatialGatherRadius': 32,
            'usePairedNeighbors': False,
            'useDoFReconnectionShift': False,
            'useDoFReconnectionForTemporalReuse': False,
            'deriveDoFReconnectionShiftProbabilityFromCoC': False,
        },
    }


def validate_budget(width, height, frames):
    if not all(type(v) is int for v in (width, height, frames)) or not (
        1 <= width <= 640 and 1 <= height <= 360 and 1 <= frames <= 16
    ):
        raise ValueError('Smoke run is bounded to 640x360 and 16 frames')


def render_script(scene, camera, output, frames, method, *, options=None):
    from .spatial_render_script import build_script

    options = graph_options(method) if options is None else options
    return build_script(scene, camera, output, frames, options)


def validate_resolved_graph(source, requested, pass_name='PathTracer'):
    calls = [node for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == 'create_pass' and len(node.args) == 3
             and isinstance(node.args[0], ast.Constant) and node.args[0].value == pass_name]
    if len(calls) != 1: raise ValueError('Resolved graph must contain one ' + pass_name)
    actual = ast.literal_eval(calls[0].args[2])
    def check(expected, found, path='PathTracer'):
        if not isinstance(found, dict): raise ValueError('Resolved options missing at ' + path)
        for key, value in expected.items():
            if key not in found: raise ValueError('Resolved graph omits ' + path + '.' + key)
            if isinstance(value, dict): check(value, found[key], path + '.' + key)
            elif type(found[key]) is not type(value) or found[key] != value:
                raise ValueError('Resolved option mismatch at ' + path + '.' + key)
    check(requested, actual, pass_name)
    return actual


def _transient_runtime_file(name):
    return (name.startswith('.shadercache/') or name.endswith('.pdb')
            or bool(re.fullmatch(r'Mogwai\.exe\.\d+\.log', name)))


def validate_runtime_inventory(runtime, expected):
    runtime = Path(runtime)
    files = {p.relative_to(runtime).as_posix() for p in runtime.rglob('*') if p.is_file()}
    wanted = {k for k in expected if not _transient_runtime_file(k)}
    actual = {k for k in files if not _transient_runtime_file(k)}
    if actual != wanted:
        raise ValueError('Runtime inventory differs; missing=' + repr(sorted(wanted-actual)[:5]) + ' extra=' + repr(sorted(actual-wanted)[:5]))
    for name in sorted(wanted):
        path = runtime / name
        if path.is_symlink() or run.sha(path) != expected[name]:
            raise ValueError('Runtime hash mismatch: ' + name)


def validate_runtime(runtime, method):
    from . import cgns_shader_overlay as overlay
    base = (reference_runtime.DEST / 'runtime').resolve()
    runtime = Path(runtime).resolve(strict=True)
    base_receipt = reference_runtime.verify()
    if method == 'baseline':
        if runtime != base: raise ValueError('Baseline requires the verified reference runtime')
        validate_runtime_inventory(base, base_receipt['runtime_files_sha256'])
        return {'kind': 'verified_reference_runtime', 'receipt_sha256': run.sha(reference_runtime.DEST / 'receipt.json')}
    if method != 'cgns' or runtime == base:
        raise ValueError('CGNS requires a private overlay runtime')
    if (runtime.parent / 'receipt.json').is_file():
        from .cgns_runtime import verify_prepared
        verified = verify_prepared(runtime)
        if verified['source_kind'] != 'reference':
            raise ValueError('Classroom smoke requires the reference source runtime')
        return verified
    receipt_path = runtime.parent / 'overlay-receipt.json'
    receipt = json.loads(receipt_path.read_text(encoding='utf8'))
    inputs = {name:(base / overlay.MODULE / name).read_bytes().decode('utf8') for name in overlay.FILES}
    selector = overlay.SELECTOR.read_text(encoding='utf8')
    expected_sources = overlay.build_overlay(inputs, selector)
    files = receipt.get('files')
    names = {(overlay.MODULE / name).as_posix() for name in overlay.FILES}
    if receipt.get('marker') != overlay.MARKER or receipt.get('selector_sha256') != run.sha(overlay.SELECTOR) or not isinstance(files, dict) or set(files) != names:
        raise ValueError('Invalid CGNS overlay receipt')
    expected = dict(base_receipt['runtime_files_sha256'])
    for name, source in expected_sources.items():
        rel = (overlay.MODULE / name).as_posix()
        before = hashlib.sha256(inputs[name].encode('utf8')).hexdigest()
        after = hashlib.sha256(source.encode('utf8')).hexdigest()
        if files[rel] != {'original_sha256': before, 'patched_sha256': after}:
            raise ValueError('Overlay receipt mismatch: ' + rel)
        expected[rel] = after
    validate_runtime_inventory(runtime, expected)
    return {'kind': 'verified_cgns_overlay_runtime', 'base_receipt_sha256': run.sha(reference_runtime.DEST / 'receipt.json'), 'overlay_receipt_sha256': run.sha(receipt_path), 'selector_sha256': run.sha(overlay.SELECTOR)}


def launch(config_path, output, runtime, *, method='baseline', width=320, height=180, frames=4, timeout=1200):
    from PIL import Image
    from .reference_extension_gallery import display

    validate_budget(width, height, frames)
    options = graph_options(method)
    if os.environ.get('FALCOR_DEVMODE') == '1':
        raise RuntimeError('FALCOR_DEVMODE overrides isolated shader path')
    config_path = Path(config_path).resolve(strict=True)
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    if (config.get('scene_id'), config.get('view_id')) != ('classroom', 'view-a'):
        raise ValueError('This smoke driver currently supports Classroom view-a')
    reference_runner.validate_scene_qualification(config)
    scene = (ROOT / config['scene_source']).resolve(strict=True)
    if not scene.is_relative_to(ROOT): raise ValueError('Scene escapes repository')
    output = Path(output).resolve()
    runtime = Path(runtime).resolve(strict=True)
    executable = (runtime / 'Mogwai.exe').resolve(strict=True)
    shader = (runtime / 'shaders/ReSTIRPathTracing/SpatialResampling.cs.slang').resolve(strict=True)
    command = [str(executable), '--device-type', 'd3d12', '--width', str(width), '--height', str(height), '--script', str(output / 'render.py'), '--headless']
    with exclusive_operation(ROOT / 'build/falcor/.operation.lock'):
        check_renderer_idle()
        build = __import__('scripts.falcor.build', fromlist=['verify_build']).verify_build()
        assets = reference_runner.asset_inventory(config)
        runtime_receipt = validate_runtime(runtime, method)
        shader_hash = run.sha(shader)
        gpu = subprocess.check_output(['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'], text=True).strip()
        metadata = {'kind': 'cgns_pt_spatial_smoke', 'requested_method': method, 'scene_config': config, 'scene_config_sha256': run.sha(config_path), 'resolution': [width,height], 'frames': frames, 'seed_policy': 'fixedSeed=frame-1; fresh process', 'requested_graph_options': options, 'retrace_schedule': 'Compact default in pinned Falcor; not exposed in serialized options', 'runtime': str(runtime), 'runtime_spatial_shader_sha256': shader_hash, 'runtime_executable_sha256': run.sha(executable), 'runtime_falcor_dll_sha256': run.sha(runtime / 'Falcor.dll'), 'runtime_verification': runtime_receipt, 'build_commit': build['commit'], 'asset_sha256': assets, 'gpu_driver': gpu}
        def prepare(out):
            (out / 'render.py').write_text(render_script(scene, config['camera'], out, frames, method), encoding='utf8')
        def verify(out):
            paths = list(out.glob('capture.PathTracer.color.*.exr'))
            if len(paths) != 1: raise ValueError('Expected exactly one captured EXR')
            got = run.capture_frames(paths, [frames])
            rgb = run.inspect_hdr(paths[0], width, height)
            state = json.loads((out / 'resolved-camera.json').read_text(encoding='utf8'))
            reference_runner.validate_camera_records(config['camera'], state, frames)
            resolved = (out / 'resolved.py').read_text(encoding='utf8')
            validate_resolved_graph(resolved, options)
            validate_resolved_graph(resolved, {'samplePattern':'Center', 'sampleCount':1, 'useAlphaTest':True, 'useDOF':False}, 'VBufferRT')
            preview = out / 'preview.png'
            Image.fromarray(display(rgb, 'reinhard', 0)).save(preview)
            if run.sha(shader) != shader_hash: raise RuntimeError('Shader changed during run')
            if validate_runtime(runtime, method) != runtime_receipt: raise RuntimeError('Runtime changed during run')
            if reference_runner.asset_inventory(config) != assets: raise RuntimeError('Scene inputs changed')
            return [{'frame':got[0], 'hdr':paths[0].name, 'sha256':run.sha(paths[0]), 'preview':preview.name, 'preview_sha256':run.sha(preview), 'resolved_graph_sha256':run.sha(out / 'resolved.py'), 'camera_sha256':run.sha(out / 'resolved-camera.json')}]
        with isolated_python_environment():
            return run.execute(command, output, timeout, prepare=prepare, verify=verify, metadata=metadata)


def main():
    parser = argparse.ArgumentParser(description='Bounded Falcor ReSTIR PT smoke run')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--method', choices=('baseline', 'cgns'), default='baseline')
    parser.add_argument('--width', type=int, default=320)
    parser.add_argument('--height', type=int, default=180)
    parser.add_argument('--frames', type=int, default=4)
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    print(launch(args.config, args.output, args.runtime, method=args.method, width=args.width, height=args.height, frames=args.frames, timeout=args.timeout))

if __name__ == '__main__': main()
