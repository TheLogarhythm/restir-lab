"""Verifier-only, same-process PDF history and full graph reset versus fresh graphs.

Requires an already prepared private observe runtime. Never prepares a runtime
or writes to an existing output directory. Captured fixed seeds and clock frame
numbers come from the running Mogwai script; reuse seeds are not inferred.
The bounded graph-replacement check removes the used graph and constructs a
new PathTracer. It compares all HDR pixels and M/W/pHat bits to a separate new
graph with the same seed and native first-frame state (11 or 19 total frames).
Camera-cut diagnostics explicitly call tracer.reset(); continuous camera motion
retains reprojectable history and does not imply a camera-cut reset.
"""

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re

import numpy as np

from . import spatial_capture as capture, spatial_render_script, pdf_pt_runtime
from . import cgns_pt_six_view_smoke as views, reference_runner, reference_extension_batch, run
from . import spatial_experiment_config as settings
from .adapted_reference_runner import isolated_python_environment
from .process_utils import check_renderer_idle, exclusive_operation
from scripts.analysis.relative_paths import relative_to_document

ROOT = Path(__file__).resolve().parents[2]


def frame_plan(seed_offset=0, *, camera_cut=False):
    if type(camera_cut) is not bool:
        raise ValueError('camera_cut must be a boolean')
    largest = 106 if camera_cut else 8
    if type(seed_offset) is not int or not 0 <= seed_offset <= 2**32 - 1 - largest:
        raise ValueError('Diagnostic seeds exceed uint32')
    plan = []

    def step(graph, seed, pose='base', reset=False, label=None, replace=False):
        plan.append({'clock_frame': len(plan) + 1, 'graph': graph, 'path_seed': seed,
                     'pose': pose, 'reset': reset, 'capture': label, 'replace': replace})

    for index in range(6):
        step('reset-history', seed_offset + index,
             label='before-reset' if index == 5 else None)
    step('reset-history', seed_offset + 6, reset=True, label='after-reset')
    step('fresh-reset', seed_offset + 6, label='fresh-reset')
    step('reset-history', seed_offset + 7, label='before-replacement')
    step('reset-history', seed_offset + 8, replace=True, label='after-replacement')
    step('fresh-replacement', seed_offset + 8, label='fresh-replacement')
    if camera_cut:
        for index in range(6):
            step('cut-history', seed_offset + 100 + index,
                 label='before-cut' if index == 5 else None)
        step('cut-history', seed_offset + 106, pose='cut', reset=True, label='after-cut')
        step('fresh-cut', seed_offset + 106, pose='cut', label='fresh-cut')
    return plan


