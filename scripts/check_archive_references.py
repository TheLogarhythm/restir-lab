"""Optional local check of current PT result-index references; never renders or writes.

Ignored archives may be absent in a fresh checkout. Each absent archive is skipped.
Historical records inside an archive and unrelated historical result rows are not
interpreted as current file promises. Use full archive verifiers for byte integrity.
"""
import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from records.archive import child, read

ARCHIVES = {
    'pt-6-views-spatial-compare': ('manifest.json', 'falcor_pt_statistics_archive'),
    'pt-4-trajectories-spatial-compare': ('archive-manifest.json', 'falcor_pt_trajectory_media_archive'),
}

def contained(root, relative):
    return child(root, relative, must_exist=False)


def check(root=ROOT):
    root = Path(root).resolve(strict=True)
    with (root / 'results/index.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    checked, skipped = {}, []
    for name, (manifest_name, kind) in ARCHIVES.items():
        archive = contained(root, 'runs/' + name)
        if not archive.exists():
            skipped.append(name)
            continue
        manifest = read(archive / manifest_name)
        if manifest.get('kind') != kind:
            raise ValueError('Unexpected archive kind: ' + name)
        indexed = {r['path'] for r in manifest['files']}
        selected = [r for r in rows if r['experiment_id'] == name]
        expected = {name + '/' + v for v in manifest['views']}
        if len(selected) != len(expected) or {r['run_id'] for r in selected} != expected:
            raise ValueError('Result-index coverage mismatch: ' + name)
        for row in selected:
            for field in ('artifact_uri', 'summary_path', 'config_path'):
                relative = row[field]
                if not relative:
                    raise ValueError('Missing current index field: ' + field)
                path = contained(root, relative)
                if not path.exists():
                    raise ValueError('Missing current index target: ' + relative)
                if field == 'artifact_uri' and not path.is_relative_to(archive):
                    raise ValueError('Artifact is outside its archive: ' + relative)
                if path.is_relative_to(archive):
                    local = path.relative_to(archive).as_posix()
                    members = {s for s in indexed if s == local or path.is_dir() and (local == '.' or s.startswith(local + '/'))}
                    if not members:
                        raise ValueError('Unindexed current target: ' + relative)
                    for member in members:
                        if not contained(archive, member).is_file():
                            raise ValueError('Missing indexed artifact: ' + member)
        checked[name] = len(selected)
    return {'status': 'passed', 'checked_result_rows': checked, 'skipped_absent_archives': skipped,
            'scope': 'Current PT result-index paths and coverage; historical records excluded; no content hashing',
            'renderer_launched': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(check(args.workspace), indent=2))

if __name__ == '__main__':
    main()
