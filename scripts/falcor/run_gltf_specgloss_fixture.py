"""GPU control for low-specular SpecGloss diffuse-lobe sampling bug."""
import json, os, subprocess, sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.falcor.process_utils import exclusive_operation,check_renderer_idle
from scripts.falcor import prepare_gltf_composite_runtime_v2 as old_runtime
from scripts.falcor import prepare_gltf_specgloss_fixture_runtime as new_runtime
from image_io.exr import read_exr
old=ROOT/'runs/bistro-gltf-investigation-20261111/factor-fixture-01'
out=ROOT/'runs/bistro-gltf-general-20261111/sg-sampling-gpu-fixture-01'
if out.exists():raise FileExistsError(out)
out.mkdir()
scene_template=(old/'constant.pyscene').read_text(encoding='utf8')
render_template=(old/'textured/render.py').read_text(encoding='utf8')
env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
for name,marked,runtime in [('marked_before',True,old_runtime),('marked_after',True,new_runtime),('native_before',False,old_runtime),('native_after',False,new_runtime)]:
 d=out/name;d.mkdir()
 scene=scene_template.replace('mat.baseColor=float4(.25,.5,.75,1)','mat.baseColor=float4(.214,.061,.044,1)').replace('mat.specularParams=float4(.2,.3,.4,.6)','mat.specularParams=float4(.003,.003,.003,.6)')
 if marked:scene=scene.replace('mat=StandardMaterial(', 'mat=GltfFactorMaterial(')+'\nassert mat.gltfFactorMarker\n'
 sf=d/'scene.pyscene';sf.write_text(scene,encoding='utf8')
 render=render_template.replace(repr(str(old/'textured')),repr(str(d))).replace(repr(str(old/'textured.pyscene')),repr(str(sf)))
 render=render.replace('from reference_graph import build_graph',f"sys.path.insert(0,{str(old/'textured')!r})\nfrom reference_graph import build_graph").replace('range(4)', 'range(16)').replace('sample == 4 - 1','sample == 16 - 1')
 script=d/'render.py';script.write_text(render,encoding='utf8')
 cmd=[str(runtime.DEST/'runtime/Mogwai.exe'),'--device-type','d3d12','--width','64','--height','36','--script',str(script),'--headless']
 with exclusive_operation(ROOT/'build/falcor/.operation.lock'):
  check_renderer_idle();runtime.quarantine_transients();runtime.verify()
  with (d/'renderer.log').open('w',encoding='utf8') as log: result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,env=env,timeout=240)
  runtime.quarantine_transients();runtime.verify()
 if result.returncode:raise RuntimeError(f'{name} returned {result.returncode}')
 print(name,'completed',flush=True)
img={x:read_exr(out/x/'capture.AccumulatePass.output.16.exr') for x in ['marked_before','marked_after','native_before','native_after']}
results={}
for a,b in [('marked_before','marked_after'),('native_before','native_after')]:
 x=img[a];y=img[b]; diff=np.abs(x-y);results[a+'_vs_'+b]={'max_abs':float(np.max(diff)),'mean_abs':float(np.mean(diff)),'mean_rgb_before':np.mean(x,axis=(0,1)).tolist(),'mean_rgb_after':np.mean(y,axis=(0,1)).tolist(),'changed_fraction':float(np.mean(np.any(diff>1e-6,axis=-1)))}
(out/'comparison.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf8')
print(json.dumps(results,indent=2),flush=True)
