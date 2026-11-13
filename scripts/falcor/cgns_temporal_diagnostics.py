"""Experimental GPU validation for point-reservoir temporal reuse.

Uses the production temporal script without changing its source or runtime.
PathTracer.dupMap green is the selected temporal sample age divided by 40;
positive age proves at least one historical sample survived, not that all
pixels or all histories are correct. A private shader copy checks spatial
neighbor consistency during temporal reuse, with a fault positive control.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import numpy as np
from . import cgns_temporal_capture as temporal, cgns_paper_capture as paper
from . import spatial_render_script, spatial_capture
from . import cgns_pt_smoke as smoke, cgns_pt_six_view_smoke as six
from . import cgns_single_runtime as single, cgns_single_diagnostic as diagnostic
from . import reference_extension_batch, reference_runner, run
from .adapted_reference_runner import isolated_python_environment
from .process_utils import check_renderer_idle, exclusive_operation

ROOT=Path(__file__).resolve().parents[2]
CONFIG=ROOT/'experiments/configs/falcor-pt-spatial-comparison/classroom-reference.json'


def history_stats(age):
    a=np.asarray(age)
    if a.ndim!=2 or not a.size or not np.isfinite(a).all() or np.any(a<0):raise ValueError('Invalid temporal age image')
    positive=int(np.count_nonzero(a>0))
    return {'pixels':int(a.size),'positive_pixels':positive,'positive_fraction':positive/int(a.size),
            'max_age_frames':float(np.max(a)*40.)}


def compare_color(a,b):
    a=np.asarray(a);b=np.asarray(b)
    if a.shape!=b.shape or a.ndim!=3 or a.shape[-1]!=3 or not a.size or a.dtype!=np.float32 or b.dtype!=np.float32:
        raise ValueError('Expected matching float32 RGB images')
    if not np.isfinite(a).all() or not np.isfinite(b).all():raise ValueError('Nonfinite image')
    if not np.array_equal(a.view(np.uint32),b.view(np.uint32)):raise ValueError('Diagnostic output changes color')
    return 0.


def probe_script(scene,camera,output,*,method,temporal,dup,frames=41,captures=None):
    if type(temporal) is not bool or type(dup) is not bool:raise ValueError('Invalid mode')
    if type(frames) is not int or not 2<=frames<=64:raise ValueError('Invalid frame count')
    captures=[1,frames] if captures is None else captures
    if not captures or captures!=sorted(set(captures)) or any(type(x) is not int or not 1<=x<=frames for x in captures):raise ValueError('Invalid capture schedule')
    options = spatial_capture.graph_options(method, temporal_reuse=temporal)
    return spatial_render_script.build_script(
        scene, camera, output, frames, options, capture_frames=captures, static_clock=True,
        record_scene_state=True, duplication_map=dup,
    )


def _files(out,prefix,expected):
    import re
    found={}
    for p in Path(out).glob('capture.PathTracer.'+prefix+'.*.exr'):
        m=re.fullmatch(r'capture\.PathTracer\.'+re.escape(prefix)+r'\.(\d+)(?:\.[A-Za-z]+)?\.exr',p.name)
        if not m or int(m.group(1)) in found:raise ValueError('Unexpected duplicate capture')
        found[int(m.group(1))]=p
    if sorted(found)!=expected:raise ValueError('Unexpected capture frames for '+prefix+': '+repr(sorted(found)))
    return found


def _read_age(path, width, height):
    import OpenEXR
    with OpenEXR.File(str(path),separate_channels=True) as f:
        channels=f.channels()
        if 'G' not in channels:raise ValueError('DupMap EXR missing G channel: '+repr(list(channels)))
        age=np.array(channels['G'].pixels,copy=True)
    if age.shape!=(height,width) or age.dtype.kind!='f':raise ValueError('Invalid age EXR')
    return age


def launch(output,work):
    from src.image_io.exr import read_exr
    output=Path(output).resolve();work=Path(work).resolve()
    if not output.is_relative_to((ROOT/'runs').resolve()) or output.exists():raise ValueError('Output must be a new directory under runs')
    if work.parent!=(ROOT/'build').resolve() or work.exists():raise ValueError('Work must be a new direct child of build')
    if os.environ.get('FALCOR_DEVMODE')=='1':raise RuntimeError('FALCOR_DEVMODE conflicts')
    config=six.load_config(CONFIG);key=(config['scene_id'],config['view_id'])
    if key!=('classroom','view-a'):raise ValueError('Classroom-only diagnostic')
    entry=six.frozen_views()[key];scene=(ROOT/config['scene_source']).resolve(strict=True)
    expected_state,_=six._reference_observations(key)
    runtimes={'baseline':ROOT/'build/falcor-reference-runtime/runtime','cgns':ROOT/'build/falcor-cgns-single-reference/runtime'}
    output.mkdir(parents=True,exist_ok=False)
    results={}
    for method in ('baseline','cgns'):
        runtime=runtimes[method].resolve(strict=True)
        for name,enabled,dup in (('on',True,False),('on-dup',True,True),('off',False,False)):
            out=output/method/name
            options=temporal.graph_options(method) if enabled else paper.graph_options(method)
            command=[str(runtime/'Mogwai.exe'),'--device-type','d3d12','--width','160','--height','90','--script',str(out/'render.py'),'--headless']
            with exclusive_operation(ROOT/'build/falcor/.operation.lock'):
                check_renderer_idle();reference_extension_batch.recheck_view(entry,config)
                receipt=temporal.validate_runtime(runtime,method,False)
                source=probe_script(scene,config['camera'],out,method=method,temporal=enabled,dup=dup)
                def prepare(d): (d/'render.py').write_text(source,encoding='utf8')
                def verify(d):
                    colors=_files(d,'color',[1,41]); ages=_files(d,'dupMap',[1,41]) if dup else {}
                    smoke.validate_resolved_graph((d/'resolved.py').read_text(encoding='utf8'),options)
                    smoke.validate_resolved_graph((d/'resolved.py').read_text(encoding='utf8'),{'samplePattern':'Center','sampleCount':1,'useAlphaTest':True,'useDOF':False},'VBufferRT')
                    reference_runner.validate_camera_records(config['camera'],json.loads((d/'resolved-camera.json').read_text(encoding='utf8')),41)
                    six.validate_reference_state(expected_state,json.loads((d/'scene-state.json').read_text(encoding='utf8')))
                    if temporal.validate_runtime(runtime,method,False)!=receipt:raise ValueError('Runtime changed during diagnostic')
                    reference_extension_batch.recheck_view(entry,config)
                    artifacts=[]
                    for frame,p in sorted(colors.items()):
                        run.inspect_hdr(p,160,90);artifacts.append({'frame':frame,'color':p.name,'sha256':run.sha(p)})
                    for frame,p in sorted(ages.items()):
                        stats=history_stats(_read_age(p,160,90));artifacts.append({'frame':frame,'dupMap':p.name,'sha256':run.sha(p),'history':stats})
                    return artifacts
                with isolated_python_environment():
                    run.execute(command,out,1200,prepare=prepare,verify=verify,metadata={'kind':'temporal_history_diagnostic','method':method,'temporal':enabled,'diagnostic_output':dup,'resolution':[160,90],'frames':[1,41],'runtime_receipt':receipt,'requested_graph_options':options})
            results[(method,name)]=out
        on=results[(method,'on')];dupe=results[(method,'on-dup')];off=results[(method,'off')]
        for name in ('resolved-camera.json','scene-state.json'):
            if json.loads((on/name).read_text())!=json.loads((dupe/name).read_text()) or json.loads((on/name).read_text())!=json.loads((off/name).read_text()):raise ValueError('Scene/camera differs')
        for frame in (1,41):
            normal=read_exr(_files(on,'color',[1,41])[frame],require_float32=True)
            inspected=read_exr(_files(dupe,'color',[1,41])[frame],require_float32=True)
            compare_color(normal,inspected)
        age1=history_stats(_read_age(_files(dupe,'dupMap',[1,41])[1],160,90))
        age41=history_stats(_read_age(_files(dupe,'dupMap',[1,41])[41],160,90))
        if age1['positive_pixels']!=0:raise ValueError('Initial frame has unexpected historical sample age')
        if age41['positive_pixels']==0:raise ValueError('No temporal history selected after warmup')
        a=read_exr(_files(on,'color',[1,41])[41],require_float32=True)
        b=read_exr(_files(off,'color',[1,41])[41],require_float32=True)
        changed=int(np.count_nonzero(np.any(a!=b,axis=-1)))
        if changed==0:raise ValueError('Temporal on and off match everywhere after warmup')
        (output/method/'history-summary.json').write_text(json.dumps({'status':'passed','age_frame1':age1,'age_frame41':age41,'temporal_on_vs_off_changed_pixels':changed,'color_identical_with_dup_output':True,'limitations':'Positive age proves selected history for those pixels; zero age does not rule out historical proposals. One static scene; not proof of unbiasedness.'},indent=2),encoding='utf8')
    # Check that the production schedule of eight captures does not perturb temporal state.
    capture_results={}
    for name,frames in (('multi',list(range(41,49))),('last',[48])):
        out=output/'capture-parity'/name;runtime=runtimes['cgns'].resolve(strict=True)
        command=[str(runtime/'Mogwai.exe'),'--device-type','d3d12','--width','160','--height','90','--script',str(out/'render.py'),'--headless']
        with exclusive_operation(ROOT/'build/falcor/.operation.lock'):
            check_renderer_idle();reference_extension_batch.recheck_view(entry,config)
            receipt=temporal.validate_runtime(runtime,'cgns',False)
            source=probe_script(scene,config['camera'],out,method='cgns',temporal=True,dup=False,frames=48,captures=frames)
            def prepare(d): (d/'render.py').write_text(source,encoding='utf8')
            def verify(d):
                colors=_files(d,'color',frames)
                smoke.validate_resolved_graph((d/'resolved.py').read_text(encoding='utf8'),temporal.graph_options('cgns'))
                reference_runner.validate_camera_records(config['camera'],json.loads((d/'resolved-camera.json').read_text(encoding='utf8')),48)
                six.validate_reference_state(expected_state,json.loads((d/'scene-state.json').read_text(encoding='utf8')))
                if temporal.validate_runtime(runtime,'cgns',False)!=receipt:raise ValueError('Runtime changed during capture test')
                reference_extension_batch.recheck_view(entry,config)
                for p in colors.values():run.inspect_hdr(p,160,90)
                return [{'frame':f,'file':p.name,'sha256':run.sha(p)} for f,p in sorted(colors.items())]
            with isolated_python_environment():
                run.execute(command,out,1200,prepare=prepare,verify=verify,metadata={'kind':'temporal_capture_parity','method':'cgns','frames':frames,'runtime_receipt':receipt})
        capture_results[name]=out
    a=read_exr(_files(capture_results['multi'],'color',list(range(41,49)))[48],require_float32=True)
    b=read_exr(_files(capture_results['last'],'color',[48])[48],require_float32=True)
    compare_color(a,b)
    (output/'capture-parity'/'summary.json').write_text(json.dumps({'status':'passed','frame':48,'multi_frames':list(range(41,49)),'last_frame_only':48,'color_bitwise_identical':True},indent=2),encoding='utf8')
    # Finally test selected-neighbor consistency in an independently copied M1 runtime with temporal enabled.
    stage=output/'cgns-stage'
    with exclusive_operation(ROOT/'build/falcor/.operation.lock'):
        check_renderer_idle(); original_receipt=single.verify_prepared(runtimes['cgns']);work.mkdir(parents=True,exist_ok=False)
        target=work/'runtime'
        def ignore(_,names):return [n for n in names if n=='.shadercache' or n.endswith('.pdb') or (n.startswith('Mogwai.exe.') and n.endswith('.log'))]
        shutil.copytree(runtimes['cgns'],target,ignore=ignore)
        module=target/diagnostic.single.MODULE
        original={n:(module/n).read_bytes() for n in diagnostic.FILES}; stats={}
        try:
            for fault in (False,True):
                receipt=diagnostic.apply_diagnostic(target,inject_fault=fault);name='fault' if fault else 'good';out=stage/name
                command=[str(target/'Mogwai.exe'),'--device-type','d3d12','--width','160','--height','90','--script',str(out/'render.py'),'--headless']
                source=probe_script(scene,config['camera'],out,method='cgns',temporal=True,dup=False,frames=4,captures=[1,2,3,4])
                def prepare(d):
                    (d/'render.py').write_text(source,encoding='utf8');(d/'diagnostic-receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
                def verify(d):
                    colors=_files(d,'color',[1,2,3,4]);smoke.validate_resolved_graph((d/'resolved.py').read_text(encoding='utf8'),temporal.graph_options('cgns'))
                    reference_runner.validate_camera_records(config['camera'],json.loads((d/'resolved-camera.json').read_text(encoding='utf8')),4)
                    six.validate_reference_state(expected_state,json.loads((d/'scene-state.json').read_text(encoding='utf8')))
                    output=[]
                    for frame,p in sorted(colors.items()):
                        a=run.inspect_hdr(p,160,90);count=int(np.count_nonzero((a[:,:,0]>1e19)&(a[:,:,2]>1e19)))
                        output.append({'frame':frame,'mismatch_pixels':count,'sha256':run.sha(p),'file':p.name})
                    if (fault and not any(x['mismatch_pixels'] for x in output)) or (not fault and any(x['mismatch_pixels'] for x in output)):raise ValueError('Neighbor stage diagnostic failed')
                    return output
                try:
                    with isolated_python_environment():run.execute(command,out,1200,prepare=prepare,verify=verify,metadata={'kind':'temporal_spatial_stage_diagnostic','fault':fault,'runtime_receipt':original_receipt,'diagnostic_receipt':receipt})
                    stats[name]=json.loads((out/'manifest.json').read_text(encoding='utf8'))['artifacts']
                finally:
                    for n,data in original.items():(module/n).write_bytes(data)
            if single.verify_prepared(runtimes['cgns'])!=original_receipt:raise ValueError('Production runtime changed')
        finally:
            for n,data in original.items():(module/n).write_bytes(data)
    summary={'status':'passed','scene':'classroom','resolution':[160,90],'baseline':json.loads((output/'baseline/history-summary.json').read_text()),'cgns':json.loads((output/'cgns/history-summary.json').read_text()),'capture_parity':json.loads((output/'capture-parity/summary.json').read_text()),'stage_diagnostic':stats,'limitations':'History age marks selected historical samples only; stage check covers dispatched retrace work items. Different from author area reservoirs and splatting.'}
    (output/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf8')
    return output/'summary.json'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--work',type=Path,required=True)
    a=p.parse_args();print(launch(a.output,a.work))
if __name__=='__main__':main()