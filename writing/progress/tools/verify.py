"""Verify sources, all explorer targets, source/output consistency and media."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parents[1]


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def check_indexed_source(key, entry):
    translation=entry.get('translation')
    original=REPO/(translation['original_snapshot'] if translation else entry['source'])
    errors=[]
    if not original.is_file() or sha(original)!=entry['sha256']:
        errors.append('Source missing/changed: '+key)
    if translation:
        derived=REPO/entry['source']
        if (not derived.is_file() or sha(derived)!=translation['sha256']
                or derived.stat().st_size!=translation['bytes']):
            errors.append('English derivative missing/changed: '+key)
    return errors


def check_composition(condition):
    import numpy as np
    streams={}
    for kind in ['pdf-on','pdf-off','comparison']:
        raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(ROOT/'assets/videos'/condition/(kind+'.mp4')),
            '-vf',r'select=eq(n\,0)+eq(n\,47)+eq(n\,95)','-fps_mode','passthrough','-pix_fmt','rgb24','-f','rawvideo','-'])
        streams[kind]=np.frombuffer(raw,dtype=np.uint8).reshape(3,1080,1920,3).astype(np.float32)
    y,x=np.mgrid[:1080,:1920];results=[]
    for i,frame in enumerate([1,48,96]):
        boundary=(-.01+1.26*(frame-1)/95-.24*y/1080)*1920
        left=x<boundary;valid=(y>100)&(np.abs(x-boundary)>8)
        expected=np.where(left[:,:,None],streams['pdf-on'][i],streams['pdf-off'][i])
        wrong=np.where(left[:,:,None],streams['pdf-off'][i],streams['pdf-on'][i])
        error=float(np.abs(streams['comparison'][i]-expected)[valid].mean())
        reversed_error=float(np.abs(streams['comparison'][i]-wrong)[valid].mean())
        if error>6:raise ValueError(f'{condition} frame {frame}: unexpected composition error {error}')
        if frame==48 and not error<reversed_error*.9:raise ValueError(f'{condition}: method sides do not match expected left-on/right-off')
        results.append(dict(frame=frame,mean_absolute_rgb_error=round(error,4),reversed_sides_error=round(reversed_error,4)))
    return dict(condition=condition,checks=results)


class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.slide_ids=[]
    def handle_starttag(self,tag,attributes):
        attrs=dict(attributes)
        for key in ('src','href','poster'):
            if attrs.get(key):self.links.append(attrs[key])
        if tag=='section' and attrs.get('id','').isdigit():self.slide_ids.append(attrs['id'])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--media',action='store_true');parser.add_argument('--write',action='store_true')
    args=parser.parse_args();errors=[];checks={}
    figure=json.loads((ROOT/'data/paper-figure.json').read_text(encoding='utf-8'))
    paper=REPO/figure['source']
    if not paper.is_file() or sha(paper)!=figure['source_sha256']:errors.append('Figure 2 paper source missing/changed')
    crop=ROOT/figure['path']
    if not crop.is_file() or sha(crop)!=figure['sha256']:errors.append('Figure 2 crop missing/changed')
    checks['paper_figure']={'figure':figure['figure'],'page':figure['page'],'source_sha256':figure['source_sha256']}
    index=json.loads((ROOT/'data/sources.json').read_text())
    for key,entry in index['entries'].items():
        errors.extend(check_indexed_source(key,entry))
    checks['english_derivatives']=sum('translation' in entry for entry in index['entries'].values())
    for asset in index['slide_assets']:
        path=ROOT/asset['path']
        if not path.is_file() or sha(path)!=asset['sha256']:errors.append('Slide copy missing/changed: '+str(path))
    checks['source_hashes']=len(index['entries']);checks['unchanged_slide_images']=len(index['slide_assets'])
    for name in ['comparison.html','progress.html']:
        content=(ROOT/name).read_text(encoding='utf-8');links=Links();links.feed(content)
        for target in links.links:
            parsed=urlsplit(target)
            if parsed.scheme or not parsed.path:continue
            path=ROOT/unquote(parsed.path)
            if not path.is_file():errors.append(name+' broken link: '+target)
        checks[name]={'local_links':len(links.links)}
        if name=='progress.html':
            checks['slides']=len(links.slide_ids)
            if len(links.slide_ids)!=11:errors.append('Expected eleven slides')
            if 'videos/arcade-motion-raw' in content:errors.append('Retired video in slides')
        else:
            payload=json.loads(re.search(r'<script id="report-data" type="application/json">(.*?)</script>',content,re.S).group(1))
            count=0
            for condition in payload['conditions']:
                for frame in condition['frames']:
                    stem=f'frame-{frame:04d}'
                    for region in ['full','region-1','region-2']:
                        base='images/pdf/'+condition['id']+'/'
                        for method in ['reference','pdf-off','pdf-on']:
                            key=base+('frames/' if region=='full' else 'rois/'+region+'/')+method+'/'+stem+'.png'
                            if key not in payload['sources'] or not (ROOT/payload['sources'][key]).is_file():errors.append('Missing image '+key)
                            count+=1
                        for metric in ['smape','signed_relative']+(['trmae'] if frame!=128 else []):
                            key=base+('panels/' if region=='full' else 'rois/'+region+'/')+stem+'-'+metric+'.png'
                            if key not in payload['sources'] or not (ROOT/payload['sources'][key]).is_file():errors.append('Missing map '+key)
                            count+=1
            checks['explorer_image_combinations']=count
    for source in ['comparison.js','sequence.js']:
        subprocess.run(['node','--check',str(ROOT/'source'/source)],check=True)
    result=subprocess.run(['node',str(ROOT/'tools/test_sequence.cjs')],capture_output=True,text=True)
    checks['controller_unit_checks']=result.stdout.strip()
    if result.returncode:errors.append(result.stdout+result.stderr)
    receipt=json.loads((ROOT/'data/media.json').read_text())
    if len(receipt['entries'])!=12:errors.append('Expected twelve media files')
    media=[]
    for entry in receipt['entries']:
        path=ROOT/entry['path']
        if not path.exists() or sha(path)!=entry['sha256']:errors.append('Media hash: '+str(path));continue
        if args.media:
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-count_frames','-show_entries','stream=width,height,r_frame_rate,nb_read_frames,duration','-of','json',str(path)],text=True))['streams'][0]
            if (probe['width'],probe['height'],int(probe['nb_read_frames']),probe['r_frame_rate'])!=(1920,1080,96,'30/1') or abs(float(probe['duration'])-3.2)>.0001:errors.append('Invalid media: '+str(path))
            media.append(dict(path=entry['path'],**probe))
    checks['media']=media if args.media else '12 hashes verified; decode not requested'
    if args.media:
        checks['diagonal_composition']=[check_composition(condition) for condition in ['arcade-motion','bistro-interior-motion','bistro-exterior-motion','bistro-lighting']]
    poster=receipt['poster']
    if not poster or sha(ROOT/poster['path'])!=poster['sha256']:errors.append('Poster missing/changed')
    checks['browser_interaction']='not verified: browser tool rejected local file protocol'
    report=dict(passed=not errors,checks=checks,errors=errors)
    if args.write:(ROOT/'data/verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(bool(errors))


if __name__=='__main__':main()
