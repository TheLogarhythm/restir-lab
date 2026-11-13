"""Bake a Donut procedural sky from its source scene's directional light.

This writes a new directory only. RGBA16 quantization is emulated before an
RGB FLOAT32 EXR is written; it is an approximation of the GPU implementation.
"""
import argparse
import hashlib
import json
from pathlib import Path

import OpenEXR

from scripts.falcor.donut_scene_adapter import plan_scene
from scripts.falcor.donut_procedural_sky import generate_image

ROOT=Path(__file__).resolve().parents[2]

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def bake(scene, assets, output, *, source_lighting_model, width=2048, height=1024, ignored_top_level=None):
    scene=Path(scene).resolve(strict=True); assets=Path(assets).resolve(strict=True)
    output=Path(output).resolve()
    # A preliminary plan extracts the same world-space sun direction used for
    # subsequent scene translation. The user explicitly selected static camera.
    plan=plan_scene(scene, assets, animation_policy='source_default_disabled',
                    camera_policy='external', source_lighting_model=source_lighting_model, environment={'kind':'none'},
                    ignored_top_level=ignored_top_level,
                    approximations={'light_radius':'delta','light_range':'unbounded',
                                    'light_ies':'omit','sun_angular_size':'delta'})
    suns=[a for a in plan['actions'] if a.get('type')=='DirectionalLight']
    if not suns: raise ValueError('Source scene has no directional light for sky')
    sun=suns[0]
    direction=[-v for v in sun['direction']]
    image=generate_image(width,height,direction, sun_irradiance=sun['irradiance'],
                         sun_color=sun['color'],sun_angular_size_degrees=sun['angular_size_degrees'])
    output.mkdir(parents=True,exist_ok=False)
    exr=output/'environment.exr'
    OpenEXR.File({}, {'RGB':image}).write(str(exr))
    sources=[scene,Path(__file__).resolve(),ROOT/'scripts/falcor/donut_procedural_sky.py',
             ROOT/'scripts/falcor/donut_scene_adapter.py',
             ROOT/'renderers/rtxdi/External/donut/include/donut/shaders/sky.hlsli',
             ROOT/'renderers/rtxdi/External/donut/src/render/SkyPass.cpp',
             ROOT/'renderers/rtxdi/Samples/FullSample/Shaders/RenderEnvironmentMap.hlsl']
    record={'schema_version':1,'source':'Donut procedural sky from first source directional light',
            'image':str(exr),'sha256':sha(exr),'resolution':[width,height],
            'sun':sun,'direction_to_light':direction,
            'precision':'CPU evaluation then FLOAT16 quantization, stored FLOAT32 RGB; not bit-identical to GPU',
            'source_sha256':{str(x):sha(x) for x in sources}}
    (output/'bake-receipt.json').write_text(json.dumps(record,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return record


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scene',required=True);p.add_argument('--assets',required=True);p.add_argument('--output',required=True)
    p.add_argument('--source-lighting-model',required=True,choices=('donut','rtxdi_fullsample'))
    p.add_argument('--ignore-top-level', action='append', default=[], metavar='KEY=REASON')
    args=p.parse_args()
    ignored={}
    for item in args.ignore_top_level:
        if '=' not in item: p.error('--ignore-top-level requires KEY=REASON')
        key,reason=item.split('=',1)
        if not key or not reason or key in ignored: p.error('Invalid or duplicate ignored field')
        ignored[key]=reason
    print(json.dumps(bake(args.scene,args.assets,args.output,source_lighting_model=args.source_lighting_model,ignored_top_level=ignored),indent=2))

if __name__=='__main__':main()