def render_script(scene, camera, plan, *, adapted=False, experiment=None):
    options = capture.graph_options('pdf-similarity', experiment, temporal_reuse=True)
    cameras = {'base': deepcopy(camera), 'cut': deepcopy(camera)}
    cameras['base']['target'] = reference_runner.camera_target(camera)
    cameras['cut']['position'][0] += 1.0
    cameras['cut']['target'] = list(reference_runner.camera_target(camera))
    cameras['cut']['target'][0] += 1.0
    focal = 12.0 / math.tan(math.radians(camera['vertical_fov']) / 2)
    scene_import = ', SceneBuilderFlags' if adapted else ''
    flags = ', SceneBuilderFlags.DontOptimizeMaterials' if adapted else ''
    return f'''import json, contextlib
from pathlib import Path
from falcor import float3, RenderGraph, createPass, TextureChannelFlags{scene_import}

def make_graph(name):
    graph = RenderGraph(name)
    graph.addPass(createPass('VBufferRT', {spatial_render_script.VBUFFER_OPTIONS!r}), 'VBufferRT')
    graph.addPass(createPass('PathTracer', {options!r}), 'PathTracer')
    for name in ('vbuffer', 'viewW', 'mvec'):
        graph.addEdge('VBufferRT.' + name, 'PathTracer.' + name)
    graph.markOutput('PathTracer.color')
    for output in {capture.PDF_DIAGNOSTIC_OUTPUTS!r}:
        graph.markOutput(output, TextureChannelFlags.RGBA)
    m.addGraph(graph)
    return graph

graphs = {{'reset-history': make_graph('reset-history')}}
graph_frames = {{'reset-history': 0}}
m.loadScene({str(scene)!r}{flags})
m.scene.animated = False
camera = m.scene.camera
camera.animated = False
camera.frameHeight = 24
camera.focalLength = {focal!r}
camera.apertureRadius = 0
poses = {cameras!r}
current_pose = None
m.clock.framerate = 0
m.clock.pause()
m.clock.time = 0
m.frameCapture.outputDir = str(Path('.').resolve())
m.frameCapture.captureAllOutputs = False
records = []
for event in {plan!r}:
    if event['replace']:
        m.removeGraph(graphs.pop(event['graph']))
        graph_frames.pop(event['graph'])
    if event['graph'] not in graphs:
        graphs[event['graph']] = make_graph(event['graph'])
        graph_frames[event['graph']] = 0
    graph = graphs[event['graph']]
    graph_created = graph_frames[event['graph']] == 0
    m.setActiveGraph(graph)
    if current_pose != event['pose']:
        pose = poses[event['pose']]
        camera.position = float3(*pose['position'])
        camera.target = float3(*pose['target'])
        camera.up = float3(*pose['up'])
        if 'near_plane' in pose: camera.nearPlane = pose['near_plane']
        current_pose = event['pose']
    tracer = graph['PathTracer']
    tracer.useFixedSeed = True
    if event['reset']: tracer.reset()
    previous_fixed_seed = int(tracer.fixedSeed)
    tracer.fixedSeed = event['path_seed']
    m.clock.frame = event['clock_frame']
    m.renderFrame()
    graph_frames[event['graph']] += 1
    if m.clock.framerate != 0 or abs(m.clock.time) > 1e-9:
        raise RuntimeError('Static diagnostic clock drift')
    records.append({{**event, 'actual_fixed_seed': int(tracer.fixedSeed),
                    'fixed_seed_before_assignment': previous_fixed_seed,
                    'graph_created': graph_created,
                    'renders_on_graph': graph_frames[event['graph']],
                    'actual_clock_frame': int(m.clock.frame),
                    'camera': {{'position': [camera.position.x, camera.position.y, camera.position.z],
                               'target': [camera.target.x, camera.target.y, camera.target.z],
                               'up': [camera.up.x, camera.up.y, camera.up.z]}}}})
    if event['capture']:
        m.frameCapture.baseFilename = event['capture']
        m.frameCapture.capture()
for name, graph in graphs.items():
    with Path('resolved-' + name + '.py').open('w', encoding='utf8') as stream, contextlib.redirect_stdout(stream):
        graph.print()
Path('executed-frames.json').write_text(json.dumps(records, indent=2), encoding='utf8')
exit()
'''


def compare_statistics(moment, count, fresh_moment, fresh_count):
    arrays = [np.asarray(value) for value in (moment, count, fresh_moment, fresh_count)]
    moment, count, fresh_moment, fresh_count = arrays
    if (moment.ndim != 3 or moment.shape[-1] != 4 or moment.shape != fresh_moment.shape
            or not moment.size
            or count.shape != moment.shape[:2] or fresh_count.shape != count.shape
            or any(value.dtype != np.float32 or not np.isfinite(value).all() for value in arrays)):
        raise ValueError('Expected matching finite FLOAT32 raw A/B and count images')
    if (np.any(count < 0) or np.any(count > 1) or not np.any(count > 0)
            or np.any(fresh_count < 0) or np.any(fresh_count > 1)):
        raise ValueError('Reset/cut retained count history or contains no direction evidence')
    changed = int(np.count_nonzero(np.any(moment.view(np.uint32) != fresh_moment.view(np.uint32), axis=-1)))
    changed_count = int(np.count_nonzero(count.view(np.uint32) != fresh_count.view(np.uint32)))
    direction = np.divide(moment[..., :3], moment[..., 3:4],
                          out=np.zeros_like(moment[..., :3]), where=moment[..., 3:4] > 0)
    fresh_direction = np.divide(fresh_moment[..., :3], fresh_moment[..., 3:4],
                                out=np.zeros_like(fresh_moment[..., :3]), where=fresh_moment[..., 3:4] > 0)
    if changed or changed_count:
        raise ValueError(f'Raw A/B or count differs from fresh graph: {changed}, {changed_count} pixels')
    return {'raw_moment_changed_pixels': changed, 'count_changed_pixels': changed_count,
            'direction_max_abs_difference': float(np.max(np.abs(direction - fresh_direction))),
            'evidence_pixels': int(np.count_nonzero(count > 0)), 'max_count': float(np.max(count))}


