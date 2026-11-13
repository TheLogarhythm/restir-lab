"""Extend six frozen 8192-spp Falcor references to 16384 spp.

Each scene is loaded once per attempt; completed blocks from failed attempts are
reused only after a full successful postflight; failed attempts remain untouched.
"""
import argparse
import json
import math
import re
from pathlib import Path

from . import reference_batch as common, reference_runner, reference_extension_runner as extension, run
from . import reference_extension_provenance as provenance
from src.image_io.reference_average_16 import average_sixteen_seed_exrs

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = common.EXPECTED_VIEWS
sha = common.sha


def within(root, relative):
    root = Path(root).resolve(strict=True)
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Path escapes root')
    return path


def validate_output(old_root, output):
    old_root=Path(old_root).resolve(strict=True);output=Path(output).resolve()
    if output==old_root or old_root.is_relative_to(output):
        raise ValueError('Output overlaps original data')
    if output.is_relative_to(old_root):
        if output.parent!=old_root or not re.fullmatch(r'reference-16384-[A-Za-z0-9][A-Za-z0-9._-]*',output.name):
            raise ValueError('Output overlaps original data')
    return output


def old_images(root, view):
    root = Path(root).resolve(strict=True)
    if view.get('seed_count') != 8 or view.get('spp_per_seed') != 1024 or view.get('resolution') != [1920,1080]:
        raise ValueError('Old view budget mismatch')
    reference = within(root,view['reference'])
    if not reference.is_file() or sha(reference) != view['reference_sha256']:
        raise ValueError('Old reference hash mismatch')
    images=[]
    if len(view['seeds'])!=8: raise ValueError('Eight old seeds required')
    for i,seed in enumerate(view['seeds']):
        if seed['index']!=i: raise ValueError('Old seed order mismatch')
        image=within(root,seed['path']);manifest=within(root,seed['manifest'])
        if not image.is_file() or not manifest.is_file() or sha(image)!=seed['sha256'] or sha(manifest)!=seed['manifest_sha256']:
            raise ValueError('Old seed or manifest hash mismatch')
        record=json.loads(manifest.read_text(encoding='utf-8-sig'))
        if (record.get('status')!='completed' or record.get('kind')!='reference_seed' or record.get('seed_index')!=i
            or record.get('samples_per_pixel')!=1024 or record.get('sample_seed_first')!=1024*i
            or record.get('sample_seed_last')!=1024*i+1023 or record.get('resolution')!=[1920,1080]):
            raise ValueError('Old seed metadata mismatch')
        matching=[x for x in record.get('artifacts',[]) if x.get('file')==image.name]
        if len(matching)!=1 or matching[0].get('sha256')!=seed['sha256']:
            raise ValueError('Old seed artifact hash mismatch')
        if any(image.samefile(prior) for prior in images):raise ValueError('Duplicate old seed')
        images.append(image)
    return images


