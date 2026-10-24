"""Build the local experiment explorer from an immutable source index."""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parents[1]
LABELS={
 'cornell-static':'Cornell · Static','arcade-static':'Arcade · Static',
 'bistro-interior-static':'Bistro interior · Static','bistro-exterior-static':'Bistro exterior · Static',
 'arcade-motion':'Arcade · Camera motion','bistro-interior-motion':'Bistro interior · Camera motion',
 'bistro-exterior-motion':'Bistro exterior · Camera motion','bistro-lighting':'Bistro · Lighting change',
 'bistro-interior-static-spatial-only':'Bistro interior · Spatial only',
 'bistro-interior-static-neighbors-2':'Bistro interior · 2 neighbors',
 'bistro-interior-static-neighbors-8':'Bistro interior · 8 neighbors',
 'bistro-exterior-static-neighbors-2':'Bistro exterior · 2 neighbors',
 'bistro-exterior-static-neighbors-8':'Bistro exterior · 8 neighbors'}


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def build(restore_assets=False):
    figure=json.loads((ROOT/'data/paper-figure.json').read_text(encoding='utf-8'))
    target=ROOT/figure['path']
    if restore_assets or not target.exists():
        source=REPO/figure['source']
        if sha(source)!=figure['source_sha256']:raise ValueError('Paper source changed: '+str(source))
        target.parent.mkdir(parents=True,exist_ok=True)
        x,y,width,height=figure['crop_pixels']
        subprocess.run(['pdftoppm','-f',str(figure['page']),'-l',str(figure['page']),'-singlefile',
            '-r',str(figure['dpi']),'-x',str(x),'-y',str(y),'-W',str(width),'-H',str(height),
            '-png',str(source),str(target.with_suffix(''))],check=True)
    index=json.loads((ROOT/'data/sources.json').read_text(encoding='utf-8'))
    entries=index['entries']
    def rows(key):
        path=REPO/entries[key]['source']
        if sha(path)!=entries[key]['sha256']:raise ValueError('Source changed: '+str(path))
        with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
    def url(key):return entries[key]['url']
    def table(data):
        if not data:return ''
        keys=list(data[0]);esc=lambda v:html.escape(str(v))
        return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(k)+'</th>' for k in keys)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(r[k])+'</td>' for k in keys)+'</tr>' for r in data)+'</tbody></table></div>'
    for asset in index['slide_assets']:
        target=ROOT/asset['path']
        if restore_assets or not target.exists():
            source=REPO/asset['source']
            if sha(source)!=asset['sha256']:raise ValueError('Slide source changed: '+str(source))
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    conditions=[]
    for key,label in LABELS.items():
        prefix='images/pdf/'+key+'/frames/reference/'
        frames=sorted(int(Path(k).stem.split('-')[-1]) for k in entries if k.startswith(prefix) and k.endswith('.png'))
        if not frames:raise ValueError('No reference frames: '+key)
        base='data/pdf/'+key+'/'
        conditions.append(dict(id=key,label=label,frames=frames,
            summary=rows(base+'summary.csv'),paired=rows(base+'paired-differences.csv'),seeds=rows(base+'seed-metrics.csv'),
            csv=dict(summary=url(base+'summary.csv'),paired=url(base+'paired-differences.csv'),seeds=url(base+'seed-metrics.csv'))))
    overview=rows('data/pdf/main/full-image-overview.csv')
    scenes=json.loads((ROOT/'data/scenes.json').read_text(encoding='utf-8'))
    cards=[]
    for scene in scenes['scenes']:
        path='assets/scenes/'+scene['id']+'.png'
        cards.append('<figure><a href="'+path+'" target="_blank"><img loading="lazy" src="'+path+'" alt="'+html.escape(scene['title']+' · OIDN scene preview')+'"></a><figcaption><strong>'+html.escape(scene['title'])+'</strong><span>'+html.escape(scene['description_zh'])+'</span></figcaption></figure>')
    csvs=[(k,e) for k,e in entries.items() if k.endswith('.csv') and k.startswith('data/pdf/') and 'raw-timings' not in k]
    links=''.join('<li><a href="'+e['url']+'">'+html.escape(k.removeprefix('data/pdf/'))+'</a></li>' for k,e in csvs)
    payload=json.dumps(dict(conditions=conditions,overview=overview,sources={k:e['url'] for k,e in entries.items()}),ensure_ascii=False).replace('</','<\\/')
    content=(ROOT/'source/comparison.html').read_text(encoding='utf-8')
    values={'__CSS__':'\n'.join((ROOT/'source'/f).read_text(encoding='utf-8') for f in ['comparison.css','sequence.css']),
        '__JS__':(ROOT/'source/comparison.js').read_text(encoding='utf-8'),
        '__VIDEO_JS__':(ROOT/'source/sequence.js').read_text(encoding='utf-8'),
        '__SEQUENCE__':(ROOT/'source/sequence.html').read_text(encoding='utf-8'),
        '__SCENES__':''.join(cards),'__CSVS__':links,'__PAYLOAD__':payload,
        '__MEASURED__':table(rows('data/pdf/equal-time-comparison/measured-points.csv')),
        '__INTERPOLATED__':table(rows('data/pdf/equal-time-comparison/interpolated-estimates.csv'))}
    for key,value in values.items():content=content.replace(key,value)
    def relocate(match):
        field,quote,target=match.groups()
        return field+'='+quote+(url(target) if target in entries else target)+quote
    content=re.sub(r'''(src|href|poster)=(['"])([^'"]+)\2''',relocate,content)
    if re.search(r'__[A-Z_]+__',content):raise ValueError('Unexpanded template placeholder')
    (ROOT/'comparison.html').write_text(content,encoding='utf-8')
    print(json.dumps({'conditions':len(conditions),'overview_rows':len(overview),'scenes':len(cards),'csv_links':len(csvs),'html_bytes':len(content.encode())}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--restore-assets',action='store_true')
    build(parser.parse_args().restore_assets)
