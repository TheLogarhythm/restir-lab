"""Render a compact paired scene gallery from registered RTXDI scenes.

Both PNGs are derived from the exact same in-memory linear RGB source.
No renderer source modifications and no persistent HDR/PFM files.
"""
from pathlib import Path
import argparse, copy, ctypes as C, hashlib, json, math, os, platform, subprocess, sys, time
import numpy as np
from PIL import Image, PngImagePlugin
CODE_ROOT = Path(__file__).resolve().parent
REPO = CODE_ROOT.parents[1]
DEFAULT_OUTPUT = REPO / "runs/scene-gallery"
sys.dont_write_bytecode=True
sys.path.insert(0, str(REPO))
sys.path.insert(0,str(REPO/'scripts/run'))
from rtxdi_common import RENDERER, sha
from experiment.config import load_definition, make_config
from experiment.runner import preflight, query, relative_path
from experiment.scenes import load_scene, validate_assets, registered_scenes
from experiment.artifacts import validate_run_outputs

from scripts.gallery.gallery_tools.catalog import (add_scene, load_plan, select_views, summarize,
                                   save, utc, file_hash)
from scripts.gallery.gallery_tools.site import build_html as write_html, verify as verify_gallery


def build_html(plan, output_dir=DEFAULT_OUTPUT):
    write_html(plan, output_dir)


def verify(plan, allow_pending=False, output_dir=DEFAULT_OUTPUT):
    return verify_gallery(plan, output_dir, allow_pending=allow_pending,
                          build_config=lambda p, v: native_config(p, v, output_dir=output_dir))


def digest(data):return hashlib.sha256(data).hexdigest()

class OIDN:
    """OIDN 2.x C API, device-owned buffers (host pointers are not CUDA pointers)."""
    def __init__(self,library):
        self.path=Path(library)
        self.dirs=[os.add_dll_directory(str(self.path.parent)),os.add_dll_directory(str(self.path.parent.parent))]
        self.lib=C.CDLL(str(self.path))
        signatures={
          'oidnNewDevice':([C.c_int],C.c_void_p),
          'oidnCommitDevice':([C.c_void_p],None),'oidnReleaseDevice':([C.c_void_p],None),
          'oidnGetDeviceError':([C.c_void_p,C.POINTER(C.c_char_p)],C.c_int),
          'oidnGetDeviceInt':([C.c_void_p,C.c_char_p],C.c_int),
          'oidnNewBuffer':([C.c_void_p,C.c_size_t],C.c_void_p),
          'oidnWriteBuffer':([C.c_void_p,C.c_size_t,C.c_size_t,C.c_void_p],None),
          'oidnReadBuffer':([C.c_void_p,C.c_size_t,C.c_size_t,C.c_void_p],None),
          'oidnReleaseBuffer':([C.c_void_p],None),
          'oidnNewFilter':([C.c_void_p,C.c_char_p],C.c_void_p),
          'oidnSetFilterImage':([C.c_void_p,C.c_char_p,C.c_void_p,C.c_int,*([C.c_size_t]*5)],None),
          'oidnSetFilterBool':([C.c_void_p,C.c_char_p,C.c_bool],None),
          'oidnSetFilterInt':([C.c_void_p,C.c_char_p,C.c_int],None),
          'oidnCommitFilter':([C.c_void_p],None),'oidnExecuteFilter':([C.c_void_p],None),
          'oidnReleaseFilter':([C.c_void_p],None)}
        for name,(args,result) in signatures.items():
            fn=getattr(self.lib,name);fn.argtypes=args;fn.restype=result
    def check(self,dev):
        msg=C.c_char_p();code=self.lib.oidnGetDeviceError(dev,C.byref(msg))
        if code:raise RuntimeError('OIDN '+str(code)+': '+str(msg.value))
    def denoise(self,rgb):
        src=np.ascontiguousarray(np.maximum(rgb,0),dtype=np.float32)
        dst=np.empty_like(src);h,w,_=src.shape
        lib=self.lib;dev=lib.oidnNewDevice(3)
        self.check(dev)
        if not dev:raise RuntimeError('No OIDN CUDA device')
        buffers=[];filt=None
        try:
            lib.oidnCommitDevice(dev);self.check(dev)
            version=lib.oidnGetDeviceInt(dev,b'version')
            for _ in range(2):
                buffers.append(lib.oidnNewBuffer(dev,src.nbytes));self.check(dev)
            lib.oidnWriteBuffer(buffers[0],0,src.nbytes,src.ctypes.data)
            filt=lib.oidnNewFilter(dev,b'RT');self.check(dev)
            for key,buffer in [(b'color',buffers[0]),(b'output',buffers[1])]:
                lib.oidnSetFilterImage(filt,key,buffer,3,w,h,0,12,w*12)
            lib.oidnSetFilterBool(filt,b'hdr',True)
            lib.oidnSetFilterInt(filt,b'quality',6)
            lib.oidnCommitFilter(filt);self.check(dev)
            lib.oidnExecuteFilter(filt);self.check(dev)
            lib.oidnReadBuffer(buffers[1],0,dst.nbytes,dst.ctypes.data);self.check(dev)
            if not np.isfinite(dst).all():raise RuntimeError('Non-finite OIDN output')
            return np.maximum(dst,0),{'name':'Open Image Denoise','version_integer':version,'device':'CUDA',
                 'filter':'RT','hdr':True,'quality':'HIGH','guides':'color only','library_sha256':sha(self.path)}
        finally:
            if filt:lib.oidnReleaseFilter(filt)
            for buf in buffers:
                if buf:lib.oidnReleaseBuffer(buf)
            lib.oidnReleaseDevice(dev)