def validate_block(attempt, index, config, adapted):
    attempt=Path(attempt).resolve(strict=True);d=attempt/f'block-{index+1:02d}'
    progress_path=d/'progress.json';camera_path=d/'camera.json';scene_state=attempt/'scene-state.json'
    progress=json.loads(progress_path.read_text(encoding='utf-8-sig'))
    seeds=extension.block_seed_range(index,1024)
    if progress.get('status')!='submitted' or (progress['block'],progress['samples'],progress['seed_first'],progress['seed_last'])!=(index,1024,seeds.start,seeds.stop-1):
        raise ValueError('Block progress mismatch')
    camera=json.loads(camera_path.read_text(encoding='utf-8-sig'))
    reference_runner.validate_camera_records(config['camera'],camera,1024)
    if 'near_plane' in config['camera'] and any(not math.isclose(float(camera[k]['nearPlane']),float(config['camera']['near_plane']),rel_tol=1e-6,abs_tol=1e-6) for k in ('initial','first_frame','last_frame')):
        raise ValueError('Camera near plane mismatch')
    state=json.loads(scene_state.read_text(encoding='utf-8-sig'))
    audit_path=attempt/'scene-audit.json'
    if adapted:
        audit=json.loads(audit_path.read_text(encoding='utf-8-sig'))
        if [x['material_count'] for x in audit['models']]!=config['expected_material_counts'] or [len(x['loaded_texture_slots']) for x in audit['models']]!=config['expected_texture_slots']:
            raise ValueError('Material audit mismatch')
        if len(state['lights'])!=config['expected_light_count'] or any(not x['active'] for x in state['lights']):raise ValueError('Active light mismatch')
        if state['environment_present']!=config['expected_environment_present'] or not all(state[k] for k in ('useAnalyticLights','useEnvLight','useEmissiveLights')):raise ValueError('Scene light mismatch')
    files=list(d.glob('capture.AccumulatePass.output.*.exr'))
    if len(files)!=1: raise ValueError('Expected one completed block image')
    run.inspect_hdr(files[0],1920,1080)
    expected={'camera_sha256':sha(camera_path),'scene_state_sha256':sha(scene_state),'scene_audit_sha256':sha(audit_path) if adapted else None}
    if any(progress.get(k)!=v for k,v in expected.items()):raise ValueError('Block persisted hash mismatch')
    return {'block':index,'file':files[0].relative_to(attempt).as_posix(),'sha256':sha(files[0]),
            'samples':1024,'seed_first':seeds.start,'seed_last':seeds.stop-1,
            'camera_sha256':sha(camera_path),'progress_sha256':sha(progress_path),
            'scene_state_sha256':sha(scene_state),'scene_audit_sha256':sha(audit_path) if adapted else None}


def code_identity():
    from . import adapted_reference_runner
    names=[Path(__file__),Path(extension.__file__),Path(reference_runner.__file__),
           Path(adapted_reference_runner.__file__),Path(provenance.__file__),
           ROOT/'src/image_io/reference_average_16.py',ROOT/'src/image_io/exr.py',
           ROOT/'scripts/falcor/reference_graph.py',ROOT/'scripts/falcor/run.py',
           ROOT/'scripts/falcor/project_paths.py',
           ROOT/'scripts/falcor/process_utils.py',ROOT/'scripts/falcor/build.py',
           ROOT/'scripts/falcor/reference_runtime.py',ROOT/'scripts/falcor/prepare_gltf_composite_runtime_v3.py']
    return {p.relative_to(ROOT).as_posix():sha(p) for p in names}


def verify_runtimes():
    from . import reference_runtime, prepare_gltf_composite_runtime_v3 as gltf_runtime
    from .process_utils import check_renderer_idle, exclusive_operation
    with exclusive_operation(ROOT/'build/falcor/.operation.lock'):
        check_renderer_idle()
        reference_runtime.verify()
        gltf_runtime.quarantine_transients()
        gltf_runtime.verify()


def recheck_view(entry, config):
    from . import adapted_reference_runner

    path = Path(entry["config_path"])
    if "input_sha256" in entry:
        from .scene_inputs import load_view

        expanded, inputs = load_view(path, ROOT)
        if inputs != entry["input_sha256"] or expanded != config:
            raise ValueError("Reusable scene inputs or expanded config changed")
    if (
        sha(path) != entry["config_sha256"]
        or sha(ROOT / "scripts/falcor/reference_graph.py") != entry["graph_sha256"]
    ):
        raise ValueError("View config or graph changed")
    receipt = ROOT / (
        "build/falcor-gltf-composite-runtime-v3/receipt.json"
        if entry["adapted"]
        else "build/falcor-reference-runtime/receipt.json"
    )
    if sha(receipt) != entry["runtime_receipt_sha256"]:
        raise ValueError("View runtime receipt changed")
    if entry["adapted"]:
        assets = adapted_reference_runner.inventory_resources(config["resources"], ROOT)
        sources = adapted_reference_runner.inventory_resources(config["sources"], ROOT)
    else:
        assets = reference_runner.asset_inventory(config)
        sources = {}
    if assets != entry["asset_sha256"] or sources != entry["source_sha256"]:
        raise ValueError("View inputs changed")


