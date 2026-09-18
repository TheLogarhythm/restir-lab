"""Check scaffold integrity; does not validate renderers or research results."""
from pathlib import Path
import csv
import hashlib
import json
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
errors = []
required = [
    'README.md', 'LICENSE', 'THIRD_PARTY.md', 'CONTRIBUTING.md', 'AGENTS.md',
    '.gitignore', '.gitattributes', '.github/workflows/scaffold.yml',
    'docs/scope.md', 'docs/roadmap.md', 'docs/setup.md', 'docs/architecture.md',
    'docs/decisions', 'docs/literature/notes', 'docs/reproductions', 'docs/observations',
    'renderers/README.md', 'renderers/rtxdi', 'renderers/falcor',
    'scenes/manifest.yaml', 'scenes/configs/rtxdi', 'scenes/configs/falcor',
    'scenes/trajectories', 'scenes/procedural', 'scenes/authoring',
    'experiments/protocol.md', 'experiments/configs', 'experiments/suites',
    'scripts/assets', 'scripts/run', 'scripts/analysis', 'tests',
    'results/index.csv', 'results/summaries', 'results/figures',
    'writing/references.bib', 'writing/course/sources.json',
    'writing/course/proposal/main.tex', 'writing/course/report/main.tex',
    'writing/course/slides',
]
for name in required:
    if not (ROOT / name).exists():
        errors.append(f'Missing: {name}')
try:
    sources = json.loads((ROOT / 'writing/course/sources.json').read_text(encoding='utf-8'))
    for item in sources['files']:
        path = ROOT / item['repository_path']
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            errors.append(f'Original source changed: {item["repository_path"]}')
    manifest = json.loads((ROOT / 'scenes/manifest.yaml').read_text(encoding='utf-8'))
    if manifest['schema_version'] != 1 or not isinstance(manifest['scenes'], list):
        errors.append('Invalid scene manifest schema')
    ids = set()
    for scene in manifest['scenes']:
        fields = {'id', 'source_url', 'source_revision', 'sha256', 'license',
                  'local_path', 'conversion', 'modifications', 'backend_configs'}
        if fields - scene.keys():
            errors.append(f'Scene missing fields: {fields - scene.keys()}')
        if scene.get('id') in ids:
            errors.append(f'Duplicate scene ID: {scene.get("id")}')
        ids.add(scene.get('id'))
except (OSError, ValueError, KeyError, TypeError) as exc:
    errors.append(f'Manifest validation: {exc}')
for folder in ('experiments/configs', 'experiments/suites'):
    for path in (ROOT / folder).glob('*.json'):
        try:
            json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            errors.append(f'{path.relative_to(ROOT)}: {exc}')
headers = {
    'docs/literature/reading-matrix.csv': ['paper_id','title','year','venue','source_url','code_url','method_family','reading_status','reproduction_status','notes_path'],
    'results/index.csv': ['run_id','experiment_id','backend','method','scene_id','code_commit','config_path','summary_path','artifact_uri','status'],
}
for name, expected in headers.items():
    try:
        with (ROOT / name).open(encoding='utf-8', newline='') as handle:
            rows = list(csv.reader(handle))
        if not rows or rows[0] != expected:
            errors.append(f'Unexpected CSV header: {name}')
        if any(len(row) != len(expected) for row in rows[1:]):
            errors.append(f'Inconsistent CSV row width: {name}')
    except OSError as exc:
        errors.append(str(exc))
# Do not crawl renderer dependencies or bulk assets.
markdown = list(ROOT.glob('*.md'))
for folder in ('docs', 'scenes', 'experiments', 'scripts', 'tests', 'results', 'writing', '.github'):
    markdown.extend((ROOT / folder).rglob('*.md'))
markdown.extend((ROOT / 'renderers').glob('README.md'))
for backend in ('rtxdi', 'falcor'):
    slot = ROOT / 'renderers' / backend
    if not (slot / '.git').exists() and (slot / 'README.md').is_file():
        markdown.append(slot / 'README.md')
link_count = 0
for path in markdown:
    content = re.sub(r'```.*?```', '', path.read_text(encoding='utf-8'), flags=re.S)
    for raw in re.findall(r'(?<!!)\[[^\]]+\]\(([^)]+)\)', content):
        target = raw.strip().split('#', 1)[0]
        if not target or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target):
            continue
        link_count += 1
        if not (path.parent / unquote(target)).exists():
            errors.append(f'Broken local link in {path.relative_to(ROOT)}: {target}')
if errors:
    print('\n'.join('FAIL: ' + error for error in errors))
    sys.exit(1)
print(f'PASS: {len(required)} required paths, course hashes, registries, JSON configs, and {link_count} local Markdown links.')