def display(rgb,ev):
    x=np.maximum(np.asarray(rgb,dtype=np.float64),0)*(2.**ev)
    mapped=np.clip((x*(2.51*x+.03))/(x*(2.43*x+.59)+.14),0,1)
    srgb=np.where(mapped<=.0031308,12.92*mapped,1.055*mapped**(1/2.4)-.055)
    return np.rint(np.clip(srgb,0,1)*255).astype(np.uint8)

def choose_exposure(rgb):
    lum=rgb@np.array([.2126,.7152,.0722])
    vals=lum[lum>1e-7]
    if not vals.size:raise RuntimeError('Black scene capture')
    p=float(np.percentile(vals,65))
    return round(max(-10,min(14,math.log2(.18/p)))*4)/4

def png(path,rgb,info):
    metadata=PngImagePlugin.PngInfo();metadata.add(b'sRGB',b'\x00')
    for k,v in info.items():metadata.add_text(k,json.dumps(v,ensure_ascii=False) if not isinstance(v,str) else v)
    Image.fromarray(rgb).save(path,pnginfo=metadata)

def make_view_config(plan,scene,width,height,scout):
    d=copy.deepcopy(plan.get('definition_snapshot') or load_definition());d['pdf_similarity']=False
    settings=plan['render_settings']
    scout_settings=plan.get('scout',{'frames':128,'averaged_tail_frames':1})
    frames=scout_settings['frames'] if scout else settings['frames']
    count=scout_settings['averaged_tail_frames'] if scout else settings['averaged_tail_frames']
    d['seed']=settings.get('seed',1)
    d['frames']=frames;d['captures']['static']=list(range(frames-count+1,frames+1))
    config=make_config(scene,d,'combined','static',resolution=[width,height],headless=True)
    config['arguments'].update({'lighting.indirectMode':('BRDF' if settings.get('indirect')=='BRDF' else 'RESTIRPT'),
       'restirPT.preset':settings.get('pt_preset','ULTRA'),
       'restirPT.initialSampling.maxBounceDepth':settings.get('max_bounces',5),
       'restirPT.initialSampling.numInitialSamples':settings.get('initial_paths_per_pixel_per_frame',1)})
    config['purpose']='configured_scene_gallery; paired unfiltered/OIDN display images; not method evaluation'
    return config

def native_config(plan, view, scout=False, *, output_dir=DEFAULT_OUTPUT):
    """Build the same portable native config used for rendering and stale checks."""
    scene=load_scene(view['scene_id'])
    scene['camera']=copy.deepcopy(view['camera'])
    scene['motion']['end_position']=scene['camera']['position'][:]
    scene['lighting'].update(view.get('lighting_overrides',{}))
    resolution=plan.get('scout',{}).get('resolution',[640,360]) if scout else plan['resolution']
    local_plan=dict(plan)
    local_plan['render_settings']={**plan['render_settings'],**view.get('render_overrides',{})}
    config=make_view_config(local_plan,scene,*resolution,scout)
    if 'indirect_mode' in view:
        config['arguments']['lighting.indirectMode']=view['indirect_mode']
    output=output_dir/('_scouts' if scout else '')/view['scene_id']/view['id']
    config['output']='.'
    config['repository_root']=relative_path(REPO,output)
    return config


