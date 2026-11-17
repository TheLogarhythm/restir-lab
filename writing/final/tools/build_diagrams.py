from pathlib import Path
from html import escape
OUT=Path(__file__).resolve().parents[1]/'assets/diagrams'
OUT.mkdir(parents=True,exist_ok=True)
BG='#ffffff'; INK='#23150e'; TEAL='#c87536'; MUTED='#69584b'; PURPLE='#817394'
def svg(name,body,w=1120,h=310):
    (OUT/(name+'.svg')).write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="{TEAL}"/></marker></defs><rect width="100%" height="100%" fill="{BG}"/><g font-family="Arial, Arial, sans-serif" fill="{INK}">{body}</g></svg>',encoding='utf-8')
def text(x,y,s,size=24,color=INK,weight='normal',anchor='start'):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{escape(s)}</text>'
def line(x1,y1,x2,y2,color=TEAL,arrow=False,dash=False,width=4):
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"'+(' marker-end="url(#arrow)"' if arrow else '')+(' stroke-dasharray="8 6"' if dash else '')+'/>'
def circle(x,y,r=8,color=TEAL):return f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>'
# Pipeline: original explanatory schematic, not measured data.
b=''
for x,head,sub in [(0,'Initial paths','1 sample / pixel'),(290,'Temporal reuse','Previous frame'),(580,'Spatial reuse','Our comparison'),(870,'Resolve','HDR + GPU time')]:
    b+=f'<rect x="{x+4}" y="42" width="240" height="116" rx="2" fill="'+('#f0dfc3' if x==580 else '#f4ece2')+'"/>'
    b+=text(x+124,88,head,25,TEAL if x==580 else INK,'600','middle')+text(x+124,126,sub,21,MUTED,'normal','middle')
    if x<870:b+=line(x+249,100,x+279,100,arrow=True)
b+=line(704,165,704,204)+line(522,204,945,204)+text(522,244,'Ordinary',23,INK,'600','middle')+text(710,244,'PDF Similarity',23,PURPLE,'600','middle')+text(945,244,'CGNS',23,TEAL,'600','middle')
b+=text(560,294,'Shared native PT shift mapping, Jacobians, visibility and reservoir merging',22,MUTED,anchor='middle')
svg('pipeline',b)
# Original PT schematic inspired by Tokuyoshi Figure 2.
import math
BLUE='#34558b'; ORANGE='#d56922'; LOBE='#f7b17c'
def star(x,y):
    pts=[]
    for i in range(16):
        t=i*math.pi/8;r=16 if i%2==0 else 6
        pts.append(f'{x+r*math.cos(t):.1f},{y+r*math.sin(t):.1f}')
    return f'<polygon points="{" ".join(pts)}" fill="#f2ca42" stroke="#23150e" stroke-width="1.4"/>'+circle(x,y,4,'#f2ca42')
def ray(points):
    return '<polyline points="'+' '.join(f'{x},{y}' for x,y in points)+f'" fill="none" stroke="{ORANGE}" stroke-width="2.5" stroke-linejoin="round" stroke-dasharray="6 4"/>'
def lobe(x,y,dx,dy,length,width):
    t=math.degrees(math.atan2(dy,dx));cx=x+length/2*dx;cy=y+length/2*dy
    return f'<ellipse cx="{cx}" cy="{cy}" rx="{length/2}" ry="{width}" transform="rotate({t} {cx} {cy})" fill="{LOBE}" fill-opacity=".82"/>'
b=''
for off in [0,580]:
    b+=f'<path d="M{off+25} 247 H{off+515} V261 H{off+25} Z M{off+452} 247 V160 H{off+487} V247" fill="{BLUE}"/>'
    # Recognizable side-view eye looking toward the surface hits, inspired by the supplied reference.
    b+=f'<g transform="translate({off+53} 141) rotate(25)"><path d="M-34 0 Q-17 -12 0 0 Q-17 12 -34 0 Z" fill="white" stroke="#23150e" stroke-width="3" stroke-linejoin="round"/><path d="M-13 -7 Q-20 0 -13 7" fill="none" stroke="#23150e" stroke-width="3"/><ellipse cx="-12" cy="0" rx="3" ry="6" fill="#23150e"/></g>'
    for x in [off+198,off+422]:b+=line(off+53,141,x,246,color='#23150e',width=1.6)
    b+=star(off+310,41)+star(off+497,50)
paths=[[(198,247),(168,108),(310,41)],[(198,247),(202,105),(372,130),(497,50)],[(422,247),(404,170),(497,50)]]
# At each hit, the outward normal bisects the directions to previous and next vertices.
# This keeps both segments on the reflective side and satisfies ideal reflection.
def reflecting_patch(prev,hit,nxt,half):
    import math
    def unit(v):
        n=math.hypot(*v);return(v[0]/n,v[1]/n)
    u=unit((prev[0]-hit[0],prev[1]-hit[1]));v=unit((nxt[0]-hit[0],nxt[1]-hit[1]))
    n=unit((u[0]+v[0],u[1]+v[1]));t=(-n[1],n[0])
    points=[(hit[0]+k*half*t[0]-depth*n[0],hit[1]+k*half*t[1]-depth*n[1]) for k,depth in [(-1,0),(1,0),(1,12),(-1,12)]]
    assert sum(u[i]*n[i] for i in [0,1])>0 and sum(v[i]*n[i] for i in [0,1])>0
    reflected=tuple(-u[i]+2*sum(u[k]*n[k] for k in [0,1])*n[i] for i in [0,1])
    assert max(abs(reflected[i]-v[i]) for i in [0,1])<1e-12
    return '<polygon points="'+' '.join(f'{x:.2f},{y:.2f}' for x,y in points)+'" fill="#b4b7bd"/>'
for path,half in zip(paths,[20,20,18]):
    for j in range(1,len(path)-1):b+=reflecting_patch(path[j-1],path[j],path[j+1],32 if j==2 else half)
for path in paths:
    b+=ray(path)+line(*path[0],*path[1],color=ORANGE,width=3.6)
    for x,y in path[1:-1]:b+=circle(x,y,3.5,'#7e828a')
b+=text(64,70,'Secondary surfaces',17,MUTED)+line(154,74,164,94,color=MUTED,width=1.2)
for x in [198,422]:b+=f'<circle cx="{x}" cy="247" r="5" fill="white" stroke="{ORANGE}" stroke-width="2.5"/>'
b+=text(198,280,'x',21,INK,anchor='middle')+text(422,280,'y',21,INK,anchor='middle')
b+=text(275,311,'(a) Multi-bounce paths: retain first-hop directions',20,INK,anchor='middle')
b+=lobe(778,247,-.22,-.975,115,27)+lobe(1002,247,-.57,-.822,102,15)
for x,y,dx,dy in [(778,247,-.22,-.975),(1002,247,-.57,-.822)]:
    b+=line(x,y,x+dx*102,y+dy*102,color=ORANGE,arrow=True,width=2.2)
    b+=f'<circle cx="{x}" cy="{y}" r="5" fill="white" stroke="{ORANGE}" stroke-width="2.5"/>'
b+=text(818,106,'Compare lobe direction',18,ORANGE,'600')+text(818,128,'and concentration',18,ORANGE,'600')
b+=text(778,280,'x',21,INK,anchor='middle')+text(1002,280,'y',21,INK,anchor='middle')
b+=text(850,311,'(b) Fit vMF lobes to the first-hop summaries',20,INK,anchor='middle')
svg('first-hop',b,w=1120,h=330)
# Compatibility selection, cache and three consumers.
b=text(15,28,'Propose up to 32 candidates',24,INK,'600')
for x in range(30,330,58):
    for y in range(65,245,58):b+=circle(x,y,7,'#bdc9c6')
b+=circle(147,181,11,INK)+text(45,274,'Center pixel',20,MUTED)+line(137,195,92,248,color=MUTED,width=2)
for x,y,col in [(205,122,TEAL),(262,180,'#ddc7a7'),(88,66,'#cf9f9d')]:
    b+=circle(x,y,11,col)+line(x,y,x+(0 if col==TEAL else 20),y-29,color=col,width=3)
b+=line(157,171,192,133,arrow=True)+text(360,84,'Score position + normals',25,TEAL,'600')+text(360,128,'Weighted sampling selects one.',24)+text(360,170,'Cache geometry + neighbor ID.',24)+text(360,215,'A bad geometric match is less likely.',21,MUTED)
b+=line(680,145,735,145,arrow=True)
for y,s in [(63,'Workload'),(143,'Retrace'),(223,'Merge')]:
    b+=f'<rect x="770" y="{y-31}" width="300" height="57" fill="#f0dfc3"/>'+text(920,y+6,s,24,INK,'600','middle')
b+=line(748,63,748,223,width=3)
for y in [63,143,223]:b+=line(748,y,768,y,width=3)
b+=text(920,296,'Same cached neighbor in all stages',20,MUTED,anchor='middle')
svg('cgns',b)
print('Built 3 original method diagrams')

# Restore the attributed paper excerpt using its pinned crop record.
import hashlib, json, subprocess
FINAL=OUT.parents[1]
REPO=FINAL.parents[1]
receipt=FINAL/'data/cgns-figure2.json'
if receipt.exists():
    spec=json.loads(receipt.read_text())
    source=REPO/spec['source'];target=REPO/spec['output']
    if not target.exists():
        assert hashlib.sha256(source.read_bytes()).hexdigest()==spec['source_sha256']
        x,y,w,h=map(str,spec['crop_pixels'])
        subprocess.run(['pdftoppm','-f',str(spec['page']),'-l',str(spec['page']),'-r',str(spec['dpi']),
                        '-singlefile','-x',x,'-y',y,'-W',w,'-H',h,'-png',str(source),str(target.with_suffix(''))],check=True)
    assert hashlib.sha256(target.read_bytes()).hexdigest()==spec['output_sha256'], 'CGNS figure crop changed'
