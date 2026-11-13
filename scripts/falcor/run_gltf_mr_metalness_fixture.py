"""Check metalness gating of marked MR transmission."""
import json,os,subprocess,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.falcor.process_utils import exclusive_operation,check_renderer_idle
from scripts.falcor import prepare_gltf_composite_runtime_v3 as runtime
from image_io.exr import read_exr
old=ROOT/'runs/bistro-gltf-general-20261111/thin-surface-fixture-01';out=ROOT/'runs/bistro-gltf-general-20261111/mr-metalness-gpu-fixture-01'
if out.exists():raise FileExistsError(out)
out.mkdir(); scene_template=(old/'thin.pyscene').read_text(encoding='utf8');render_template=(old/'thin.py').read_text(encoding='utf8');env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
for name,metallic in [('zero',0),('half',.5),('one',1)]:
 d=out/name;d.mkdir();scene=scene_template.replace('glass.thinSurface=True',f'glass.metallic={metallic}\nglass.thinSurface=True')
 sf=d/'scene.pyscene';sf.write_text(scene,encoding='utf8');render=render_template.replace(repr(str(old/'thin.pyscene')),repr(str(sf))).replace(repr(str(old/'thin')),repr(str(d)))
 render=render.replace('range(16)', 'range(64)');script=d/'render.py';script.write_text(render,encoding='utf8')
 cmd=[str(runtime.DEST/'runtime/Mogwai.exe'),'--device-type','d3d12','--width','64','--height','64','--script',str(script),'--headless']
 with exclusive_operation(ROOT/'build/falcor/.operation.lock'):
  check_renderer_idle();runtime.quarantine_transients();runtime.verify()
  with (d/'renderer.log').open('w',encoding='utf8') as log: result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,env=env,timeout=240)
  runtime.quarantine_transients();runtime.verify()
 if result.returncode:raise RuntimeError(f'{name} failed {result.returncode}')
 print(name,'completed',flush=True)
res={}
for name in ['zero','half','one']:
 a=read_exr(out/name/'capture.AccumulatePass.output.64.exr');res[name]={'center_mean_rgb':np.mean(a[8:56,8:56],axis=(0,1)).tolist(),'center_zero_fraction':float(np.mean(np.all(a[8:56,8:56]==0,axis=-1)))}
(out/'comparison.json').write_text(json.dumps(res,indent=2)+'\n',encoding='utf8');print(json.dumps(res,indent=2),flush=True)
