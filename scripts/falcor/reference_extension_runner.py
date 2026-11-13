"""Append nonoverlapping samples in scene-resident, restartable chunks."""
from pathlib import Path
import json, math, os, subprocess, time
from . import reference_runner, adapted_reference_runner, run
from .process_utils import check_renderer_idle, exclusive_operation
ROOT=Path(__file__).resolve().parents[2]


def block_seed_range(index,count):
    if type(index) is not int or not 0<=index<8: raise ValueError('block index must be 0..7')
    if type(count) is not int or not 1<=count<=1024: raise ValueError('block count must be 1..1024')
    first=8192+index*1024
    return range(first,first+count)


def render_script(scene,camera,output,blocks,count,*,adapted=False,portable=False):
    if not isinstance(blocks,(list,tuple)) or not blocks or len(set(blocks))!=len(blocks): raise ValueError('Blocks must be nonempty and unique')
    for index in blocks: block_seed_range(index,count)
    scene=Path(scene); output=Path(output)
    script=reference_runner.render_script(scene,camera,output,0,count,portable=portable)
    if portable:scene,output=reference_runner.portable_render_paths(scene,output)
    if adapted:
        script=script.replace('from falcor import float3','from falcor import float3, SceneBuilderFlags',1)
        original='m.loadScene('+repr(str(scene))+')'
        if script.count(original)!=1:raise ValueError('Reference scene interface changed')
        script=script.replace(original,original[:-1]+', SceneBuilderFlags.DontOptimizeMaterials)',1)
    if 'near_plane' in camera:
        value=float(camera['near_plane'])
        if not math.isfinite(value) or value<=0:raise ValueError('Invalid camera near plane')
        script=script.replace('camera.apertureRadius = 0','camera.apertureRadius = 0\ncamera.nearPlane = '+repr(value),1)
    load_line=next(line for line in script.splitlines() if line.startswith('m.loadScene('))
    script=script.replace(load_line, 'import time\n_scene_load_started=time.perf_counter()\n'+load_line+'\n_scene_load_seconds=time.perf_counter()-_scene_load_started',1)
    anchor='camera_records = {\'initial\': camera_state()}'
    if script.count(anchor)!=1:raise ValueError('Reference render loop interface changed')
    script=script[:script.index(anchor)]
    block_output='str(block_dir.resolve())' if portable else 'str(block_dir)'
    return script+f'''import time, hashlib, os
def digest_file(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()
def atomic_json(path, value):
    temporary=path.with_name(path.name+'.tmp')
    with temporary.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2,allow_nan=False);stream.flush();os.fsync(stream.fileno())
    os.replace(str(temporary),str(path))
tracer = g['PathTracer']
tracer.useFixedSeed = True
for block in {list(blocks)!r}:
    block_dir = Path({str(output)!r}) / ('block-{{:02d}}'.format(block+1))
    m.frameCapture.outputDir = {block_output}
    g['AccumulatePass'].reset()
    camera_records = {{'initial': camera_state()}}
    block_started = time.perf_counter()
    for sample in range({count}):
        tracer.fixedSeed = 8192 + block * 1024 + sample
        m.clock.frame = sample + 1
        m.renderFrame()
        if sample == 0:
            if block == {list(blocks)!r}[0]:
                settings=m.scene.renderSettings
                state={{'lights':[{{'name':l.name,'active':l.active,'intensity':[l.intensity.x,l.intensity.y,l.intensity.z]}} for l in m.scene.lights], 'environment_present':m.scene.envMap is not None,'useAnalyticLights':settings.useAnalyticLights,'useEnvLight':settings.useEnvLight,'useEmissiveLights':settings.useEmissiveLights,'stats':m.scene.stats}}
                Path({str(output / 'scene-state.json')!r}).write_text(json.dumps(state,indent=2),encoding='utf-8')
            camera_records['first_frame'] = {{**camera_state(), 'frame': sample + 1}}
        if sample == {count}-1:
            camera_records['last_frame'] = {{**camera_state(), 'frame': sample + 1}}
    render_wall=time.perf_counter()-block_started
    capture_started=time.perf_counter()
    m.frameCapture.capture()
    capture_wall=time.perf_counter()-capture_started
    atomic_json(block_dir/'camera.json',camera_records)
    state_path=Path({str(output / 'scene-state.json')!r})
    audit_path=Path({str(output / 'scene-audit.json')!r})
    progress={{'status':'submitted','block':block,'seed_first':8192+block*1024,'seed_last':8192+block*1024+{count}-1,'samples':{count},'camera_sha256':digest_file(block_dir/'camera.json'),'scene_state_sha256':digest_file(state_path),'scene_audit_sha256':digest_file(audit_path) if audit_path.is_file() else None,'wall_seconds_submit_capture':time.perf_counter()-block_started,'render_frame_calls_seconds':render_wall,'capture_call_seconds':capture_wall,'scene_load_seconds':_scene_load_seconds}}
    atomic_json(block_dir/'progress.json',progress)
exit()
'''


