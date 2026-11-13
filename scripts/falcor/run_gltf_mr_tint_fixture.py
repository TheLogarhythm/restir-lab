"""MR thin-glass transmission tint, including sRGB texture × factor."""
import json,os,subprocess,sys
from pathlib import Path
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.falcor.process_utils import exclusive_operation,check_renderer_idle
from scripts.falcor import prepare_gltf_composite_runtime_v2 as old_runtime
from scripts.falcor import prepare_gltf_composite_runtime_v3 as new_runtime
from image_io.exr import read_exr
old=ROOT/'runs/bistro-gltf-general-20261111/thin-surface-fixture-01';out=ROOT/'runs/bistro-gltf-general-20261111/mr-tint-gpu-fixture-01'
if out.exists():raise FileExistsError(out)
out.mkdir(); gray=out/'gray.png';Image.new('RGBA',(2,2),(128,128,128,255)).save(gray)
scene_template=(old/'thin.pyscene').read_text(encoding='utf8');render_template=(old/'thin.py').read_text(encoding='utf8')
linear=((128/255+.055)/1.055)**2.4
env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
for name,textured,runtime in [('old_textured',True,old_runtime),('new_textured',True,new_runtime),('new_constant',False,new_runtime)]:
 d=out/name;d.mkdir()
 if textured:
  edit=f"glass.baseColor=float4(1,.5,.25,1)\nsceneBuilder.loadMaterialTexture(glass,MaterialTextureSlot.BaseColor,{str(gray)!r})\nsceneBuilder.waitForMaterialTextureLoading()"
 else:edit=f'glass.baseColor=float4({linear},{linear*.5},{linear*.25},1)'
 scene=scene_template.replace('glass.thinSurface=True',edit+'\nglass.thinSurface=True')
 sf=d/'scene.pyscene';sf.write_text(scene,encoding='utf8')
 render=render_template.replace(repr(str(old/'thin.pyscene')),repr(str(sf))).replace(repr(str(old/'thin')),repr(str(d)))
 script=d/'render.py';script.write_text(render,encoding='utf8')
 cmd=[str(runtime.DEST/'runtime/Mogwai.exe'),'--device-type','d3d12','--width','64','--height','64','--script',str(script),'--headless']
 with exclusive_operation(ROOT/'build/falcor/.operation.lock'):
  check_renderer_idle();runtime.quarantine_transients();runtime.verify()
  with (d/'renderer.log').open('w',encoding='utf8') as log: result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,env=env,timeout=240)
  runtime.quarantine_transients();runtime.verify()
 if result.returncode:raise RuntimeError(f'{name} failed {result.returncode}')
 print(name,'completed',flush=True)
img={x:read_exr(out/x/'capture.AccumulatePass.output.16.exr') for x in ['old_textured','new_textured','new_constant']}
res={'srgb_value':128,'linear_srgb':linear}
for k,v in img.items():res[k+'_center_mean_rgb']=np.mean(v[8:56,8:56],axis=(0,1)).tolist()
diff=np.abs(img['new_textured']-img['new_constant']);res['new_texture_vs_constant']={'max_abs':float(np.max(diff)),'mean_abs':float(np.mean(diff))}
(out/'comparison.json').write_text(json.dumps(res,indent=2)+'\n',encoding='utf8');print(json.dumps(res,indent=2),flush=True)
