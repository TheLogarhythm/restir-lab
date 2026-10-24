"""Create and verify the explicitly authorized PDF reporting archive; never deletes sources."""
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import argparse, csv, hashlib, json, math, re, shutil, sys

REPO=Path(__file__).resolve().parents[2]
SOURCE=REPO/'runs/pdf-controlled-20261018'
ARCHIVE=REPO/'runs/pdf-similarity-archive'
DYNAMIC=('arcade-motion','bistro-interior-motion','bistro-exterior-motion','bistro-lighting')
MEDIA={'.png','.npz','.mp4'}

def now(): return datetime.now(timezone.utc).isoformat()
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()
def rebase(v):
    if isinstance(v,dict):return {k:rebase(x) for k,x in v.items()}
    if isinstance(v,list):return [rebase(x) for x in v]
    if isinstance(v,str):
        for old,new in ((str(SOURCE),str(ARCHIVE)),(SOURCE.as_posix(),ARCHIVE.as_posix())):
            if v.lower().startswith(old.lower()):return new+v[len(old):]
    return v

def selection():
    files=sorted(p for p in SOURCE.rglob('*') if p.is_file())
    state=read(SOURCE/'state.json'); idx=read(SOURCE/'references/reference-index.json')
    keep={}; refs=set(); ref_png=set()
    for v in idx['references'].values():
        p=SOURCE/'references'/v['image']; refs.add(p)
        if v.get('converged'):
            refs.add(SOURCE/'references'/v['previous_image']); ref_png.add(p.parent.parent/'reference.png')
        else:ref_png.add(p.with_suffix('').with_suffix('.png'))
        streams=v['stream_images']
        refs.update(SOURCE/'references'/x for x in (streams.values() if isinstance(streams,dict) else streams))
    products={SOURCE/v for k,v in state['products'].items() if k.startswith('artifacts/') and not k.startswith('artifacts/raw/')}
    for p in files:
        rel=p.relative_to(SOURCE); top=rel.parts[0]; hdr=p.name.endswith('.pfm.gz')
        if p.suffix not in MEDIA and not hdr:keep[p]='complete_original_statistics_settings_and_records'
        elif p in refs:keep[p]='final_or_reference_sensitivity_hdr'
        elif p in ref_png:keep[p]='final_reference_display'
        elif top in ('formal','ablation','equal-time'):
            f=int(re.fullmatch(r'frame-(\d+)\.(?:png|pfm.gz)',p.name)[1]); dynamic=rel.parts[1] in DYNAMIC
            if p.suffix=='.png' and (not dynamic or f in {1,31,32,33,47,48,64,65,95,96}):keep[p]='method_keyframe_png'
            elif hdr and f in ({31,32,47,48,95,96} if dynamic else {128}):keep[p]='sparse_evaluation_method_hdr'
        elif top=='artifacts' and p.suffix=='.png':
            if any(p.is_relative_to(x) for x in products):keep[p]='current_official_display_error_or_roi'
            elif len(rel.parts)>4 and rel.parts[1]=='raw' and rel.parts[2] in DYNAMIC and rel.parts[3]=='frames':keep[p]='complete_video_source_png'
            elif len(rel.parts)>3 and rel.parts[1]=='raw' and rel.parts[3]=='panels':keep[p]='historical_raw_comparison_panel'
        elif top=='diagnostics' and p.suffix=='.png':keep[p]='diagnostic_display'
        elif p==SOURCE/state['products']['analysis/equal-time-comparison']/'frontier.png':keep[p]='equal_time_plot'
    counts=Counter('pfm.gz' if p.name.endswith('.pfm.gz') else p.suffix for p in keep)
    assert len(files)==8490 and counts['.png']==1666 and counts['pfm.gz']==228 and counts['.csv']==375 and counts['.mp4']==0,counts
    assert Counter(keep.values())['complete_video_source_png']==768
    return files,keep,state

