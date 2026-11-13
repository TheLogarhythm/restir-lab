"""Compare marked sRGB mid-gray texture factors with linear constants."""
import json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'src'))
from scripts.falcor.process_utils import exclusive_operation, check_renderer_idle
from image_io.exr import read_exr
import numpy as np
from PIL import Image
old=ROOT/'runs/bistro-gltf-investigation-20261111/factor-fixture-01'
out=ROOT/'runs/gltf-factor-srgb-gpu-fixture-01'
if out.exists(): raise FileExistsError(out)
out.mkdir(parents=True)
gray=128/255
linear=((gray+.055)/1.055)**2.4
texture=out/'gray.png'; Image.new('RGBA',(2,2),(128,128,128,255)).save(texture)
base=(old/'textured.pyscene').read_text(encoding='utf8')
render_template=(old/'textured/render.py').read_text(encoding='utf8')
for name,textured in [('linear_constant',False),('srgb_texture',True)]:
    d=out/name;d.mkdir()
    scene=base.replace('mat=StandardMaterial(', 'mat=GltfFactorMaterial(').replace('light=StandardMaterial(', 'light=GltfFactorMaterial(')
    if textured:
        scene=scene.replace(str(old/'white.png').replace('\\','\\\\'),str(texture).replace('\\','\\\\'))
    else:
        scene='\n'.join(line for line in scene.splitlines() if 'loadMaterialTexture' not in line)+'\n'
        scene=scene.replace('mat.baseColor=float4(.25,.5,.75,1)',f'mat.baseColor=float4({.25*linear},{.5*linear},{.75*linear},1)')
        scene=scene.replace('mat.specularParams=float4(.2,.3,.4,.6)',f'mat.specularParams=float4({.2*linear},{.3*linear},{.4*linear},.6)')
        scene=scene.replace('light.emissiveColor=float3(17,12,4)',f'light.emissiveColor=float3({17*linear},{12*linear},{4*linear})')
    scene+='\nassert mat.gltfFactorMarker and light.gltfFactorMarker\n'
    sf=d/'scene.pyscene';sf.write_text(scene,encoding='utf8')
    render=render_template.replace(repr(str(old/'textured')),repr(str(d))).replace(repr(str(old/'textured.pyscene')),repr(str(sf)))
    render=render.replace('from reference_graph import build_graph',f"sys.path.insert(0, {str(old/'textured')!r})\nfrom reference_graph import build_graph")
    script=d/'render.py';script.write_text(render,encoding='utf8')
    cmd=[str(ROOT/'build/falcor-gltf-factor-runtime/runtime/Mogwai.exe'),'--device-type','d3d12','--width','64','--height','36','--script',str(script),'--headless']
    with exclusive_operation(ROOT/'build/falcor/.operation.lock'):
        check_renderer_idle(); result=subprocess.run(cmd,capture_output=True,text=True,timeout=240)
    (d/'stdout.log').write_text(result.stdout,encoding='utf8');(d/'stderr.log').write_text(result.stderr,encoding='utf8')
    if result.returncode:raise RuntimeError(f'{name} failed: {result.stderr[-3000:]} {result.stdout[-3000:]}')
    print(name,'completed',flush=True)
a=read_exr(out/'linear_constant/capture.AccumulatePass.output.4.exr');b=read_exr(out/'srgb_texture/capture.AccumulatePass.output.4.exr');diff=np.abs(a-b)
result={'srgb_u8':128,'linear_srgb':linear,'max_abs':float(np.max(diff)),'mean_abs':float(np.mean(diff)),'mean_signal':float(np.mean(np.abs(a)))}
(out/'comparison.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
print(json.dumps(result,indent=2),flush=True)
