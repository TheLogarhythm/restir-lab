"""Generate verified side-by-side 8192/16384-spp reference previews."""
import html
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
from src.image_io.exr import read_exr
from . import reference_batch as common

RECIPES={('bistro','view-a'):('aces',7.0),('bistro','view-b'):('reinhard',0.0),
         ('classroom','view-a'):('reinhard',0.0),('emerald-square','view-a'):('reinhard',8.25),
         ('veach-ajar','view-a'):('reinhard',0.0),('zero-day-measure-seven','view-a'):('reinhard',6.0)}


def display(rgb,method,ev):
    x=np.maximum(np.asarray(rgb,dtype=np.float64),0)*(2.**ev)
    if method=='reinhard':mapped=x/(1+x)
    elif method=='aces':mapped=np.clip((x*(2.51*x+.03))/(x*(2.43*x+.59)+.14),0,1)
    else:raise ValueError('Unknown display transform')
    srgb=np.where(mapped<=.0031308,12.92*mapped,1.055*mapped**(1/2.4)-.055)
    return np.rint(np.clip(srgb,0,1)*255).astype(np.uint8)


def preview_difference(actual,expected):
    actual=np.asarray(actual);expected=np.asarray(expected)
    if actual.shape!=expected.shape:raise ValueError('Old preview dimensions mismatch')
    maximum=int(np.max(np.abs(actual.astype(np.int16)-expected.astype(np.int16))))
    if maximum>1:raise ValueError('Old preview transform mismatch')
    return maximum


def publish(path,data):
    path=Path(path)
    if path.exists():
        if path.read_bytes()!=data:raise FileExistsError(path)
        return
    fd,tmp=tempfile.mkstemp(prefix='.preview-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.link(tmp,path)
    finally:os.unlink(tmp)


def create(old_root,output):
    old_root=Path(old_root).resolve(strict=True);output=Path(output).resolve(strict=True)
    index=json.loads((old_root/'manifest.json').read_text(encoding='utf-8-sig'))
    status=json.loads((output/'manifest.json').read_text(encoding='utf-8-sig'))
    old={(v['scene_id'],v['view_id']):v for v in index['views']}
    new={(v['scene_id'],v['view_id']):v for v in status['views']}
    if set(old)!=set(RECIPES) or set(new)!=set(RECIPES) or any(v['status']!='completed' for v in new.values()):
        raise ValueError('Six completed views required for gallery')
    sections=[]
    for key in RECIPES:
        ov=old[key];nv=new[key];method,ev=RECIPES[key]
        old_exr=(old_root/ov['reference']).resolve(strict=True);old_png=(old_root/ov['preview']).resolve(strict=True)
        new_exr=(output/nv['reference']).resolve(strict=True)
        if not old_exr.is_relative_to(old_root) or not old_png.is_relative_to(old_root) or not new_exr.is_relative_to(output):raise ValueError('Gallery input escapes run')
        if common.sha(old_exr)!=ov['reference_sha256'] or common.sha(old_png)!=ov['preview_sha256'] or common.sha(new_exr)!=nv['reference_sha256']:
            raise ValueError('Gallery input hash mismatch')
        expected=display(read_exr(old_exr,require_float32=True),method,ev)
        with Image.open(old_png) as im: actual=np.asarray(im.convert('RGB'))
        maxdiff=preview_difference(actual,expected)
        new_image=display(read_exr(new_exr,require_float32=True),method,ev)
        image_path=new_exr.parent/'preview-16384.png';buffer=BytesIO();Image.fromarray(new_image).save(buffer,format='PNG');publish(image_path,buffer.getvalue())
        old_url=os.path.relpath(old_png,output).replace('\\','/')
        new_url=os.path.relpath(image_path,output).replace('\\','/')
        exr_url=os.path.relpath(new_exr,output).replace('\\','/')
        title=html.escape(ov.get('title',f'{key[0]} {key[1]}'))
        sections.append(f'<section><h2>{title}</h2><p>{html.escape(method)} · EV {ev:+g} · old preview maximum difference {maxdiff}/255</p><div class="pair"><figure><img src="{html.escape(old_url,quote=True)}"><figcaption>8192 spp</figcaption></figure><figure><img src="{html.escape(new_url,quote=True)}"><figcaption>16384 spp</figcaption></figure></div><a href="{html.escape(exr_url,quote=True)}">16384 spp linear EXR</a></section>')
    page='<!doctype html><html lang="zh"><meta charset="utf-8"><title>Falcor reference 对比</title><style>body{background:#15191f;color:#eee;font:16px sans-serif;max-width:1400px;margin:30px auto;padding:0 18px}a{color:#9fcdff}.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}figure{margin:0}img{width:100%;height:auto}section{margin:32px 0}@media(max-width:700px){.pair{grid-template-columns:1fr}}</style><h1>Falcor Reference：8192 与 16384 spp</h1><p>每对图使用相同曝光和显示变换；所有数值平均均在线性 HDR 空间完成。</p>'+''.join(sections)+'</html>'
    path=output/'index.html';publish(path,page.encode('utf-8'));return path


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(create(args.old_root,args.output))


if __name__=='__main__':main()
