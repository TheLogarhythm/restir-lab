"""Build the expanded results panels from retained statistics; no renderer runs."""
from pathlib import Path
import json,csv,hashlib
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image,ImageDraw,ImageFont
R=Path(__file__).resolve().parents[3];F=R/'writing/final';S=R/'runs/pt-6-views-spatial-compare';O=F/'assets/figures'
inputs={};outputs={}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):inputs[p.relative_to(R).as_posix()]=sha(p);return p
def font(n):return ImageFont.truetype('C:/Windows/Fonts/arial.ttf',n)
def save(im,name):p=O/name;im.save(p);outputs[p.relative_to(R).as_posix()]=sha(p)
rows=list(csv.DictReader(read(S/'statistics/summary.csv').open()));t={(r['view'],r['method']):r for r in rows};views=['bistro-interior','bistro-exterior','classroom','emerald-square','veach-ajar','zero-day-measure-seven'];names=['Bistro Interior','Bistro Exterior','Classroom','Emerald Square','Veach Ajar','Zero Day']
plt.rcParams.update({'font.family':'Arial','font.size':15,'text.color':'#23150e','axes.labelcolor':'#23150e'})
fig,axes=plt.subplots(1,2,figsize=(11,3.6));fig.subplots_adjust(left=.15,right=.98,bottom=.19,top=.82,wspace=.35)
for ax,key,title in zip(axes,['temporal_covariance','spatial_covariance'],['Temporal covariance','Spatial covariance']):
 for i,(m,c) in enumerate([('pdf','#817394'),('cgns','#c87536')]):
  vals=[100*(float(t[v,m][key])/float(t[v,'temporal-on'][key])-1) for v in views]
  ax.barh(np.arange(6)+(i-.5)*.34,vals,height=.30,color=c,label='PDF Similarity' if m=='pdf' else 'CGNS')
  for j,val in enumerate(vals):ax.text(val+(1 if val>=0 else -1),j+(i-.5)*.34,f'{val:+.1f}%',ha='left' if val>=0 else 'right',va='center',fontsize=10)
 ax.set_yticks(range(6),names if key=='temporal_covariance' else ['']*6);ax.invert_yaxis();ax.axvline(0,color='#69584b',lw=.8);ax.set_xlim(-55,40);ax.set_title(title,pad=15);ax.set_xlabel('Change vs. ordinary reuse (%)',fontsize=11);ax.spines[['top','right','left']].set_visible(False)
axes[0].legend(loc='lower left',bbox_to_anchor=(0,1.13),ncol=2,frameon=False,fontsize=12)
p=O/'covariance-change.png';fig.savefig(p,dpi=200);plt.close(fig);outputs[p.relative_to(R).as_posix()]=sha(p)
# Classroom: compact crop grid, identical locations and display transform.
metrics=json.loads(read(S/'data/classroom/presentation-strip-metrics.json').read_text());im=Image.new('RGB',(1900,1000),'white');d=ImageDraw.Draw(im)
ref=Image.open(read(S/'images/classroom/reference.png')).convert('RGB').resize((620,349));im.paste(ref,(10,310));d.text((10,265),'Classroom',font=font(31),fill='#23150e')
for j,strip in enumerate(metrics['strips']):
 x,y=strip['x'],strip['y'];box=(x,y-64,x+128,y+64);color=['#c87536','#817394'][j]
 rect=(10+x*620/1920,310+(y-64)*349/1080,10+(x+128)*620/1920,310+(y+64)*349/1080);d.rectangle(rect,outline=color,width=3);d.text((rect[0]-24,rect[1]-8),strip['label'],font=font(25),fill=color)
 d.text((10,700+j*48),'A: detail' if j==0 else 'B: blackboard',font=font(29),fill=color)
 for i,(m,label) in enumerate([('temporal-on','Ordinary'),('pdf','PDF Similarity'),('cgns','CGNS')]):
  xx=660+i*400;yy=65+j*465
  if j==0:d.text((xx+190,12),label,font=font(32),fill='#23150e',anchor='mt')
  crop=Image.open(read(S/f'images/classroom/{m}-frame48-seed0.png')).convert('RGB').crop(box).resize((380,380),Image.Resampling.NEAREST);im.paste(crop,(xx,yy));d.line((xx,yy+190,xx+380,yy+190),fill=color,width=2)
  v=metrics['methods'][m][j]['smape'];d.text((xx+190,yy+390),f'{strip["label"]}: {v:.3f}%',font=font(31),fill='#23150e',anchor='mt')
save(im,'classroom-local-results.png')
# One scene illustrates the high-level cost breakdown.
stages=list(csv.DictReader(read(S/'statistics/stage-summary.csv').open()));st={r['method']:r for r in stages if r['view']=='bistro-interior'}
fig,ax=plt.subplots(figsize=(11,2.3));fig.subplots_adjust(left=.13,right=.92,top=.69,bottom=.23);left=np.zeros(3)
for key,label,c in [('initial_ms','Initial sampling','#23150e'),('temporal_ms','Temporal','#b7a38d'),('spatial_ms','Spatial','#c87536'),('other_frame_ms','Other','#e8ded1')]:
 vals=np.array([float(st[m][key]) for m in ['temporal-on','pdf','cgns']]);ax.barh(range(3),vals,left=left,color=c,label=label)
 for j,v in enumerate(vals):ax.text(left[j]+v/2,j,f'{v:.1f}',ha='center',va='center',color='white' if key in ['initial_ms','spatial_ms'] else '#23150e',fontsize=12)
 left+=vals
for j,m in enumerate(['temporal-on','pdf','cgns']):assert abs(left[j]-float(st[m]['frame_ms']))<1e-6
ax.set_yticks(range(3),['Ordinary','PDF','CGNS']);ax.invert_yaxis();ax.set_xlim(0,50);ax.set_xlabel('Bistro Interior GPU frame time (ms)',fontsize=12);ax.legend(ncol=4,loc='lower left',bbox_to_anchor=(0,1.08),frameon=False,fontsize=12);ax.spines[['top','right','left']].set_visible(False)
p=O/'bistro-interior-stage-cost.png';fig.savefig(p,dpi=200);plt.close(fig);outputs[p.relative_to(R).as_posix()]=sha(p)
for p,h in inputs.items():assert sha(R/p)==h
(F/'data/results-panels.json').write_text(json.dumps({'inputs':inputs,'outputs':outputs,'script_sha256':sha(Path(__file__)),'source_images_unchanged':True},indent=2)+'\n')
print('Built 3 results panels; all source hashes unchanged')
