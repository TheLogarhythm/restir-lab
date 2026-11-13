"""Render and resume adapted Falcor references with immutable seed attempts.

Each configuration is a qualified adapted_reference_runner config. All views
use exactly eight seeds of 1024 spp at 1920x1080. Failed attempts remain intact.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from . import adapted_reference_runner as runner
from . import reference_runner
from .process_utils import exclusive_operation

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from image_io.reference_average import average_seed_exrs

BATCH_LOCK = ROOT / 'build/falcor/.adapted-reference-batch.lock'
BUDGET = {'seeds': 8, 'samples_per_seed': 1024, 'resolution': [1920, 1080]}


def _time():
    return datetime.now(timezone.utc).isoformat()


def _save_status(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.status-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, allow_nan=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _pipeline_hashes():
    files = [Path(__file__), Path(runner.__file__), Path(reference_runner.__file__),
             ROOT/'scripts/falcor/reference_graph.py', ROOT/'scripts/falcor/run.py',
             ROOT/'scripts/falcor/scene_inputs.py',
             ROOT/'scripts/falcor/process_utils.py', ROOT/'scripts/falcor/build.py',
             ROOT/'scripts/falcor/prepare_gltf_composite_runtime_v3.py',
             ROOT/'src/image_io/reference_average.py', ROOT/'src/image_io/exr.py']
    return {str(p.relative_to(ROOT)).replace('\\', '/'): runner.file_sha256(p) for p in files}


def current_provenance(config):
    """Verify actual assets, build and isolated runtime before accepting old seeds."""
    from . import build, prepare_gltf_composite_runtime_v3 as runtime
    from .process_utils import check_renderer_idle
    with exclusive_operation(ROOT/'build/falcor/.operation.lock'):
        check_renderer_idle()
        runtime.quarantine_transients()
        built = build.verify_build()
        receipt = runtime.verify()
        receipt_hash = runner.file_sha256(runtime.DEST/'receipt.json')
    if receipt_hash != config['runtime_receipt_sha256']:
        raise ValueError('Runtime receipt differs from configuration')
    return {'asset_sha256': runner.inventory_resources(config['resources'], ROOT),
            'source_sha256': runner.inventory_resources(config['sources'], ROOT),
            'graph_sha256': runner.file_sha256(ROOT/'scripts/falcor/reference_graph.py'),
            'runner_sha256': runner.file_sha256(Path(runner.__file__)),
            'runtime_receipt_sha256': receipt_hash,
            'runtime_kind': receipt['kind'], 'build_commit': built['commit'],
            'gpu_driver': subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version',
                               '--format=csv,noheader'],text=True).strip()}


def _configs(paths):
    if not paths:
        raise ValueError("At least one view configuration is required")
    result = []
    for p in paths:
        p = Path(p).resolve(strict=True)
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        inputs = None
        if data.get("schema_version") == 2:
            from .scene_inputs import load_view

            data, inputs = load_view(p, ROOT, expected_adapted=True)
        reference_runner.validate_scene_qualification(data)
        scene, view = data.get("scene_id"), data.get("view_id")
        if not all(
            isinstance(x, str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", x)
            for x in (scene, view)
        ):
            raise ValueError("Invalid scene or view identifier")
        result.append(
            {
                "scene_id": scene,
                "view_id": view,
                "path": str(p),
                "sha256": runner.file_sha256(p),
                "config": data,
                **({"config_input_sha256": inputs} if inputs is not None else {}),
            }
        )
    keys = [(r["scene_id"], r["view_id"]) for r in result]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate view configuration")
    return sorted(result, key=lambda r: (r["scene_id"], r["view_id"]))


def _row_unchanged(row):
    if runner.file_sha256(row["path"]) != row["sha256"]:
        return False
    if "config_input_sha256" in row:
        from .scene_inputs import load_view

        try:
            config, inputs = load_view(row["path"], ROOT, expected_adapted=True)
            from .scene_inputs import verify_profile_inventory

            verify_profile_inventory(config, ROOT, adapted=True)
        except (OSError, ValueError):
            return False
        return config == row["config"] and inputs == row["config_input_sha256"]
    return True


def _validate_seed(attempt, seed, row, expected):
    manifest=attempt/'manifest.json'
    data=json.loads(manifest.read_text(encoding='utf-8'))
    if (data.get('status')!='completed' or data.get('kind')!='reference_seed'
        or data.get('seed_index')!=seed or data.get('samples_per_pixel')!=1024
        or data.get('sample_seed_first')!=seed*1024 or data.get('sample_seed_last')!=seed*1024+1023
        or data.get('resolution')!=[1920,1080] or data.get('scene_config')!=row['config']
        or data.get('config_sha256')!=row['sha256']):
        raise ValueError('Seed does not match formal configuration')
    if any(data.get(k)!=v for k,v in expected.items()):
        raise ValueError('Seed provenance differs from current inputs')
    if 'config_input_sha256' in row and data.get('config_input_sha256')!=row['config_input_sha256']:
        raise ValueError('Seed scene profile provenance differs')
    artifacts=data.get('artifacts')
    if not isinstance(artifacts,list) or not artifacts:
        raise ValueError('Seed must have EXR and audited artifacts')
    images=[]; names=set()
    for item in artifacts:
        if not isinstance(item,dict):raise ValueError('Invalid artifact record')
        name=item.get('file')
        if not isinstance(name,str) or Path(name).name!=name or name in names:
            raise ValueError('Unsafe or duplicate seed artifact path')
        names.add(name)
        artifact=(attempt/name).resolve(strict=True)
        if artifact.parent!=attempt.resolve() or runner.file_sha256(artifact)!=item.get('sha256'):
            raise ValueError('Seed output hash mismatch')
        if artifact.suffix.lower()=='.exr':images.append(artifact)
    if len(images)!=1:raise ValueError('Seed must have exactly one EXR artifact')
    if 'scene-audit.json' not in names:raise ValueError('Seed scene audit artifact is missing')
    return manifest,images[0]


def _existing(seed_root, seed, row, expected):
    if not seed_root.exists():return None
    found=[]
    for attempt in sorted(seed_root.iterdir()):
        if attempt.is_symlink() or not attempt.is_dir() or not re.fullmatch(r'attempt-[0-9]{2,}',attempt.name):
            raise ValueError('Unexpected seed attempt entry')
        manifest=attempt/'manifest.json'
        if not manifest.exists():continue
        data=json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('status')=='completed':found.append(_validate_seed(attempt,seed,row,expected))
        elif data.get('status') not in ('running','failed'):
            raise ValueError('Unexpected attempt status')
    if len(found)>1:raise ValueError('Multiple completed attempts for one seed')
    return found[0] if found else None


def _next_attempt(seed_root):
    seed_root.mkdir(parents=True,exist_ok=True)
    numbers=[]
    for p in seed_root.iterdir():
        match=re.fullmatch(r'attempt-([0-9]{2,})',p.name)
        if not match or p.is_symlink() or not p.is_dir():raise ValueError('Unexpected seed attempt entry')
        numbers.append(int(match.group(1)))
    return seed_root/f'attempt-{max(numbers,default=0)+1:02d}'


def _run_batch(paths, output, timeout, resume):
    rows=_configs(paths)
    if type(timeout) not in (float,int) or not math.isfinite(timeout) or timeout<=0:
        raise ValueError('Timeout must be positive and finite')
    output=Path(output).resolve();status_path=output/'manifest.json'
    configs=[{k:r[k] for k in ('scene_id','view_id','path','sha256','config_input_sha256') if k in r} for r in rows]
    pipeline=_pipeline_hashes()
    # Check current inputs before creating the result directory or resuming work.
    provenance={(r['scene_id'],r['view_id']):current_provenance(r['config']) for r in rows}
    if resume:
        status=json.loads(status_path.read_text(encoding='utf-8'))
        if status.get('status')=='completed':raise ValueError('Batch is already completed')
        if status.get('configurations')!=configs or status.get('budget')!=BUDGET or status.get('pipeline_sha256')!=pipeline:
            raise ValueError('Batch configuration or pipeline provenance changed')
        if set((v['scene_id'],v['view_id']) for v in status['views']) != set(provenance):
            raise ValueError('Batch view set changed')
    else:
        output.mkdir(parents=True,exist_ok=False)
        status={'schema_version':1,'status':'running','started_utc':_time(),
                'budget':BUDGET,'configurations':configs,'pipeline_sha256':pipeline,
                'views':[{'scene_id':r['scene_id'],'view_id':r['view_id'],
                          'provenance':provenance[(r['scene_id'],r['view_id'])],
                          'status':'pending','seeds':[]} for r in rows]}
        _save_status(status_path,status)
    views={(v['scene_id'],v['view_id']):v for v in status['views']}
    try:
        # Validate every historical view and seed before launching any work.
        ready={}
        for row in rows:
            key=(row['scene_id'],row['view_id']);view=views[key];expected=provenance[key]
            if view['provenance']!=expected:raise ValueError('View provenance changed')
            viewdir=output/key[0]/key[1]
            recorded={x['index']:x for x in view['seeds']}
            if len(recorded)!=len(view['seeds']) or any(i not in range(8) for i in recorded):
                raise ValueError('Invalid recorded seeds')
            for seed in range(8):
                previous=_existing(viewdir/'seeds'/f'seed-{seed+1:02d}',seed,row,expected)
                if seed in recorded:
                    if previous is None:raise ValueError('Previously completed seed is missing')
                    manifest,image=previous
                    if (str(manifest.relative_to(output))!=recorded[seed]['manifest'] or
                        runner.file_sha256(manifest)!=recorded[seed]['manifest_sha256'] or
                        runner.file_sha256(image)!=recorded[seed]['hdr_sha256']):
                        raise ValueError('Recorded seed provenance mismatch')
                if view['status']=='completed' and previous is None:
                    raise ValueError('Completed view is missing a seed')
                ready[(key,seed)]=previous
            if view['status']=='completed':
                dest=(output/view['reference']).resolve(strict=True)
                if dest.parent!=viewdir.resolve() or runner.file_sha256(dest)!=view['reference_sha256']:
                    raise ValueError('Reference output provenance mismatch')
        status['status']='running';status.pop('error',None);_save_status(status_path,status)
        for row in rows:
            key=(row['scene_id'],row['view_id']);view=views[key];viewdir=output/key[0]/key[1]
            if view['status']=='completed':continue
            viewdir.mkdir(parents=True,exist_ok=True);view['status']='running';_save_status(status_path,status)
            images=[]
            for seed in range(8):
                if not _row_unchanged(row) or _pipeline_hashes()!=pipeline:
                    raise ValueError('Configuration or pipeline changed during batch')
                previous=ready[(key,seed)]
                if previous is None:
                    attempt=_next_attempt(viewdir/'seeds'/f'seed-{seed+1:02d}')
                    manifest=runner.launch(Path(row['path']),attempt,seed,1024,1920,1080,timeout)
                    if Path(manifest).resolve()!=(attempt/'manifest.json').resolve():raise ValueError('Unexpected manifest path')
                    manifest,image=_validate_seed(attempt,seed,row,provenance[key])
                else:manifest,image=previous
                images.append(image)
                entry={'index':seed,'manifest':str(manifest.relative_to(output)),
                       'manifest_sha256':runner.file_sha256(manifest),'hdr_sha256':runner.file_sha256(image)}
                view['seeds']=[x for x in view['seeds'] if x['index']!=seed]+[entry]
                view['seeds'].sort(key=lambda x:x['index']);_save_status(status_path,status)
            # Revalidate inputs and all eight outputs immediately before publishing.
            if current_provenance(row['config'])!=provenance[key] or _pipeline_hashes()!=pipeline or not _row_unchanged(row):
                raise ValueError('Inputs changed before averaging')
            images=[_validate_seed(ready_attempt.parent,seed,row,provenance[key])[1]
                    for seed,ready_attempt in enumerate([output/x['manifest'] for x in view['seeds']])]
            dest=viewdir/'reference.exr';n=2
            while dest.exists():
                dest=viewdir/f'reference-attempt-{n:02d}.exr';n+=1
            average_seed_exrs(images,dest)
            if current_provenance(row['config'])!=provenance[key] or _pipeline_hashes()!=pipeline or not _row_unchanged(row):
                raise ValueError('Inputs changed during averaging')
            for seed, entry in enumerate(view['seeds']):
                manifest=output/entry['manifest']
                if runner.file_sha256(manifest)!=entry['manifest_sha256']:
                    raise ValueError('Seed manifest changed during averaging')
                _validate_seed(manifest.parent,seed,row,provenance[key])
            view.update(status='completed',reference=str(dest.relative_to(output)),
                        reference_sha256=runner.file_sha256(dest),completed_utc=_time())
            _save_status(status_path,status)
        status.update(status='completed',completed_utc=_time());_save_status(status_path,status)
    except BaseException as exc:
        for view in status['views']:
            if view['status']=='running':view['status']='failed'
        status.update(status='failed',error=str(exc),ended_utc=_time());_save_status(status_path,status)
        raise
    return status_path


def run_batch(config_paths, output, *, timeout=7200, resume=False):
    with exclusive_operation(BATCH_LOCK):
        return _run_batch(config_paths,output,timeout,resume)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configs',nargs='+',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--timeout',type=float,default=7200)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    print(run_batch(args.configs,args.output,timeout=args.timeout,resume=args.resume))


if __name__=='__main__':main()