def prepare():
    assert SOURCE.is_dir() and SOURCE.resolve().parent==(REPO/'runs').resolve() and not SOURCE.is_symlink()
    assert not ARCHIVE.exists(),'Archive already exists; inspect before modifying.'
    files,keep,state=selection(); ARCHIVE.mkdir()
    save(ARCHIVE/'migration-status.json',{'phase':'copying','source':str(SOURCE),'authorized_plan':'User-approved 2026-10-23: full video PNG, sparse HDR, no old MP4; verify before deleting old directory.','updated_utc':now()})
    entries=[];total=0
    for i,p in enumerate(files,1):
        rel=p.relative_to(SOURCE).as_posix();n=p.stat().st_size;digest=sha(p);total+=n
        e={'original_source':p.relative_to(REPO).as_posix(),'source_absolute':str(p),'relative_path':rel,'bytes':n,'sha256':digest,'status':'retained' if p in keep else 'omitted','current_path':(ARCHIVE/rel).relative_to(REPO).as_posix() if p in keep else None,'reason':keep.get(p,'outside_approved_retention_set')}
        if p in keep:
            dest=ARCHIVE/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
            assert sha(dest)==digest,rel
        entries.append(e)
        if i%500==0:print(f'Inventoried {i}/{len(files)} files, {total/2**30:.2f} GiB; retained copies hash checked.',flush=True)
    save(ARCHIVE/'inventory.json',{'schema_version':1,'created_utc':now(),'historical_root':str(SOURCE),'archive_root':str(ARCHIVE),'source_files':len(files),'source_bytes':total,'retained_files':len(keep),'retained_bytes':sum(e['bytes'] for e in entries if e['status']=='retained'),'entries':entries})
    audits=[]
    for p in sorted((REPO/'build/pdf-controlled').rglob('*')):
        if not p.is_file():continue
        rel=p.relative_to(REPO/'build/pdf-controlled');dest=ARCHIVE/'audits'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
        digest=sha(p);assert sha(dest)==digest
        audits.append({'original_source':p.relative_to(REPO).as_posix(),'current_path':dest.relative_to(ARCHIVE).as_posix(),'bytes':p.stat().st_size,'sha256':digest})
    save(ARCHIVE/'audit-inventory.json',{'created_utc':now(),'entries':audits})
    conditions=[]
    for key in state['products']:
        if not key.startswith('artifacts/') or key.startswith('artifacts/raw/'):continue
        cid=key.split('/',1)[1];analysis=state['products']['analysis/'+cid]
        receipt=read(SOURCE/analysis/'.controlled-output.json')
        report=next(c for c in receipt['identity']['reports'] if c['id']==cid)
        conditions.append({'id':cid,'analysis':analysis,'artifacts':state['products'][key],'report':rebase(report),'original_receipt_sha256':sha(SOURCE/analysis/'.controlled-output.json')})
    save(ARCHIVE/'archive-inputs.json',{'schema_version':1,'created_utc':now(),'kind':'derived_current_input_mapping_original_receipts_unchanged','conditions':conditions})
    save(ARCHIVE/'artifact-availability.json',{'schema_version':1,'archived_utc':now(),'status':'archive_copied_pending_verification','historical_root':'runs/pdf-controlled-20261018','current_root':'runs/pdf-similarity-archive','inventory':'inventory.json','method_runs':78,'method_seeds':[1,2,3],'video_source_png':768,'method_hdr':198,'reference_hdr':30,'display_png_total':1666,'old_mp4_retained':False,'numeric_npz_retained':False,'capabilities':['Rebuild comparison videos from full 96-frame seed-1 PNG sequences.','Recompute selected spatial/ROI and local temporal metrics from retained HDR.'],'limits':['Full dynamic HDR sequences and reference generation/resume chain are retired.','Original convergence records survive; full historical convergence cannot be rerun from this archive.','Bistro reference precision remains not_evaluated.'],'original_records_immutable':True})
    save(ARCHIVE/'migration-status.json',{'phase':'copied_pending_verification','updated_utc':now(),'source':str(SOURCE)})
    print('COPY COMPLETE',len(keep),'retained source files;',len(audits),'audit snapshots',flush=True)

