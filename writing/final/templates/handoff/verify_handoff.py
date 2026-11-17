from pathlib import Path
import hashlib,re
R=Path(__file__).resolve().parents[1]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
n=0
for line in (R/'checksums.sha256').read_text().splitlines():
 h,rel=line.split('  ',1);p=R/rel;assert p.is_file(),rel;assert sha(p)==h,rel;n+=1
source=R/'writing/final/source/final.md'
if source.exists():
 for name in ['final','appendix']:
  s=R/f'writing/final/source/{name}.md'
  for ref in re.findall(r'(?:src|poster)="([^"]+)"',s.read_text()):assert (s.parent/ref).resolve().is_file(),ref
 print('PASS: slide image/video links resolve')
print(f'PASS: {n} packaged file SHA-256 hashes')