def read_manifest(output_dir=DEFAULT_OUTPUT):
    return load_plan(output_dir, lambda p, v: native_config(p, v, output_dir=output_dir),
                     scene_loader=load_scene)


def render(plan,view,scout,force, *, output_dir=DEFAULT_OUTPUT):
    output_dir = Path(output_dir)
    sid=view['scene_id'];vid=view['id'];key=sid+'/'+vid
    output=output_dir/('_scouts' if scout else '')/sid/vid
    if view.get('camera') is None:
        raise ValueError('Choose a camera in scenes/'+sid+'.json before rendering '+key)
    if not scout and view.get('status')=='stale' and not force:
        raise ValueError('Configuration changed for '+key+'; use --force to replace its PNG pair')
    if not scout and view.get('status')=='completed' and not force:
        if all((output_dir/a['path']).is_file() and sha(output_dir/a['path'])==a['sha256'] for a in view['outputs'].values()):
            print('SKIP',key,flush=True);return
    if scout and not force and (output/'raw.png').is_file() and (output/'render-record.json').is_file():
        old=json.loads((output/'render-record.json').read_text(encoding='utf-8'))
        previous=copy.deepcopy(old['configuration']);desired=native_config(plan,view,scout=True,output_dir=output_dir)
        for config in (previous,desired):
            config.pop('repository_root',None);config.pop('output',None)
        if previous==desired and (view.get('exposure_ev') is None or old['display']['exposure_ev']==view['exposure_ev']):
            print('SKIP SCOUT',key,flush=True);return
    config=native_config(plan,view,scout,output_dir=output_dir)
    output.mkdir(parents=True,exist_ok=True)
    work=output_dir/'_work'/sid/vid
    work.mkdir(parents=True,exist_ok=True)
    if any(work.iterdir()):raise RuntimeError('Inspect existing temporary captures before rerendering: '+str(work))
    width,height=config['width'],config['height']
    config['repository_root']=relative_path(REPO,work)
    save(work/'config.json',config)
    exe=RENDERER/'build/bin/FullSamplePdf.exe'
    command=[str(exe),*(f'--{k}={v}' for k,v in config['arguments'].items())]
    environment={k:v for k,v in os.environ.items() if not k.upper().startswith('RTXDI_')}
    environment['RTXDI_EXPERIMENT_CONFIG']='config.json'
    started=time.monotonic();start_utc=utc()
    print('RENDER',key,'scout' if scout else f'{width}x{height}',flush=True)
    with (work/'renderer.log').open('w',encoding='utf-8') as log:
        result=subprocess.run(command,cwd=work,env=environment,stdout=log,stderr=subprocess.STDOUT,timeout=900)
    if result.returncode:raise RuntimeError('Renderer exit '+str(result.returncode)+'; '+str(work/'renderer.log'))
    validate_run_outputs(work,config)
    inputs=[];mean=np.zeros((height,width,3),dtype=np.float64)
    for frame in config['frames']:
        if not frame['capture']:continue
        p=work/f"frame-{frame['frame']:04d}.rgba16f"
        rgb=np.fromfile(p,dtype='<f2').reshape(height,width,4)[...,:3].astype(np.float64)
        if not np.isfinite(rgb).all():raise RuntimeError('Non-finite native capture')
        inputs.append({'logical_frame':frame['frame'],'sampling_frame':frame['sampling_frame'],'sha256':sha(p)})
        mean+=rgb
    mean=np.ascontiguousarray(mean/len(inputs),dtype='<f4')
    if not np.any(mean>0):raise RuntimeError('All-black capture')
    exposure=view.get('exposure_ev')
    if exposure is None:exposure=choose_exposure(mean)
    source_hash=digest(mean.tobytes())
    raw=display(mean,exposure)
    if scout:
        processed=None;denoise_record=None
    else:
        oidn=OIDN(plan['oidn_library']);processed,denoise_record=oidn.denoise(mean)
    png(output/'raw.png',raw,{'Scene':sid,'Camera':view['camera'],'Linear source SHA256':source_hash,
       'Display':{'transform':'ACES fitted + sRGB','exposure_ev':exposure},'Filtering':'none'})
    if not scout:
        png(output/'processed.png',display(processed,exposure),{'Scene':sid,'Camera':view['camera'],
          'Linear source SHA256':source_hash,'Display':{'transform':'ACES fitted + sRGB','exposure_ev':exposure},
          'Filtering':denoise_record})
    record={'status':'completed','scene_id':sid,'view_id':vid,'started_utc':start_utc,
      'finished_utc':utc(),'wall_seconds':round(time.monotonic()-started,3),
      'configuration':config,'native_resolved':json.loads((work/'resolved.json').read_text()),
      'native_command':command,'working_directory':'temporary config directory',
      'environment':{'RTXDI_EXPERIMENT_CONFIG':'config.json'},
      'runtime':{k:copy.deepcopy(plan[k]) for k in ('build','gpu','os','python') if k in plan},
      'script_sha256':sha(Path(__file__)),'tool_sources':tool_sources(),'linear_source':{'sha256':source_hash,'dtype':'little-endian float32 RGB, row-major, top-to-bottom',
          'construction':'arithmetic mean of listed native RGBA16_FLOAT captures, accumulated in float64 then converted to float32',
          'capture_hashes':inputs,'same_source_for_both_pngs':True,'finite':True,
          'mean_rgb':float(mean.mean()),'maximum_rgb':float(mean.max()),'retained_on_disk':False,
          'correlated_history_samples':True},
      'display':{'transform':'ACES fitted + sRGB','exposure_ev':exposure,'same_for_both_pngs':True},
      'postprocessing':denoise_record,'raw_is_unfiltered_after_finite_frame_average':True}
    portable_config=copy.deepcopy(config)
    portable_config['repository_root']=relative_path(REPO,output)
    save(output/'config.json',portable_config)
    record['portable_reproduction_config']='config.json'
    record['portable_reproduction_config_sha256']=sha(output/'config.json')
    save(output/'render-record.json',record)
    for name in ['renderer.log','timings.csv','resolved.json']:
        (output/name).write_bytes((work/name).read_bytes())
    # Delete only enumerated native float capture files and empty owned directories.
    for p in work.iterdir():
        if p.is_file():p.unlink()
        else:raise RuntimeError('Unexpected subdirectory in temporary capture directory')
    try:work.rmdir()
    except OSError:pass  # Windows can briefly hold an already-empty renderer working directory.
    if not scout:
        view.update(status='completed',rendered_exposure_ev=exposure,
          render_input_sha256=view['requested_input_sha256'],paired_linear_source_sha256=source_hash,
          outputs={name:{'path':(output/(name+'.png')).relative_to(output_dir).as_posix(),
            'sha256':sha(output/(name+'.png')),'width':width,'height':height} for name in ['raw','processed']},
          record=(output/'render-record.json').relative_to(output_dir).as_posix())
        summarize(plan)
        save(output_dir/'manifest.json',plan)
    print('DONE',key,'EV',exposure,'seconds',record['wall_seconds'],flush=True)