def compare_system_state(color, reservoir, fresh_color, fresh_reservoir):
    arrays = [np.asarray(value) for value in (color, reservoir, fresh_color, fresh_reservoir)]
    color, reservoir, fresh_color, fresh_reservoir = arrays
    if (color.ndim != 3 or color.shape[-1] != 3 or not color.size or color.shape != fresh_color.shape
            or reservoir.shape != (*color.shape[:2], 4) or fresh_reservoir.shape != reservoir.shape
            or any(value.dtype != np.float32 or not np.isfinite(value).all() for value in arrays)):
        raise ValueError('Expected matching finite FLOAT32 HDR and M/W/pHat images')
    hdr_changed = int(np.count_nonzero(np.any(color.view(np.uint32) != fresh_color.view(np.uint32), axis=-1)))
    reservoir_changed = int(np.count_nonzero(np.any(
        reservoir[..., :3].copy().view(np.uint32) != fresh_reservoir[..., :3].copy().view(np.uint32), axis=-1)))
    if hdr_changed or reservoir_changed:
        raise ValueError(f'Graph replacement differs from fresh HDR or M/W/pHat: {hdr_changed}, {reservoir_changed} pixels')
    return {'hdr_changed_pixels': hdr_changed, 'reservoir_m_w_phat_changed_pixels': reservoir_changed,
            'pixel_count': int(color.shape[0] * color.shape[1]), 'comparison': 'bitwise FLOAT32, full image'}


def _rgba(path, width, height):
    import OpenEXR
    with OpenEXR.File(str(path), separate_channels=True) as image:
        channels = image.channels()
        if not all(name in channels for name in ('R', 'G', 'B', 'A')):
            raise ValueError('Diagnostic EXR requires raw RGBA channels')
        value = np.stack([channels[name].pixels for name in ('R', 'G', 'B', 'A')], axis=-1)
    if value.shape != (height, width, 4) or value.dtype != np.float32 or not np.isfinite(value).all():
        raise ValueError('Invalid diagnostic RGBA EXR')
    return value