def launch(config_path,output,blocks,count=1024,width=1920,height=1080,timeout=7200,*,adapted=False,scout=False):
    from . import build, reference_runtime, prepare_gltf_composite_runtime_v3 as gltf_runtime
    preflight_started=time.perf_counter()
    cfgpath=Path(config_path).resolve(strict=True);config=json.loads(cfgpath.read_text(encoding='utf-8-sig'));output=Path(output).resolve()
    if os.environ.get('FALCOR_DEVMODE')=='1':raise RuntimeError('FALCOR_DEVMODE overrides isolated runtime')
    reference_runner.validate_render_budget(count,width,height,scout=scout)
    if not math.isfinite(timeout) or timeout<=0:raise ValueError('Invalid timeout')
    scene=(ROOT/config['scene_source']).resolve(strict=True)
    if not scene.is_relative_to(ROOT):raise ValueError('Scene outside repository')
    script=render_script(scene,config['camera'],output,blocks,count,adapted=adapted,portable=True)
    graph=Path(__file__).with_name('reference_graph.py');runtime=gltf_runtime if adapted else reference_runtime
    with exclusive_operation(ROOT/'build/falcor/.operation.lock'):
        check_renderer_idle();built=build.verify_build()
        if adapted:runtime.quarantine_transients()
        receipt=runtime.verify();receipt_path=runtime.DEST/'receipt.json'
        receipt_hash=run.sha(receipt_path)
        if adapted:
            if receipt_hash!=config['runtime_receipt_sha256']:raise ValueError('Runtime differs from frozen config')
            assets=adapted_reference_runner.inventory_resources(config['resources'],ROOT)
            sources=adapted_reference_runner.inventory_resources(config['sources'],ROOT)
        else:
            assets=reference_runner.asset_inventory(config);sources={}
        dependency_sha256={str(Path(mod.__file__).relative_to(ROOT)).replace('\\','/'):run.sha(Path(mod.__file__)) for mod in (reference_runner,adapted_reference_runner)}
        gpu=subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version','--format=csv,noheader'],text=True).strip()
        executable=runtime.DEST/'runtime'/Path(built['executable']).name
        meta={'kind':'reference_extension_scout' if scout else 'reference_extension','scene_config':config,'config_sha256':run.sha(cfgpath),'blocks':list(blocks),'samples_per_block':count,'resolution':[width,height], 'asset_sha256':assets,'source_sha256':sources,'runtime_receipt_sha256':receipt_hash,'graph_sha256':run.sha(graph),'runner_sha256':run.sha(Path(__file__)),'build_commit':built['commit'],'gpu_driver':gpu,'preflight_seconds':time.perf_counter()-preflight_started,'dependency_sha256':dependency_sha256}
        command=[str(executable),'--device-type','d3d12','--width',str(width),'--height',str(height),'--script',str(output/'render.py'),'--headless']
        meta.update(reference_runner.portable_command(command))
        def prepare(out):
            (out/'reference_graph.py').write_bytes(graph.read_bytes());(out/'render.py').write_text(script,encoding='utf8');run.save(out/'config.json',config)
            for index in blocks:(out/f'block-{index+1:02d}').mkdir()
        def verify(out):
            artifacts=[]
            state_path=out/'scene-state.json'
            scene_state=json.loads(state_path.read_text(encoding='utf8'))
            audit_path=out/'scene-audit.json'
            if adapted:
                audit=json.loads(audit_path.read_text(encoding='utf8'))
                if [x['material_count'] for x in audit['models']]!=config['expected_material_counts'] or [len(x['loaded_texture_slots']) for x in audit['models']]!=config['expected_texture_slots']:raise ValueError('Material audit differs from scene plan')
                if len(scene_state['lights'])!=config['expected_light_count'] or any(not x['active'] for x in scene_state['lights']):raise ValueError('Scene active light count differs')
                if scene_state['environment_present']!=config['expected_environment_present'] or not all(scene_state[k] for k in ('useAnalyticLights','useEnvLight','useEmissiveLights')):raise ValueError('Scene light settings differ')
            for index in blocks:
                d=out/f'block-{index+1:02d}';state=json.loads((d/'progress.json').read_text(encoding='utf8'));seeds=block_seed_range(index,count)
                if (state.get('status'),state['block'],state['samples'],state['seed_first'],state['seed_last'])!=('submitted',index,count,seeds.start,seeds.stop-1):raise ValueError('Block progress mismatch')
                records=json.loads((d/'camera.json').read_text(encoding='utf8'));reference_runner.validate_camera_records(config['camera'],records,count)
                if 'near_plane' in config['camera'] and any(not math.isclose(float(records[k]['nearPlane']),float(config['camera']['near_plane']),rel_tol=1e-6,abs_tol=1e-6) for k in ('initial','first_frame','last_frame')):raise ValueError('Camera near plane mismatch')
                paths=list(d.glob('capture.AccumulatePass.output.*.exr'))
                if len(paths)!=1:raise ValueError('Expected one EXR per block')
                run.inspect_hdr(paths[0],width,height)
                if state['camera_sha256']!=run.sha(d/'camera.json') or state['scene_state_sha256']!=run.sha(state_path) or state['scene_audit_sha256']!=(run.sha(audit_path) if adapted else None):raise ValueError('Block receipt hash mismatch')
                artifacts.append({'file':paths[0].relative_to(out).as_posix(),'sha256':run.sha(paths[0]),'block':index,'samples':count,'seed_first':seeds.start,'seed_last':seeds.stop-1,'camera_sha256':run.sha(d/'camera.json'),'progress_sha256':run.sha(d/'progress.json'),'scene_state_sha256':run.sha(state_path),'scene_audit_sha256':run.sha(audit_path) if adapted else None})
            if adapted:
                audit_hash=adapted_reference_runner.finalize_portable_audit(audit_path,ROOT,[out/f'block-{i+1:02d}'/'progress.json' for i in blocks])
                for artifact in artifacts:
                    artifact['scene_audit_sha256']=audit_hash
                    artifact['progress_sha256']=run.sha(out/f"block-{artifact['block']+1:02d}"/'progress.json')
            if any(run.sha(ROOT/path)!=digest for path,digest in dependency_sha256.items()):raise ValueError('Runner dependency changed')
            if adapted:
                if adapted_reference_runner.inventory_resources(config['resources'],ROOT)!=assets or adapted_reference_runner.inventory_resources(config['sources'],ROOT)!=sources:raise ValueError('Scene inputs changed')
                runtime.quarantine_transients()
            elif reference_runner.asset_inventory(config)!=assets:raise ValueError('Scene inputs changed')
            runtime.verify()
            return artifacts
        with adapted_reference_runner.isolated_python_environment():return run.execute(command,output,timeout,prepare=prepare,verify=verify,metadata=meta)