def verify(decode=False):
    inv=read(ARCHIVE/'inventory.json');n=0;pngs=0
    for e in inv['entries']:
        p=ARCHIVE/e['relative_path']
        if e['status']=='retained':
            assert p.is_file() and p.stat().st_size==e['bytes'] and sha(p)==e['sha256'],e['relative_path'];n+=1
            if decode and p.suffix=='.png':
                from PIL import Image
                with Image.open(p) as im:
                    im.load()
                    if e['reason']=='complete_video_source_png':assert im.size==(1920,1080)
                pngs+=1
        else:assert not p.exists(),e['relative_path']
    for e in read(ARCHIVE/'audit-inventory.json')['entries']:
        p=ARCHIVE/e['current_path'];assert p.is_file() and sha(p)==e['sha256'],e['current_path']
    for cid in DYNAMIC:
        for mode in ('pdf-off','pdf-on'):
            p=ARCHIVE/'artifacts/raw'/cid/'frames'/mode
            assert {x.name for x in p.glob('*.png')}=={f'frame-{i:04d}.png' for i in range(1,97)}
    timings=[p for branch in ('formal','ablation','equal-time') for p in (ARCHIVE/branch).rglob('timings.csv')]
    rows=sum(len(list(csv.DictReader(p.open(encoding='utf-8-sig',newline='')))) for p in timings)
    assert len(timings)==78 and rows==9216
    assert not list(ARCHIVE.rglob('*.mp4')) and not list(ARCHIVE.rglob('*.npz'))
    report={'passed':True,'checked_utc':now(),'retained_source_files_hash_checked':n,'audit_snapshots_hash_checked':len(read(ARCHIVE/'audit-inventory.json')['entries']),'pngs_decoded':pngs,'video_source_sequences':8,'frames_per_sequence':96,'timing_files':len(timings),'timing_rows':rows,'no_mp4_or_npz':True}
    save(ARCHIVE/'verification/integrity.json',report);print('INTEGRITY PASS',report,flush=True)