def verify_results(output, plan, width, height):
    output = Path(output)
    executed = json.loads((output / 'executed-frames.json').read_text(encoding='utf8'))
    if len(executed) != len(plan):
        raise ValueError('Diagnostic execution frame count differs')
    for actual, expected in zip(executed, plan):
        if (any(actual.get(key) != value for key, value in expected.items())
                or actual.get('actual_fixed_seed') != expected['path_seed']
                or actual.get('actual_clock_frame') != expected['clock_frame']):
            raise ValueError('Executed diagnostic graph, clock frame or fixed seed differs')
    records, images = [], {}
    for event in plan:
        phase = event['capture']
        if phase is None:
            continue
        images[phase] = {}
        for name in ('color', *(name.split('.')[-1] for name in capture.PDF_DIAGNOSTIC_OUTPUTS)):
            pattern = (re.escape(phase + '.PathTracer.' + name + '.' + str(event['clock_frame']))
                       + r'(?:\.RGBA)?\.exr')
            matches = [path for path in output.glob(phase + '.PathTracer.' + name + '.*.exr')
                       if re.fullmatch(pattern, path.name)]
            if len(matches) != 1:
                raise ValueError('Missing or duplicate diagnostic capture: ' + phase + '/' + name)
            path = matches[0]
            if name == 'color':
                images[phase][name] = run.inspect_hdr(path, width, height)
            else:
                images[phase][name] = _rgba(path, width, height)
            records.append({'phase': phase, 'clock_frame': event['clock_frame'],
                            'output': name, 'path': path.name, 'sha256': run.sha(path)})
    if {path.name for path in output.glob('*.exr')} != {record['path'] for record in records}:
        raise ValueError('Unexpected diagnostic capture set')
    result = {}
    for reason in ('reset', 'cut'):
        phase = 'after-' + reason
        if phase not in images:
            continue
        before = images['before-' + reason]['nrdEmission'][..., 3]
        if not np.any(before > 1):
            raise ValueError('Warmup did not establish nontrivial direction history')
        current, fresh = images[phase], images['fresh-' + reason]
        result[reason] = compare_statistics(current['nrdDiffuseRadianceHitDist'], current['nrdEmission'][..., 3],
                                            fresh['nrdDiffuseRadianceHitDist'], fresh['nrdEmission'][..., 3])
        left = next(row for row in executed if row['capture'] == phase)
        right = next(row for row in executed if row['capture'] == 'fresh-' + reason)
        previous = next(row for row in executed if row['capture'] == 'before-' + reason)
        if left.get('camera') != right.get('camera'):
            raise ValueError('Reset/cut and fresh cameras differ')
        if (left.get('camera') == previous.get('camera')) != (reason == 'reset'):
            raise ValueError('Reset must preserve the camera; camera cut must change its pose')
        result[reason]['warmup_max_count'] = float(np.max(before))
    old = images['before-replacement']['nrdEmission'][..., 3]
    if not np.any(old > 1):
        raise ValueError('Graph replacement was not preceded by nontrivial history')
    replaced = images['after-replacement']
    fresh = images['fresh-replacement']
    left = next(row for row in executed if row['capture'] == 'after-replacement')
    right = next(row for row in executed if row['capture'] == 'fresh-replacement')
    previous = next(row for row in executed if row['capture'] == 'before-replacement')
    if (left.get('graph_created') is not True or right.get('graph_created') is not True
            or left.get('renders_on_graph') != 1 or right.get('renders_on_graph') != 1
            or left.get('actual_fixed_seed') != right.get('actual_fixed_seed')
            or left.get('fixed_seed_before_assignment') != right.get('fixed_seed_before_assignment')
            or left.get('camera') != right.get('camera') or left.get('camera') != previous.get('camera')):
        raise ValueError('Replacement and fresh must use new PathTracers, matching seeds and camera')
    result['replacement'] = compare_system_state(replaced['color'], replaced['nrdEmission'],
                                                 fresh['color'], fresh['nrdEmission'])
    result['replacement']['direction_statistics'] = compare_statistics(
        replaced['nrdDiffuseRadianceHitDist'], replaced['nrdEmission'][..., 3],
        fresh['nrdDiffuseRadianceHitDist'], fresh['nrdEmission'][..., 3])
    result['replacement'].update({
        'path_seed': left['actual_fixed_seed'],
        'fixed_seed_before_assignment': left['fixed_seed_before_assignment'],
        'warmup_max_count': float(np.max(old)),
        'reuse_seed_control': 'Both new PathTracer/ReSTIR instances use matching native first-frame state; no seed inferred from clock labels.',
        'user_reset_step': 'Remove the used render graph and create a new graph with a newly constructed PathTracer and the same camera/options.'})
    return {'status': 'passed', 'comparisons': result, 'artifacts': records,
            'limitations': 'One fixed scene and bounded seeds; raw moments/count only, not an unbiasedness proof.'}


