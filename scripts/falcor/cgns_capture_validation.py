"""Check that repeated asynchronous capture preserves each frame's pixels.

Two fresh processes execute the same four frames and seeds. The first captures
all four; the second captures only frame four. Their scene, camera, resolved
graph and final frame are checked exactly. This is a bounded GPU diagnostic,
not a quality comparison or an accumulation test.
"""
from pathlib import Path
import argparse
import json
import math
import re
import numpy as np
from src.image_io.exr import read_exr
from . import cgns_paper_capture as paper, run

ROOT=Path(__file__).resolve().parents[2]


def compare_pixels(a,b):
    a=np.asarray(a);b=np.asarray(b)
    if a.shape!=b.shape or a.ndim!=3 or a.shape[-1]!=3 or not a.size:raise ValueError('Image shape differs')
    if a.dtype!=np.float32 or b.dtype!=np.float32:raise ValueError('Expected float32')
    if not np.isfinite(a).all() or not np.isfinite(b).all():raise ValueError('Image contains nonfinite values')
    if not np.array_equal(a.view(np.uint32),b.view(np.uint32)):raise ValueError('Images not bitwise equal')
    return float(np.max(np.abs(a.astype(np.float64)-b.astype(np.float64))))


def artifact_for_frame(artifacts,frame):
    found=[x for x in artifacts if x.get('frame')==frame]
    if len(found)!=1:raise ValueError('Expected exactly one frame artifact')
    item=found[0]; name=item.get('hdr')
    if not isinstance(name,str) or Path(name).name!=name or '/' in name or '\\' in name:raise ValueError('Unsafe image filename')
    return item


def validate_artifact_set(artifacts,expected):
    if not isinstance(artifacts,list) or sorted(x.get('frame') for x in artifacts)!=expected:
        raise ValueError('Artifact frames differ from capture schedule')
    for n in expected:
        item=artifact_for_frame(artifacts,n)
        match=re.fullmatch(r'capture\.PathTracer\.color\.(\d+)(?:\.RGBA)?\.exr',item['hdr'])
        if match is None or int(match.group(1))!=n or item.get('seed')!=n-1:
            raise ValueError('Artifact filename or seed does not match frame')


def verify_pair(multi,single,frame=4):
    multi=Path(multi).resolve(strict=True);single=Path(single).resolve(strict=True)
    a=json.loads((multi/'manifest.json').read_text(encoding='utf8'));b=json.loads((single/'manifest.json').read_text(encoding='utf8'))
    if a.get('status')!='completed' or b.get('status')!='completed':raise ValueError('Capture did not complete')
    for k in ('requested_method','scene_id','view_id','scene_config_sha256','reference_baseline_sha256','resolution','seed_policy','spp_per_frame','image_accumulation','requested_graph_options','runtime_verification','runtime_spatial_shader_sha256','build_commit','driver_sha256','dependency_sha256'):
        if k not in a or a[k]!=b.get(k):raise ValueError('Manifest mismatch: '+k)
    if a['warmup_frames']!=0 or a['capture_frames']!=list(range(1,frame+1)) or b['warmup_frames']!=frame-1 or b['capture_frames']!=[frame]:raise ValueError('Capture schedule differs')
    validate_artifact_set(a['artifacts'],a['capture_frames']);validate_artifact_set(b['artifacts'],b['capture_frames'])
    if run.sha(multi/'render.py')!=a.get('render_script_sha256') or run.sha(single/'render.py')!=b.get('render_script_sha256'):raise ValueError('Actual render script hash differs')
    for name in ('resolved.py','resolved-camera.json','scene-state.json'):
        if (multi/name).read_bytes()!=(single/name).read_bytes():raise ValueError('Captured state mismatch: '+name)
    if a.get('adapted'):
        if (multi/'scene-audit.json').read_bytes()!=(single/'scene-audit.json').read_bytes():raise ValueError('Scene audit differs')
    aa=artifact_for_frame(a['artifacts'],frame);bb=artifact_for_frame(b['artifacts'],frame)
    p=multi/aa['hdr'];q=single/bb['hdr']
    if run.sha(p)!=aa['sha256'] or run.sha(q)!=bb['sha256']:raise ValueError('Frame checksum differs from manifest')
    x=read_exr(p,require_float32=True);y=read_exr(q,require_float32=True)
    if x.shape[:2]!=(a['resolution'][1],a['resolution'][0]):raise ValueError('Image dimensions mismatch')
    delta=compare_pixels(x,y)
    return {'status':'passed','method':a['requested_method'],'scene_id':a['scene_id'],'view_id':a['view_id'],
            'resolution':a['resolution'],'frame':frame,'fixed_seed':frame-1,
            'multi_manifest_sha256':run.sha(multi/'manifest.json'),'single_manifest_sha256':run.sha(single/'manifest.json'),
            'multi_frame':str(p),'multi_frame_sha256':aa['sha256'],'single_frame':str(q),'single_frame_sha256':bb['sha256'],
            'resolved_graph_sha256':run.sha(multi/'resolved.py'),'camera_sha256':run.sha(multi/'resolved-camera.json'),
            'scene_state_sha256':run.sha(multi/'scene-state.json'),'max_abs_difference':delta,'pixel_float32_bits_equal':True,
            'limitation':'Checks frame four of this scene/settings only; does not establish independence or unbiasedness.'}


def launch(config,runtime,output,*,method):
    output=Path(output).resolve(); runs=(ROOT/'runs').resolve()
    if not output.is_relative_to(runs) or output==runs or output.exists():raise ValueError('Output must be a new directory under runs')
    if method not in ('baseline','cgns'):raise ValueError('Unknown method')
    output.mkdir(parents=True,exist_ok=False)
    multi=output/'multi';single=output/'single'
    paper.launch(config,multi,runtime,method=method,width=160,height=90,warmup=0,count=4,scout=True)
    paper.launch(config,single,runtime,method=method,width=160,height=90,warmup=3,count=1,scout=True)
    result=verify_pair(multi,single)
    result['validation_script_sha256']=run.sha(Path(__file__))
    with (output/'summary.json').open('x',encoding='utf8') as f:json.dump(result,f,indent=2,allow_nan=False)
    return output/'summary.json'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--runtime',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--method',choices=('baseline','cgns'),required=True)
    a=p.parse_args();print(launch(a.config,a.runtime,a.output,method=a.method))
if __name__=='__main__':main()
