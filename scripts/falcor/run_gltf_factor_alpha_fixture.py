"""Test alpha factor under texture and constant paths using deterministic Cornell captures."""
import json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'src'))
from scripts.falcor.process_utils import exclusive_operation, check_renderer_idle
from image_io.exr import read_exr
import numpy as np
old=ROOT/'runs/bistro-gltf-investigation-20261111/factor-fixture-01'
out=ROOT/'runs/gltf-factor-alpha-gpu-fixture-01'
if out.exists(): raise FileExistsError(out)
out.mkdir(parents=True)
render_template=(old/'textured/render.py').read_text(encoding='utf8')
scene_template=(old/'textured.pyscene').read_text(encoding='utf8')
for name, textured, alpha in [('masked_constant', False, .25), ('masked_textured', True, .25), ('opaque_textured', True, 1.)]:
    d=out/name; d.mkdir()
    scene=scene_template.replace('mat=StandardMaterial(', 'mat=GltfFactorMaterial(')
    scene=scene.replace('mat.baseColor=float4(.25,.5,.75,1)', f'mat.baseColor=float4(.25,.5,.75,{alpha})').replace('mat.alphaThreshold=0', 'mat.alphaThreshold=.5')
    if not textured: scene='\n'.join(line for line in scene.splitlines() if 'loadMaterialTexture(mat,' not in line)+'\n'
    scene+='\nassert mat.gltfFactorMarker\n'
    scene_file=d/'scene.pyscene'; scene_file.write_text(scene,encoding='utf8')
    render=render_template.replace(repr(str(old/'textured')), repr(str(d))).replace(repr(str(old/'textured.pyscene')),repr(str(scene_file)))
    render=render.replace('from reference_graph import build_graph',f"sys.path.insert(0, {str(old/'textured')!r})\nfrom reference_graph import build_graph")
    script=d/'render.py'; script.write_text(render,encoding='utf8')
    cmd=[str(ROOT/'build/falcor-gltf-factor-runtime/runtime/Mogwai.exe'),'--device-type','d3d12','--width','64','--height','36','--script',str(script),'--headless']
    with exclusive_operation(ROOT/'build/falcor/.operation.lock'):
        check_renderer_idle(); result=subprocess.run(cmd,capture_output=True,text=True,timeout=240)
    (d/'stdout.log').write_text(result.stdout,encoding='utf8'); (d/'stderr.log').write_text(result.stderr,encoding='utf8')
    if result.returncode: raise RuntimeError(f'{name} failed {result.returncode}: {result.stderr[-3000:]} {result.stdout[-3000:]}')
    print(name,'completed',flush=True)
img={x:read_exr(out/x/'capture.AccumulatePass.output.4.exr') for x in ['masked_constant','masked_textured','opaque_textured']}
result={}
for a,b in [('masked_constant','masked_textured'),('masked_textured','opaque_textured')]:
    diff=np.abs(img[a]-img[b]);result[a+'_vs_'+b]={'max_abs':float(np.max(diff)),'mean_abs':float(np.mean(diff))}
(out/'comparison.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
print(json.dumps(result,indent=2),flush=True)