def attempt_record(attempt, config, baseline, identity):
    manifest=attempt/'manifest.json'
    if not manifest.is_file():return None
    m=json.loads(manifest.read_text(encoding='utf-8-sig'))
    # FrameCapture writes asynchronously; only a normal, fully verified
    # host postflight can certify any images from an attempt.
    if m.get('status') != 'completed':return m, []
    if m.get('kind')!='reference_extension' or m.get('scene_config')!=config:
        raise ValueError('Extension attempt config mismatch')
    if (m.get('config_sha256')!=baseline['config_sha256'] or m.get('samples_per_block')!=1024
        or m.get('resolution')!=[1920,1080] or m.get('asset_sha256')!=baseline['asset_sha256']
        or m.get('source_sha256')!=baseline['source_sha256'] or m.get('graph_sha256')!=baseline['graph_sha256']
        or m.get('runtime_receipt_sha256')!=baseline['runtime_receipt_sha256']
        or m.get('runner_sha256')!=identity['scripts/falcor/reference_extension_runner.py']):
        raise ValueError('Extension attempt provenance mismatch')
    expected_deps={k:v for k,v in identity.items() if k in ('scripts/falcor/reference_runner.py','scripts/falcor/adapted_reference_runner.py')}
    if m.get('dependency_sha256')!=expected_deps:raise ValueError('Extension dependency provenance mismatch')
    blocks=m.get('blocks')
    if not isinstance(blocks,list) or not blocks or len(set(blocks))!=len(blocks) or any(type(i) is not int or not 0<=i<8 for i in blocks):raise ValueError('Invalid block list')
    if blocks!=list(range(8)):raise ValueError('Completed attempt must cover all eight blocks')
    recovered=[]
    for index in blocks:
        a=validate_block(attempt,index,config,baseline['adapted'])
        if m.get('status')=='completed':
            rows=[row for row in m.get('artifacts',[]) if row.get('block')==index]
            if len(rows)!=1 or any(rows[0].get(k)!=v for k,v in a.items()):
                raise ValueError('Completed block artifact hash mismatch')
        recovered.append(a)
    return m,recovered


def find_blocks(view_dir, config, baseline, identity):
    attempts=view_dir/'attempts';found={}
    if not attempts.exists():return found
    for attempt in sorted(attempts.iterdir()):
        if not attempt.is_dir() or not re.fullmatch(r'attempt-[0-9]{2,}',attempt.name):raise ValueError('Unexpected attempt directory')
        checked=attempt_record(attempt,config,baseline,identity)
        if checked is None:continue
        m,artifacts=checked
        for item in artifacts:
            i=item['block']
            if i in found:raise ValueError('Multiple completed copies of block')
            found[i]=(attempt,item,m)
    return found


def next_attempt(view_dir):
    path=view_dir/'attempts';path.mkdir(parents=True,exist_ok=True);ids=[]
    for item in path.iterdir():
        match=re.fullmatch(r'attempt-([0-9]{2,})',item.name)
        if not match or not item.is_dir():raise ValueError('Unexpected attempt directory')
        ids.append(int(match.group(1)))
    return path/f'attempt-{max(ids,default=0)+1:02d}'


def run_batch(old_root, config_paths, output, *, timeout=7200, resume=False):
    from .process_utils import exclusive_operation
    with exclusive_operation(common.BATCH_LOCK):
        return _run_batch(old_root,config_paths,output,timeout=timeout,resume=resume)