def tool_sources():
    return {p.relative_to(REPO).as_posix(): file_hash(p)
            for p in [Path(__file__), *sorted((CODE_ROOT / "gallery_tools").glob("*.py")),
                      CODE_ROOT / "gallery_tools/page.html"]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT,
                        help='Gallery configuration and rendered outputs (default: runs/scene-gallery)')
    action=parser.add_mutually_exclusive_group()
    action.add_argument('--scout',action='store_true',help='Low-resolution camera preview; no OIDN')
    action.add_argument('--render',action='store_true',help='Render configured, ready views')
    parser.add_argument('--check',action='store_true',help='Verify renderer fingerprint and selected assets')
    parser.add_argument('--sync',action='store_true',help='Refresh manifest from editable configs without rendering')
    parser.add_argument('--html',action='store_true',help='Regenerate the static gallery')
    parser.add_argument('--verify',action='store_true',help='Validate published PNG pairs, records and HTML')
    parser.add_argument('--allow-pending',action='store_true',help='Allow unrendered/planned views during verification')
    parser.add_argument('--force',action='store_true',help='Replace selected completed/stale renders')
    select=parser.add_mutually_exclusive_group()
    select.add_argument('--view',nargs='+',help='scene-id/view-id keys; omitted means all ready views')
    select.add_argument('--scene',nargs='+',help='Select all configured views of these scenes')
    parser.add_argument('--add-scene',metavar='SCENE_ID',help='Create a registered scene config; second camera starts unset')
    parser.add_argument('--list-scenes',action='store_true',help='List registered scene IDs and gallery membership')
    parser.add_argument('--oidn-smoke',action='store_true')
    args=parser.parse_args()
    output_dir = args.output_dir.resolve()
    if not any((args.scout,args.render,args.check,args.sync,args.html,args.verify,args.add_scene,args.list_scenes,args.oidn_smoke)):
        parser.print_help();return
    if args.add_scene:
        print('ADDED',add_scene(output_dir,args.add_scene,scene_loader=load_scene))
    plan=read_manifest(output_dir)
    if 'initial_publication_runtime' not in plan and 'build' in plan:
        plan['initial_publication_runtime']={k:copy.deepcopy(plan[k]) for k in ('build','gpu','os','python') if k in plan}
    if args.list_scenes:
        for sid in registered_scenes():
            print(sid, 'configured' if sid in plan['scenes'] else 'not-in-gallery')
    keys=args.view
    if args.scene:
        unknown=set(args.scene)-plan['scenes'].keys()
        if unknown:raise ValueError('Unknown gallery scene(s): '+', '.join(sorted(unknown)))
        keys=[v['scene_id']+'/'+v['id'] for v in plan['views'] if v['scene_id'] in args.scene]
    selected=select_views(plan,keys)
    if args.oidn_smoke:
        src=np.random.default_rng(5).uniform(.1,1,(128,128,3)).astype('f4')
        out,rec=OIDN(plan['oidn_library']).denoise(src)
        print(json.dumps({'finite':bool(np.isfinite(out).all()),'mean':float(out.mean()),
                         'source_std':float(src.std()),'output_std':float(out.std()),'oidn':rec}))
    if args.check or args.scout or args.render:
        if keys and (args.scout or args.render) and any(v.get('camera') is None for v in selected):
            raise ValueError('Selected view needs a camera; edit its scenes/<scene-id>.json')
        if args.render and not args.force and any(v.get('status')=='stale' for v in selected):
            raise ValueError('Selected configuration changed; inspect --sync --html, then use --force to rerender')
        plan['build']=preflight(plan['definition_snapshot'],RENDERER/'build/bin/FullSamplePdf.exe')
        plan['gpu']=query('nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader')
        plan['os']=platform.platform();plan['python']=platform.python_version()
        for sid in dict.fromkeys(v['scene_id'] for v in selected):
            assets=validate_assets(load_scene(sid));plan['scenes'][sid]['asset_validation']=assets
            print('ASSETS',sid,len(assets['file_sha256']),flush=True)
    if args.sync or args.html or args.verify or args.add_scene or args.check or args.scout or args.render:
        if 'initial_publication_reproduction' not in plan and 'reproduction' in plan:
            plan['initial_publication_reproduction']=plan['reproduction']
        plan['reproduction']={'entrypoint':'scripts/gallery/render.py --output-dir <gallery-directory>','configuration':'gallery.json + scenes/*.json',
                              'tool_sources':tool_sources(),'definition_snapshot_frozen':True,'hdr_retention':False,
                              'note':'Historical render-record.json and config.json preserve the actual renderer inputs.'}
        save(output_dir/'manifest.json',plan)
    if args.scout or args.render:
        for view in selected:
            if view.get('camera') is None:
                print('PENDING CAMERA',view['scene_id']+'/'+view['id']);continue
            render(plan,view,args.scout,args.force,output_dir=output_dir)
            if args.render:build_html(plan,output_dir)
    if args.html or args.add_scene:build_html(plan,output_dir)
    if args.verify:verify(plan,allow_pending=args.allow_pending,output_dir=output_dir)
    if args.sync:print('SYNC',plan['status'],plan['output_summary'])


if __name__=='__main__':
    main()