def launch(config_path, output, runtime, *, width=160, height=90, seed_offset=0,
           camera_cut=False, timeout=1200, experiment_path=settings.DEFAULT_CONFIG):
    plan = frame_plan(seed_offset, camera_cut=camera_cut)
    capture.validate_budget(width, height, 0, len(plan), scout=True)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise ValueError('Reset-check timeout must be in (0, 3600] seconds')
    output, runtime = Path(output).resolve(), Path(runtime).resolve(strict=True)
    if output.exists() or not output.is_relative_to((ROOT / 'runs').resolve()):
        raise ValueError('Reset-check output must be a new directory under runs')
    if os.environ.get('FALCOR_DEVMODE') == '1':
        raise RuntimeError('FALCOR_DEVMODE overrides isolated shaders')
    config_path, experiment_path = Path(config_path).resolve(strict=True), Path(experiment_path).resolve(strict=True)
    experiment, experiment_hash = settings.load_config_snapshot(experiment_path)
    config = views.load_config(config_path)
    key = (config['scene_id'], config['view_id'])
    entry = views.frozen_views()[key]
    source_kind = 'gltf-v3' if entry['adapted'] else 'reference'
    scene = (ROOT / config['scene_source']).resolve(strict=True)
    if not scene.is_relative_to(ROOT):
        raise ValueError('Diagnostic scene escapes the workspace')
    parameters = experiment['methods']['pdf-similarity']['shader']
    command = [str(runtime / 'Mogwai.exe'), '--device-type', 'd3d12', '--width', str(width),
               '--height', str(height), '--script', str(output / 'render.py'), '--headless']
    source = render_script(Path(relative_to_document(scene, output)), config['camera'], plan,
                           adapted=entry['adapted'], experiment=experiment).encode('utf8')
    with exclusive_operation(ROOT / 'build/falcor/.operation.lock'):
        check_renderer_idle()
        reference_extension_batch.recheck_view(entry, config)
        receipt = pdf_pt_runtime.verify_prepared(runtime, expected_parameters=parameters, profile='observe')
        if receipt.get('source_kind') != source_kind:
            raise ValueError('Observe runtime does not match the scene family')
        hashes = {path.relative_to(ROOT).as_posix(): run.sha(path)
                  for path in (*capture.dependency_files('pdf-similarity'), Path(__file__).resolve())}
        config_hash = run.sha(config_path)

        def prepare(directory):
            (directory / 'render.py').write_bytes(source)

        def verify(directory):
            result = verify_results(directory, plan, width, height)
            if (run.sha(config_path) != config_hash or run.sha(experiment_path) != experiment_hash
                    or (directory / 'render.py').read_bytes() != source
                    or any(run.sha(ROOT / name) != digest for name, digest in hashes.items())
                    or pdf_pt_runtime.verify_prepared(runtime, expected_parameters=parameters,
                                                      profile='observe') != receipt):
                raise ValueError('Diagnostic inputs or runtime changed')
            reference_extension_batch.recheck_view(entry, config)
            run.save(directory / 'reset-summary.json', result)
            return result['artifacts']

        with isolated_python_environment():
            return run.execute(command, output, timeout, prepare=prepare, verify=verify, metadata={
                'kind': 'pdf_pt_reset_fresh_diagnostic', 'resolution': [width, height],
                'requested_frame_plan': plan, 'runtime_verification': receipt,
                'scene_config_sha256': config_hash, 'experiment_config_sha256': experiment_hash,
                'source_sha256': hashes, 'render_script_sha256': hashlib.sha256(source).hexdigest(),
                'limitations': 'Verifier-only observe profile; diagnostic output is not a comparison campaign.'})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('config', 'output', 'runtime'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--seed-offset', type=int, default=0)
    parser.add_argument('--camera-cut', action='store_true')
    parser.add_argument('--timeout', type=int, default=1200)
    args = vars(parser.parse_args(argv))
    config = args.pop('config')
    print(launch(config, **args))


if __name__ == '__main__':
    main()