def numerical():
    import numpy as np
    sys.path.insert(0,str(REPO));sys.path.insert(0,str(REPO/'scripts/run'))
    from scripts.analysis import pdf_summary as ps
    from experiment.images import read_pfm
    from experiment.error_metrics import smape_map,signed_relative_map,trmae_map
    reports=[];totalrows=totalmaps=0;array_hashes={}
    prior=read(ARCHIVE/'verification/numerical.json') if (ARCHIVE/'verification/numerical.json').exists() else {}
    def compare(rows,path,keys):
        saved=list(csv.DictReader(path.open(encoding='utf-8-sig',newline='')))
        def key(row):return tuple(str(row[x]) for x in keys)
        index={key(row):row for row in saved};assert len(index)==len(rows)==len(saved),(path,len(rows),len(saved))
        diff=0
        for row in rows:
            old=index[key(row)]
            for k,v in row.items():
                if k not in old:continue
                if v is None:assert old[k] in ('','None'),(path,k,old[k])
                elif isinstance(v,(int,float,np.number)):
                    delta=abs(float(v)-float(old[k]));diff=max(diff,delta)
                    assert math.isclose(float(v),float(old[k]),rel_tol=1e-12,abs_tol=1e-12),(path,k,v,old[k])
                else:assert str(v)==old[k],(path,k,v,old[k])
        return diff
    for item in read(ARCHIVE/'archive-inputs.json')['conditions']:
        c=item['report'];c['references']={int(k):v for k,v in c['references'].items()}
        prepared=ps._prepare(c);fr=ps._measure(prepared);sr=ps._seed_metrics(fr,[prepared])
        fd=compare(fr,ARCHIVE/item['analysis']/'frame-metrics.csv',('condition','seed','method','frame','region'))
        sd=compare(sr,ARCHIVE/item['analysis']/'seed-metrics.csv',('condition','seed','method','phase','region'))
        mapcount=0;maxmap=0.;seed=next(x for x in c['runs'] if x['seed']==1)
        for frame in c['evaluation']['spatial_frames']:
            ref=read_pfm(Path(c['references'][frame]))
            for mode,field in (('pdf-off','off_dir'),('pdf-on','on_dir')):
                im=read_pfm(Path(seed[field])/f'frame-{frame:04d}.pfm.gz')
                values={'smape':smape_map(im,ref),'signed_relative':signed_relative_map(im,ref)}
                if any(pair[1]==frame for pair in c['evaluation']['temporal_pairs']):
                    prev=read_pfm(Path(seed[field])/f'frame-{frame-1:04d}.pfm.gz');pr=read_pfm(Path(c['references'][frame-1]))
                    values['trmae']=trmae_map(im,prev,ref,pr)
                npz=SOURCE/item['artifacts']/'maps'/mode/f'frame-{frame:04d}.npz'
                mapkey=npz.relative_to(SOURCE).as_posix()
                array_hashes[mapkey]={k:{'sha256':hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest(),'shape':list(v.shape),'dtype':str(v.dtype)} for k,v in values.items()}
                if npz.exists():
                    with np.load(npz) as saved:
                        assert set(saved.files)==set(values)
                        for k,v in values.items():
                            assert np.isfinite(v).all() and v.shape==saved[k].shape
                            delta=float(np.max(np.abs(v-saved[k])));maxmap=max(maxmap,delta)
                            assert np.allclose(v,saved[k],rtol=1e-12,atol=1e-12),(npz,k,delta)
                else:
                    assert prior.get('passed') and array_hashes[mapkey]==prior['map_array_hashes'][mapkey],mapkey
                mapcount+=1
        totalrows+=len(fr);totalmaps+=mapcount
        reports.append({'condition':c['id'],'frame_metric_rows':len(fr),'seed_metric_rows':len(sr),'frame_max_absolute_difference':fd,'seed_max_absolute_difference':sd,'numeric_maps_verified_before_removal':mapcount,'map_max_absolute_difference':maxmap})
        print('NUMERICAL PASS',c['id'],len(fr),'rows',mapcount,'maps',flush=True)
    for e in read(ARCHIVE/'inventory.json')['entries']:
        if e['status']=='retained' and e['reason']=='final_or_reference_sensitivity_hdr':
            im=read_pfm(ARCHIVE/e['relative_path']);assert im.shape==(1080,1920,3) and np.isfinite(im).all()
    assert totalrows==378 and totalmaps==42,(totalrows,totalmaps)
    save(ARCHIVE/'verification/numerical.json',{'passed':True,'checked_utc':now(),'scope':'Recomputed all 13 final conditions from archived HDR; spatial/local temporal rows and seed timing metrics matched originals. Current NPZ arrays compared before removal. Historical reference convergence chain was not rerun.','frame_metric_rows':totalrows,'numeric_maps':totalmaps,'conditions':reports,'map_array_hashes':array_hashes,'map_comparison':'source_npz' if SOURCE.exists() else 'pre_deletion_verified_array_hashes'})
    print('NUMERICAL AUDIT PASS',totalrows,totalmaps,flush=True)

def source_gate():
    assert read(ARCHIVE/'verification/integrity.json')['passed'] and read(ARCHIVE/'verification/numerical.json')['passed']
    inv=read(ARCHIVE/'inventory.json');actual={p.relative_to(SOURCE).as_posix() for p in SOURCE.rglob('*') if p.is_file()}
    assert actual=={e['relative_path'] for e in inv['entries']},'Source file set changed'
    for i,e in enumerate(inv['entries'],1):
        assert sha(SOURCE/e['relative_path'])==e['sha256'],e['relative_path']
        if i%1000==0:print('Deletion gate source hash check',i,flush=True)
    save(ARCHIVE/'verification/source-deletion-gate.json',{'passed':True,'checked_utc':now(),'source_absolute':str(SOURCE.resolve()),'archive_absolute':str(ARCHIVE.resolve()),'source_files_checked':len(actual),'source_bytes':inv['source_bytes'],'inventory_sha256':sha(ARCHIVE/'inventory.json')})
    print('SOURCE DELETION GATE PASS',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','verify','numerical','source-gate']);p.add_argument('--decode',action='store_true');a=p.parse_args()
    {'prepare':prepare,'verify':lambda:verify(a.decode),'numerical':numerical,'source-gate':source_gate}[a.action]()
