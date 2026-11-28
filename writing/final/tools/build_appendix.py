"""Refresh only the appendix quality table; Markdown prose remains authoritative."""
import csv
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]

def refresh_table(root=ROOT):
    repo = root.parents[1]
    summary = repo / 'results/summaries/falcor-pt-spatial-reuse/summary.csv'
    if not summary.exists():
        # Existing reporting handoffs carry the original archive copy of this CSV.
        summary = repo / 'runs/pt-6-views-spatial-compare/statistics/summary.csv'
    with summary.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    views=['bistro-interior','bistro-exterior','classroom','emerald-square','veach-ajar','zero-day-measure-seven']
    names=['Bistro Interior','Bistro Exterior','Classroom','Emerald Square','Veach Ajar','Zero Day Measure Seven']
    lookup={(r['view'],r['method']):r for r in rows}
    table='<table style="font-size:24px;width:100%;border-collapse:collapse"><tr><th>View</th><th>Ordinary</th><th>PDF Similarity</th><th>CGNS</th></tr>'
    for v,n in zip(views,names):
        table+='<tr><td>'+n+'</td>'
        for m in ['temporal-on','pdf','cgns']:
            r=lookup[v,m]
            table+=f'<td>{float(r["smape_percent"]):.3f} ± {float(r["smape_seed_sd"]):.3f}</td>'
        table+='</tr>'
    table+='</table>'
    path = root / 'source/appendix.md'
    source = path.read_text(encoding='utf-8-sig')
    matches = list(re.finditer(r'<table\b[^>]*>.*?</table>', source, re.S))
    if len(matches) != 1:
        raise ValueError('Expected one appendix quality table')
    match = matches[0]
    updated = source[:match.start()] + table + source[match.end():]
    if updated != source:
        path.write_text(updated, encoding='utf-8')
    return updated != source

if __name__ == '__main__':
    print('Appendix table updated' if refresh_table() else 'Appendix table unchanged')
