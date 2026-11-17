"""Bounded, verifier-only continuous-camera PDF and native lighting history check.

Uses an already prepared private observe runtime. Default 96x64, 28 frames:
8 static warmup, 12 small lateral moves, 4 stopped frames, explicit cut/reset
and fresh direction-state oracle, then graph replacement and fresh full-state
oracle. Captures finite raw FLOAT32 AOVs on every frame. This is a diagnostic,
not a comparison campaign or an unbiasedness/temporal quality measurement.
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
from . import spatial_experiment_config as settings, pdf_pt_reset_check as reset_check
from .adapted_reference_runner import isolated_python_environment
from .process_utils import check_renderer_idle, exclusive_operation
from scripts.analysis.relative_paths import relative_to_document

ROOT = Path(__file__).resolve().parents[2]


def frame_plan(seed_offset=0, *, motion_step=.004):
    if type(seed_offset) is not int or not 0 <= seed_offset <= 2**32 - 1 - 25:
        raise ValueError('Diagnostic seeds exceed uint32')
    if type(motion_step) not in (int, float) or not math.isfinite(motion_step) or not 0 < motion_step <= .05:
        raise ValueError('Diagnostic motion step must be in (0, .05] scene units')
    plan = []

    def step(phase, seed, offset, graph='motion-history', reset=False, replace=False):
        frame = len(plan) + 1
        plan.append({'clock_frame': frame, 'graph': graph, 'path_seed': seed,
                     'phase': phase, 'offset': offset, 'reset': reset, 'replace': replace,
                     'capture': f'frame-{frame:03d}'})

    for index in range(8):
        step('warmup', seed_offset + index, 0.)
    for index in range(12):
        step('motion', seed_offset + 8 + index, motion_step * (index + 1))
    end = motion_step * 12
    for index in range(4):
        step('stop', seed_offset + 20 + index, end)
    step('cut-reset', seed_offset + 24, end + 1., reset=True)
    step('fresh-cut', seed_offset + 24, end + 1., graph='fresh-cut')
    step('replacement', seed_offset + 25, end + 1., replace=True)
    step('fresh-replacement', seed_offset + 25, end + 1., graph='fresh-replacement')
    return plan


def camera_poses(camera, plan):
    base = deepcopy(camera)
    base['target'] = reference_runner.camera_target(camera)
    right = np.cross(np.asarray(camera['direction'], dtype=float), np.asarray(camera['up'], dtype=float))
    right /= np.linalg.norm(right)
    poses = []
    for event in plan:
        pose = deepcopy(base)
        for key in ('position', 'target'):
            pose[key] = (np.asarray(base[key], dtype=float) + right * event['offset']).tolist()
        poses.append(pose)
    return poses


def render_script(scene, camera, plan, *, adapted=False, experiment=None):
    options = capture.graph_options('pdf-similarity', experiment, temporal_reuse=True)
    poses = camera_poses(camera, plan)
    focal = 12.0 / math.tan(math.radians(camera['vertical_fov']) / 2)
    scene_import = ', SceneBuilderFlags' if adapted else ''
    flags = ', SceneBuilderFlags.DontOptimizeMaterials' if adapted else ''
    return f'''import json, contextlib, time
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

graphs, graph_frames = {{}}, {{}}
m.loadScene({str(scene)!r}{flags})
m.scene.animated = False
camera = m.scene.camera
camera.animated = False
camera.frameHeight = 24
camera.focalLength = {focal!r}
camera.apertureRadius = 0
m.clock.framerate = 0
m.clock.pause()
m.clock.time = 0
m.frameCapture.outputDir = str(Path('.').resolve())
m.frameCapture.captureAllOutputs = False
records = []
for event, pose in zip({plan!r}, {poses!r}):
    if event['replace']:
        m.removeGraph(graphs.pop(event['graph']))
        graph_frames.pop(event['graph'])
    if event['graph'] not in graphs:
        graphs[event['graph']] = make_graph(event['graph'])
        graph_frames[event['graph']] = 0
    graph = graphs[event['graph']]
    graph_created = graph_frames[event['graph']] == 0
    m.setActiveGraph(graph)
    camera.position = float3(*pose['position'])
    camera.target = float3(*pose['target'])
    camera.up = float3(*pose['up'])
    if 'near_plane' in pose: camera.nearPlane = pose['near_plane']
    tracer = graph['PathTracer']
    tracer.useFixedSeed = True
    if event['reset']: tracer.reset()
    previous_fixed_seed = int(tracer.fixedSeed)
    tracer.fixedSeed = event['path_seed']
    m.clock.frame = event['clock_frame']
    started = time.perf_counter()
    m.renderFrame()
    elapsed = time.perf_counter() - started
    graph_frames[event['graph']] += 1
    if m.clock.framerate != 0 or abs(m.clock.time) > 1e-9:
        raise RuntimeError('Diagnostic clock drift')
    records.append({{**event, 'actual_fixed_seed': int(tracer.fixedSeed),
                    'fixed_seed_before_assignment': previous_fixed_seed,
                    'graph_created': graph_created, 'renders_on_graph': graph_frames[event['graph']],
                    'actual_clock_frame': int(m.clock.frame), 'render_wall_seconds': elapsed,
                    'camera': {{'position': [camera.position.x, camera.position.y, camera.position.z],
                               'target': [camera.target.x, camera.target.y, camera.target.z],
                               'up': [camera.up.x, camera.up.y, camera.up.z]}}}})
    m.frameCapture.baseFilename = event['capture']
    m.frameCapture.capture()
for name, graph in graphs.items():
    with Path('resolved-' + name + '.py').open('w', encoding='utf8') as stream, contextlib.redirect_stdout(stream):
        graph.print()
Path('executed-frames.json').write_text(json.dumps(records, indent=2), encoding='utf8')
exit()
'''


def _verify_execution(executed, plan, camera):
    if len(executed) != len(plan):
        raise ValueError('Diagnostic execution frame count differs')
    seeds, frames = {}, {}
    for actual, expected, pose in zip(executed, plan, camera_poses(camera, plan)):
        if (any(actual.get(key) != value for key, value in expected.items())
                or actual.get('actual_fixed_seed') != expected['path_seed']
                or actual.get('actual_clock_frame') != expected['clock_frame']):
            raise ValueError('Executed diagnostic graph, clock frame or fixed seed differs')
        name = expected['graph']
        created = expected['replace'] or name not in seeds
        if created:
            seeds[name], frames[name] = None, 0
        if (actual.get('graph_created') is not created or actual.get('renders_on_graph') != frames[name] + 1
                or (not created and actual.get('fixed_seed_before_assignment') != seeds[name])):
            raise ValueError('Diagnostic graph lifetime or previous seed differs')
        seeds[name], frames[name] = expected['path_seed'], frames[name] + 1
        for key in ('position', 'target', 'up'):
            value = np.asarray(actual.get('camera', {}).get(key, []), dtype=float)
            if value.shape != (3,) or not np.isfinite(value).all() or not np.allclose(value, pose[key], rtol=1e-6, atol=2e-6):
                raise ValueError('Actual diagnostic camera differs from requested trajectory')
        elapsed = actual.get('render_wall_seconds')
        if type(elapsed) not in (float, int) or not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError('Invalid diagnostic render wall time')
    # Compare actual readbacks as well as requested poses: movement must survive float conversion.
    for index, event in enumerate(plan):
        if event['phase'] == 'motion':
            if executed[index]['camera'] == executed[index - 1]['camera']:
                raise ValueError('Requested continuous motion did not move the actual camera')
        elif event['phase'] == 'stop' and executed[index]['camera'] != executed[index - 1]['camera']:
            raise ValueError('Stopped diagnostic camera moved')


def verify_results(output, plan, width, height, camera):
    output = Path(output)
    executed = json.loads((output / 'executed-frames.json').read_text(encoding='utf8'))
    _verify_execution(executed, plan, camera)
    artifacts, summaries, images = [], [], {}
    for event in plan:
        frame, label = event['clock_frame'], event['capture']
        aovs = {}
        for name in ('color', *(name.split('.')[-1] for name in capture.PDF_DIAGNOSTIC_OUTPUTS)):
            pattern = re.escape(f'{label}.PathTracer.{name}.{frame}') + r'(?:\.RGBA)?\.exr'
            matches = [path for path in output.glob(f'{label}.PathTracer.{name}.*.exr') if re.fullmatch(pattern, path.name)]
            if len(matches) != 1:
                raise ValueError('Missing or duplicate motion diagnostic capture: ' + label + '/' + name)
            path = matches[0]
            digest = run.sha(path)
            aovs[name] = run.inspect_hdr(path, width, height) if name == 'color' else reset_check._rgba(path, width, height)
            if run.sha(path) != digest:
                raise ValueError('Diagnostic capture changed during readback')
            artifacts.append({'frame': frame, 'phase': event['phase'], 'output': name, 'path': path.name, 'sha256': digest})
        emission, pair, moment = aovs['nrdEmission'], aovs['nrdSpecularRadianceHitDist'], aovs['nrdDiffuseRadianceHitDist']
        if np.any(emission < 0) or np.any(moment[..., 3] < 0) or np.any(pair < 0) or np.any(pair[..., 0] > 1):
            raise ValueError('Invalid reservoir, direction count, moment denominator or pair weight')
        active = pair[..., 1] > 0
        row = {'frame': frame, 'phase': event['phase'], 'max_count': float(emission[..., 3].max()),
               'history_pixels': int(np.count_nonzero(emission[..., 3] > 1)),
               'max_lighting_M': float(emission[..., 0].max()),
               'max_temporal_source_M': float(pair[..., 3].max()),
               'temporal_lighting_pixels': int(np.count_nonzero(pair[..., 3] > 1)),
               'active_pairs': int(np.count_nonzero(active)),
               'active_h_below_one_pixels': int(np.count_nonzero(active & (pair[..., 0] < 1))),
               'minimum_active_h': float(pair[..., 0][active].min()) if active.any() else None}
        if event['phase'] == 'motion' and (row['history_pixels'] == 0 or row['max_lighting_M'] <= 1
                or row['temporal_lighting_pixels'] == 0 or row['active_h_below_one_pixels'] == 0):
            raise ValueError('Motion lost direction/native temporal lighting history or active h<1')
        summaries.append(row)
        if event['phase'] in ('cut-reset', 'fresh-cut', 'replacement', 'fresh-replacement'):
            images[event['phase']] = aovs
    if {path.name for path in output.glob('*.exr')} != {row['path'] for row in artifacts}:
        raise ValueError('Unexpected motion diagnostic capture set')
    warm = [row for row in summaries if row['phase'] == 'warmup']
    if (warm[0]['max_count'] > 1 or warm[0]['max_temporal_source_M'] > 1
            or warm[-1]['max_count'] <= 1 or warm[-1]['max_temporal_source_M'] <= 1):
        raise ValueError('Static warmup did not establish direction and native lighting history')
    left, right = images['cut-reset'], images['fresh-cut']
    cut = reset_check.compare_statistics(left['nrdDiffuseRadianceHitDist'], left['nrdEmission'][..., 3],
                                         right['nrdDiffuseRadianceHitDist'], right['nrdEmission'][..., 3])
    left, right = images['replacement'], images['fresh-replacement']
    replacement = reset_check.compare_system_state(left['color'], left['nrdEmission'], right['color'], right['nrdEmission'])
    replacement['direction_statistics'] = reset_check.compare_statistics(
        left['nrdDiffuseRadianceHitDist'], left['nrdEmission'][..., 3],
        right['nrdDiffuseRadianceHitDist'], right['nrdEmission'][..., 3])
    for a, b in (('cut-reset', 'fresh-cut'), ('replacement', 'fresh-replacement')):
        one, two = [next(row for row in executed if row['phase'] == phase) for phase in (a, b)]
        if one['camera'] != two['camera'] or one['actual_fixed_seed'] != two['actual_fixed_seed']:
            raise ValueError('Reset/replacement and fresh cameras or seeds differ')
        if a == 'replacement' and one['fixed_seed_before_assignment'] != two['fixed_seed_before_assignment']:
            raise ValueError('New PathTracer native first-frame seeds differ')
    moving = [row for row in summaries if row['phase'] == 'motion']
    return {'status': 'passed', 'frames': summaries, 'artifacts': artifacts, 'cut_reset': cut,
            'replacement': replacement, 'motion': {'frames': len(moving),
                'minimum_h': min(row['minimum_active_h'] for row in moving),
                'minimum_max_count': min(row['max_count'] for row in moving),
                'minimum_max_temporal_source_M': min(row['max_temporal_source_M'] for row in moving)},
            'timing_boundary': 'CPU wall time around m.renderFrame; includes dispatch/compilation, excludes AOV capture, not GPU timing.',
            'limitations': 'One bounded trajectory and seed stream; no quality, convergence, unbiasedness or speed claim. Cut reset compares raw A/B/count; full-state reset oracle uses newly constructed graphs.'}


def launch(config_path, output, runtime, *, width=96, height=64, seed_offset=0, motion_step=.004,
           timeout=1200, experiment_path=settings.DEFAULT_CONFIG):
    plan = frame_plan(seed_offset, motion_step=motion_step)
    capture.validate_budget(width, height, 0, len(plan), scout=True)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise ValueError('Motion-check timeout must be in (0, 3600] seconds')
    output, runtime = Path(output).resolve(), Path(runtime).resolve(strict=True)
    if output.exists() or not output.is_relative_to((ROOT / 'runs').resolve()):
        raise ValueError('Motion-check output must be a new directory under runs')
    if os.environ.get('FALCOR_DEVMODE') == '1':
        raise RuntimeError('FALCOR_DEVMODE overrides isolated shaders')
    config_path, experiment_path = Path(config_path).resolve(strict=True), Path(experiment_path).resolve(strict=True)
    experiment, experiment_hash = settings.load_config_snapshot(experiment_path)
    config = views.load_config(config_path)
    entry = views.frozen_views()[(config['scene_id'], config['view_id'])]
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
        dependencies = {*capture.dependency_files('pdf-similarity'), Path(__file__).resolve(), Path(reset_check.__file__).resolve()}
        hashes = {path.relative_to(ROOT).as_posix(): run.sha(path) for path in dependencies}
        config_hash = run.sha(config_path)

        def prepare(directory):
            (directory / 'render.py').write_bytes(source)

        def verify(directory):
            result = verify_results(directory, plan, width, height, config['camera'])
            if (run.sha(config_path) != config_hash or run.sha(experiment_path) != experiment_hash
                    or (directory / 'render.py').read_bytes() != source
                    or any(run.sha(ROOT / name) != digest for name, digest in hashes.items())
                    or pdf_pt_runtime.verify_prepared(runtime, expected_parameters=parameters, profile='observe') != receipt):
                raise ValueError('Diagnostic inputs or runtime changed')
            reference_extension_batch.recheck_view(entry, config)
            run.save(directory / 'motion-summary.json', result)
            return result['artifacts']

        with isolated_python_environment():
            return run.execute(command, output, timeout, prepare=prepare, verify=verify, metadata={
                'kind': 'pdf_pt_continuous_camera_diagnostic', 'resolution': [width, height],
                'requested_frame_plan': plan, 'requested_camera_poses': camera_poses(config['camera'], plan),
                'runtime_verification': receipt, 'scene_config_sha256': config_hash,
                'experiment_config_sha256': experiment_hash, 'source_sha256': hashes,
                'render_script_sha256': hashlib.sha256(source).hexdigest(),
                'limitations': 'Verifier-only observe profile; bounded diagnostic, not a comparison campaign.'})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('config', 'output', 'runtime'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--width', type=int, default=96)
    parser.add_argument('--height', type=int, default=64)
    parser.add_argument('--seed-offset', type=int, default=0)
    parser.add_argument('--motion-step', type=float, default=.004)
    parser.add_argument('--timeout', type=int, default=1200)
    parser.add_argument('--experiment-path', type=Path, default=settings.DEFAULT_CONFIG)
    args = vars(parser.parse_args(argv))
    config = args.pop('config')
    print(launch(config, **args))


if __name__ == '__main__':
    main()
