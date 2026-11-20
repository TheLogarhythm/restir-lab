"""Package a new, checksummed reporting handoff without import-time side effects.

This packages retained evidence, not a self-contained rendering installation.
Existing bundles and experiment archives are never edited.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

REPO = Path(__file__).resolve().parents[3]
FINAL = Path('writing/final')
TEMPLATES = FINAL / 'templates/handoff'
CODE_TREES = ('docs', 'src', 'scripts', 'tests', 'experiments', 'writing/course/report',
              'writing/course/templates', 'writing/course/guidelines', 'scenes/configs',
              'scenes/trajectories', 'renderers/falcor')
COMPRESSED = {'.png', '.jpg', '.jpeg', '.pdf', '.mp4', '.npz', '.pptx', '.zip'}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def slide_assets(root):
    """Resolve actual current source links; reject links outside the workspace."""
    paths = set()
    for name in ('final', 'appendix'):
        source = root / FINAL / 'source' / (name + '.md')
        for ref in re.findall(r'(?:src|poster)="([^"]+)"', source.read_text(encoding='utf-8-sig')):
            target = (source.parent / ref).resolve()
            if not target.is_relative_to(root.resolve()) or not target.is_file():
                raise ValueError('Missing or escaping slide asset: ' + ref)
            paths.add(target)
    return paths


def write_checksums(base):
    files = sorted(p for p in base.rglob('*') if p.is_file() and p != base / 'checksums.sha256')
    (base / 'checksums.sha256').write_text(
        ''.join(sha(p) + '  ' + p.relative_to(base).as_posix() + '\n' for p in files), encoding='utf-8')


def zip_bundle(base, target):
    # Refuse replacement even when callers invoke this helper directly.
    with zipfile.ZipFile(target, 'x', allowZip64=True) as archive:
        for source in sorted(p for p in base.rglob('*') if p.is_file()):
            compressed = source.suffix.lower() not in COMPRESSED
            archive.write(source, Path(base.name) / source.relative_to(base),
                          compress_type=zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED,
                          compresslevel=6 if compressed else None)


def package(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError('Handoff output already exists: ' + str(output))
    # A nested output would be re-ingested by tree() and could contaminate a
    # frozen archive. Keep generated bundles outside every consumed source tree.
    for relative in (*CODE_TREES, 'assets', 'runs', FINAL):
        if output.is_relative_to(root / relative):
            raise ValueError('Handoff output is inside a source/archive tree; use build/handoffs or an external directory')
    current_assets = slide_assets(root)  # Fail before creating a partial bundle.
    # Receipts can live under data/ (adopted media) or build/media-receipts/
    # (new derivatives). Copy the selected dependencies, not the entire build.
    final_root = root / FINAL
    index = json.loads((final_root / 'data/current-media.json').read_text(encoding='utf-8-sig'))
    for entry in index['entries']:
        for key in ('receipt', 'overlays'):
            if key == 'overlays' and key not in entry:
                continue
            source = (final_root / entry[key]['path']).resolve()
            if not source.is_relative_to(final_root):
                raise ValueError('Escaping current media dependency: ' + str(source))
            # An overlay is optional for playback; a pinned receipt is required.
            if key == 'overlays' and not source.exists():
                continue
            if not source.is_file():
                raise ValueError('Missing current media dependency: ' + str(source))
            current_assets.add(source)
    output.mkdir(parents=True)
    core, optional = output / 'restir-final-handoff', output / 'restir-original-videos'
    source_hashes = {}

    def copy(source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        source_hashes[source.relative_to(root).as_posix()] = sha(source)

    def tree(relative, destination=core, include=lambda path: True):
        for source in sorted((root / relative).rglob('*')):
            if not source.is_file() or any(x in source.parts for x in ('__pycache__', '.pytest_cache', 'node_modules', '.git')):
                continue
            if include(source):
                copy(source, destination / source.relative_to(root))

    for relative in CODE_TREES:
        tree(relative, include=lambda p: 'upstream' not in p.parts and 'build' not in p.parts
             and p.suffix.lower() not in {'.exr', '.dll', '.exe', '.pdb', '.lib', '.obj', '.png', '.jpg', '.mp4'})
    for relative in ('writing/references.bib', 'THIRD_PARTY.md', 'LICENSE', 'CONTRIBUTING.md',
                     'scenes/catalog.md', 'scenes/manifest.yaml', 'README.md'):
        if (root / relative).is_file():
            copy(root / relative, core / relative)
    archive = Path('runs/pt-6-views-spatial-compare')
    tree(archive, include=lambda p: 'records' not in p.relative_to(root / archive).parts)
    with zipfile.ZipFile(core / archive / 'records.zip', 'x', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as zipped:
        for source in sorted(p for p in (root / archive / 'records').rglob('*') if p.is_file()):
            zipped.write(source, source.relative_to(root / archive / 'records'))
            source_hashes[source.relative_to(root).as_posix()] = sha(source)
    for relative in ('source', 'tools', 'data', 'templates', 'assets/diagrams', 'assets/figures'):
        tree(FINAL / relative)
    for name in ('final.html', 'appendix.html', 'README.md'):
        copy(root / FINAL / name, core / FINAL / name)
    for name in ('final.pdf', 'appendix.pdf', 'final-notes.txt', 'rehearsal-script.md', 'final-with-videos.pptx'):
        copy(root / FINAL / 'build' / name, core / 'presentation' / name)
    for source in current_assets:
        target = core / source.relative_to(root)
        if not target.exists():
            copy(source, target)
    for name in ('2020-spatiotemporal-reservoir-resampling-for-direct-lighting.pdf',
                 '2022-generalized-resampled-importance-sampling.pdf',
                 '2023-efficient-spatial-resampling-using-pdf-similarity.pdf',
                 '2026-compatibility-guided-neighbor-selection-for-restir.pdf'):
        relative = Path('assets/papers') / name
        copy(root / relative, core / relative)
    tree('runs/pt-4-trajectories-spatial-compare', optional,
         lambda p: p.suffix.lower() in {'.mp4', '.json', '.csv', '.md', '.html', '.py', '.txt', '.log', '.jpg', '.jpeg'})
    tree('scenes/trajectories', optional)
    if len(list(optional.rglob('*.mp4'))) != 12:
        raise ValueError('Expected twelve original trajectory videos')
    (core / 'package.json').write_text(json.dumps(
        {'private': True, 'devDependencies': {'@marp-team/marp-cli': '4.5.1'}}, indent=2) + '\n')
    for template in ('START_HERE.md', 'DATA_INDEX.md', 'REPORT_GUIDE.md', 'requirements-analysis.txt'):
        copy(root / TEMPLATES / template, core / template)
    copy(root / TEMPLATES / 'build_slides.ps1', core / 'tools/build_slides.ps1')
    copy(root / TEMPLATES / 'OPTIONAL_START_HERE.md', optional / 'START_HERE.md')
    (core / 'provenance').mkdir()
    for args, name in ((['rev-parse', 'HEAD'], 'git-head.txt'), (['status', '--short'], 'git-status.txt'),
                       (['diff', '--binary'], 'tracked-working-tree.patch')):
        result = subprocess.run(['git', *args], cwd=root, capture_output=True, check=True)
        (core / 'provenance' / name).write_bytes(result.stdout)
    for base in (core, optional):
        copy(root / TEMPLATES / 'verify_handoff.py', base / 'tools/verify_handoff.py')
    state = {'timestamp_hkt': datetime.now(timezone(timedelta(hours=8))).isoformat(),
             'source_repository': str(root), 'source_files': source_hashes,
             'uncommitted_snapshot': True, 'commit_or_push_performed': False}
    (core / 'provenance/source-state.json').write_text(json.dumps(state, indent=2) + '\n')
    for base in (core, optional):
        write_checksums(base)
    for relative, expected in source_hashes.items():
        if sha(root / relative) != expected:
            raise ValueError('Source changed while packaging: ' + relative)
    archives = []
    for base, label in ((core, 'restir-final-handoff'), (optional, 'restir-original-videos-OPTIONAL')):
        target = output / (label + '.zip')
        zip_bundle(base, target)
        archives.append(target)
    validation = output / 'unpacked-validation'
    validation.mkdir()
    for archive_path in archives:
        with zipfile.ZipFile(archive_path) as zipped:
            zipped.extractall(validation)  # Only the ZIP just built from our contained tree.
    for base in (core, optional):
        extracted = validation / base.name
        subprocess.run([sys.executable, '-B', str(extracted / 'tools/verify_handoff.py')], cwd=extracted, check=True)
    result = {'output': str(output), 'source_hashes_unchanged': len(source_hashes),
              'main': str(archives[0]), 'optional': str(archives[1]), 'clean_extraction_verified': True}
    (output / 'packaging-result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='New directory; existing bundles are never overwritten')
    args = parser.parse_args(argv)
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d-%H%M%S')
    print(json.dumps(package(REPO, args.output or REPO / 'build/handoffs' / stamp), indent=2))


if __name__ == '__main__':
    main()