def _run_batch(old_root,config_paths,output,*,timeout=7200,resume=False):
    if not math.isfinite(timeout) or timeout<=0:raise ValueError('Invalid timeout')
    old_root=Path(old_root).resolve(strict=True);output=validate_output(old_root,output)
    # Full GPU-idle runtime verification and direct re-computation of old provenance
    # happen before writing status or launching any rendering.
    verify_runtimes()
    baseline=provenance.verify_baseline(old_root,config_paths)
    baseline_views=baseline['views'];keys={(v['scene_id'],v['view_id']) for v in baseline_views}
    if keys!=EXPECTED or len(baseline_views)!=6:raise ValueError('Baseline must contain six unique views')
    identity=code_identity();old_index=json.loads((old_root/'manifest.json').read_text(encoding='utf-8-sig'))
    old_views={(v['scene_id'],v['view_id']):v for v in old_index['views']}
    if set(old_views)!=EXPECTED or len(old_index['views'])!=6:raise ValueError('Old index does not contain six unique views')
    source_sha=sha(old_root/'manifest.json');status_path=output/'manifest.json'
    if resume:
        status=json.loads(status_path.read_text(encoding='utf-8'))
        if status.get('status')=='completed':raise ValueError('Extension already completed')
        version=status.get('schema_version')
        if version not in (1,2) or (version==2 and status.get('path_base')!='workspace'):
            raise ValueError('Invalid extension path format')
        expected_baseline=baseline if version==1 else provenance.portable_baseline(baseline,ROOT)
        expected_old_root=str(old_root) if version==1 else expected_baseline['old_root']
        if status.get('old_root')!=expected_old_root or status.get('old_manifest_sha256')!=source_sha or status.get('code_sha256')!=identity:
            raise ValueError('Extension source or code provenance changed')
        saved=json.loads((output/'baseline.json').read_text(encoding='utf-8'))
        if saved!=expected_baseline or sha(output/'baseline.json')!=status.get('baseline_sha256'):
            raise ValueError('Extension baseline provenance changed')
        status.setdefault('resume_history',[]).append({'status':status.get('status'),'error':status.get('error'),'resumed_utc':common.now()})
        status['status']='running';status.pop('error',None)
    else:
        output.mkdir(parents=True,exist_ok=False)
        baseline_path=output/'baseline.json'
        saved_baseline=provenance.portable_baseline(baseline,ROOT)
        with baseline_path.open('x',encoding='utf-8',newline='\n') as f:json.dump(saved_baseline,f,indent=2,allow_nan=False);f.write('\n')
        status={'schema_version':2,'path_base':'workspace','kind':'falcor_reference_extension_16384','status':'running','started_utc':common.now(),
                'old_root':saved_baseline['old_root'],'old_manifest_sha256':source_sha,'baseline_sha256':sha(baseline_path),
                'code_sha256':identity,'budget':{'old_seeds':8,'new_seeds':8,'spp_per_seed':1024,'resolution':[1920,1080]},'views':[]}
    common.save_status(status_path,status)
    try:
        # Verify every previously recorded block before beginning new GPU work.
        jobs=[]
        for entry in baseline_views:
            key=(entry['scene_id'],entry['view_id']);oldview=old_views[key];old=old_images(old_root,oldview)
            cfgpath=Path(entry['config_path']).resolve(strict=True);config=json.loads(cfgpath.read_text(encoding='utf-8-sig'))
            if sha(cfgpath)!=entry['config_sha256'] or (config['scene_id'],config['view_id'])!=key:raise ValueError('Frozen config mismatch')
            view_dir=output/key[0]/key[1];view_dir.mkdir(parents=True,exist_ok=True)
            matches=[v for v in status['views'] if (v['scene_id'],v['view_id'])==key]
            if len(matches)>1:raise ValueError('Duplicate view status')
            view=matches[0] if matches else {'scene_id':key[0],'view_id':key[1],'status':'pending','blocks':[]}
            if not matches:status['views'].append(view)
            found=find_blocks(view_dir,config,entry,identity)
            previous={x['block']:x for x in view.get('blocks',[])}
            if len(previous)!=len(view.get('blocks',[])):raise ValueError('Duplicate recorded block')
            for i,item in previous.items():
                if i not in found:raise ValueError('Previously completed block missing')
                attempt,artifact,_=found[i]
                if (item['attempt']!=str(attempt.relative_to(output)) or item['attempt_manifest_sha256']!=sha(attempt/'manifest.json')
                    or any(item.get(k)!=artifact.get(k) for k in ('file','sha256','camera_sha256','progress_sha256','scene_state_sha256','scene_audit_sha256'))):
                    raise ValueError('Previously recorded block provenance mismatch')
            if view['status']=='completed':
                if len(found)!=8:raise ValueError('Completed view missing block')
                ref=within(output,view['reference'])
                if not ref.is_file() or sha(ref)!=view['reference_sha256']:raise ValueError('Completed reference changed')
            jobs.append((entry,config,cfgpath,view_dir,view,old,found))
        common.save_status(status_path,status)
        for entry,config,cfgpath,view_dir,view,old,found in jobs:
            if view['status']=='completed':continue
            if code_identity()!=identity:raise ValueError('Extension source changed')
            recheck_view(entry,config)
            missing=[i for i in range(8) if i not in found]
            if missing:
                attempt=next_attempt(view_dir);view['status']='running';common.save_status(status_path,status)
                print(f"Rendering {entry['scene_id']}/{entry['view_id']}: blocks {missing}",flush=True)
                extension.launch(cfgpath,attempt,missing,1024,1920,1080,timeout,adapted=entry['adapted'])
                found=find_blocks(view_dir,config,entry,identity)
            if set(found)!=set(range(8)):raise ValueError('Not all eight extension blocks completed')
            items=[];images=[]
            for i in range(8):
                attempt,a,record=found[i];images.append(attempt/a['file']);items.append({'block':i,'attempt':str(attempt.relative_to(output)),'attempt_manifest_sha256':sha(attempt/'manifest.json'),'postflight':'host_completed','file':a['file'],'sha256':a['sha256'],'camera_sha256':a['camera_sha256'],'progress_sha256':a['progress_sha256'],'scene_state_sha256':a['scene_state_sha256'],'scene_audit_sha256':a['scene_audit_sha256']})
            view['blocks']=items;common.save_status(status_path,status)
            dest=view_dir/'reference-16384.exr'
            if dest.exists():
                n=2
                while (view_dir/f'reference-16384-attempt-{n:02d}.exr').exists():n+=1
                dest=view_dir/f'reference-16384-attempt-{n:02d}.exr'
            # Recheck inputs and verified blocks on both sides of averaging.
            verify_runtimes();recheck_view(entry,config)
            if old_images(old_root,old_views[(entry['scene_id'],entry['view_id'])])!=old:raise ValueError('Old images changed')
            before=find_blocks(view_dir,config,entry,identity)
            if any(before[i][1]!=found[i][1] for i in range(8)):raise ValueError('Blocks changed before averaging')
            average_sixteen_seed_exrs(old+images,dest)
            verify_runtimes();recheck_view(entry,config)
            if old_images(old_root,old_views[(entry['scene_id'],entry['view_id'])])!=old:raise ValueError('Old images changed')
            after=find_blocks(view_dir,config,entry,identity)
            if any(after[i][1]!=found[i][1] for i in range(8)):raise ValueError('Blocks changed during averaging')
            if code_identity()!=identity:raise ValueError('Extension source changed')
            view.update(status='completed',reference=str(dest.relative_to(output)),reference_sha256=sha(dest),completed_utc=common.now())
            common.save_status(status_path,status)
        status.update(status='completed',completed_utc=common.now());status.pop('error',None)
    except BaseException as exc:
        for view in status['views']:
            if view.get('status')=='running':view['status']='failed'
        status.update(status='failed',error=str(exc),ended_utc=common.now());common.save_status(status_path,status);raise
    common.save_status(status_path,status);return status_path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-root',type=Path,required=True)
    parser.add_argument('--configs',type=Path,nargs=6,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--timeout',type=float,default=7200)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();print(run_batch(args.old_root,args.configs,args.output,timeout=args.timeout,resume=args.resume))


if __name__=='__main__':main()
