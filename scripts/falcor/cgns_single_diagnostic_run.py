"""GPU validation of single-neighbor CGNS selection consistency.

Copies a verified M=1 reference runtime to a new, private build directory and
instruments only that copy. Four Classroom frames must produce zero mismatch
pixels; injecting a retrace-coordinate fault must be detected. The diagnostic
checks only dispatched compact-retrace work items and is not a production run.
"""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import numpy as np
from . import cgns_single_diagnostic as diag, cgns_single_runtime as single
from . import cgns_paper_capture as paper, cgns_pt_six_view_smoke as six, cgns_pt_smoke as smoke
from . import reference_extension_batch, reference_runner, run
from .process_utils import check_renderer_idle,exclusive_operation

ROOT=Path(__file__).resolve().parents[2]


def validate_counts(counts,*,fault):
    if type(fault) is not bool or not counts or any(type(x) is not int or x<0 for x in counts):raise ValueError('Invalid diagnostic counts')
    if fault and not any(counts):raise ValueError('Fault injection did not trigger')
    if not fault and any(counts):raise ValueError('Cross-stage neighbor mismatch detected')


def launch(config_path,runtime,work,output):
    config_path=Path(config_path).resolve(strict=True);runtime=Path(runtime).resolve(strict=True)
    work=Path(work).resolve();output=Path(output).resolve()
    if work.parent!=(ROOT/'build').resolve() or work.exists():raise ValueError('Work must be a new direct child of build')
    if not output.is_relative_to((ROOT/'runs').resolve()) or output.exists():raise ValueError('Output must be a new directory under runs')
    if os.environ.get('FALCOR_DEVMODE')=='1':raise RuntimeError('FALCOR_DEVMODE overrides isolated runtime')
    config=six.load_config(config_path);key=(config['scene_id'],config['view_id'])
    if key!=('classroom','view-a'):raise ValueError('Diagnostic supports Classroom only')
    entry=six.frozen_views()[key];scene=(ROOT/config['scene_source']).resolve(strict=True)
    options=paper.graph_options('cgns');expected_state,_=six._reference_observations(key)
    dependencies=[Path(__file__),Path(diag.__file__),Path(single.__file__),Path(paper.__file__),Path(six.__file__),Path(smoke.__file__)]
    dep_hashes={str(p.relative_to(ROOT)).replace('\\','/'):run.sha(p) for p in dependencies}
    with exclusive_operation(ROOT/'build/falcor/.operation.lock'):
        check_renderer_idle(); source_receipt=single.verify_prepared(runtime)
        if source_receipt['source_kind']!='reference':raise ValueError('Classroom requires reference source')
        reference_extension_batch.recheck_view(entry,config)
        output.mkdir(parents=True,exist_ok=False);work.mkdir(parents=True,exist_ok=False)
        target=work/'runtime'
        def ignore(directory,names):
            return [n for n in names if n=='.shadercache' or n.endswith('.pdb') or (n.startswith('Mogwai.exe.') and n.endswith('.log'))]
        shutil.copytree(runtime,target,ignore=ignore)
        module=target/diag.single.MODULE
        original={name:(module/name).read_bytes() for name in diag.FILES}
        results=[]
        try:
            for fault in (False,True):
                if any((module/n).read_bytes()!=v for n,v in original.items()):raise RuntimeError('Diagnostic runtime changed unexpectedly')
                receipt=diag.apply_diagnostic(target,inject_fault=fault)
                name='fault' if fault else 'good'; out=output/name
                command=[str(target/'Mogwai.exe'),'--device-type','d3d12','--width','160','--height','90','--script',str(out/'render.py'),'--headless']
                meta={'kind':'cgns_single_stage_diagnostic','fault':fault,'slot':0,'requested_method':'cgns','resolution':[160,90],
                      'frames':[1,2,3,4],'seed_policy':'fixedSeed=frame-1','source_runtime':str(runtime),
                      'source_runtime_receipt':source_receipt,'instrumented_shader_sha256':receipt['files'],'dependency_sha256':dep_hashes}
                def prepare(d):
                    (d/'render.py').write_text(paper.render_script(scene,config['camera'],d,0,4,'cgns',adapted=False),encoding='utf8')
                    (d/'diagnostic-receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
                def verify(d):
                    images=list(d.glob('capture.PathTracer.color.*.exr'));frames=run.capture_frames(images,[1,2,3,4])
                    camera=json.loads((d/'resolved-camera.json').read_text(encoding='utf8'))
                    reference_runner.validate_camera_records(config['camera'],camera,4)
                    smoke.validate_resolved_graph((d/'resolved.py').read_text(encoding='utf8'),options)
                    state=json.loads((d/'scene-state.json').read_text(encoding='utf8'));six.validate_reference_state(expected_state,state)
                    artifacts=[];counts=[]
                    for frame,p in sorted(zip(frames,images)):
                        rgb=run.inspect_hdr(p,160,90)
                        count=int(np.count_nonzero((rgb[:,:,0]>1e19)&(rgb[:,:,2]>1e19)))
                        counts.append(count);artifacts.append({'frame':frame,'seed':frame-1,'file':p.name,'sha256':run.sha(p),'mismatch_pixels':count})
                    validate_counts(counts,fault=fault)
                    return artifacts
                try:
                    manifest=run.execute(command,out,1200,prepare=prepare,verify=verify,metadata=meta)
                    record=json.loads(manifest.read_text(encoding='utf8'))
                    results.append({'name':name,'manifest':str(manifest),'manifest_sha256':run.sha(manifest),'counts':[x['mismatch_pixels'] for x in record['artifacts']]})
                finally:
                    for filename,data in original.items():(module/filename).write_bytes(data)
            if any(run.sha(ROOT/k)!=v for k,v in dep_hashes.items()):raise ValueError('Diagnostic source changed during run')
            if single.verify_prepared(runtime)!=source_receipt:raise ValueError('Production runtime changed during diagnostic')
            reference_extension_batch.recheck_view(entry,config)
            summary={'status':'passed','resolution':[160,90],'frames':4,'slot':0,'source_runtime_receipt':source_receipt,
                     'results':results,'limitation':'Exact coordinate equality only for this scene and frames; retrace covers dispatched work items only.'}
            with (output/'summary.json').open('x',encoding='utf8') as f:json.dump(summary,f,indent=2,allow_nan=False)
        finally:
            for filename,data in original.items():(module/filename).write_bytes(data)
    return output/'summary.json'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--runtime',type=Path,required=True)
    p.add_argument('--work',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(launch(a.config,a.runtime,a.work,a.output))
if __name__=='__main__':main()
