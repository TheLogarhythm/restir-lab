"""One index for the videos actually referenced by the final presentation.

Historical receipts remain immutable. A current entry pins the receipt bytes as
well as the MP4, poster, probe and complete-decode result recorded in it. Loading
this index checks recorded evidence; it does not launch ffmpeg or a renderer.
"""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DECKS = ('final', 'appendix')
INDEX = 'data/current-media.json'


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def local_path(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f'Path escapes presentation root: {value}')
    return path


def deck_slides(root: Path = ROOT, deck: str = 'final') -> list[str]:
    text = (root / 'source' / f'{deck}.md').read_text(encoding='utf-8-sig')
    # Only the opening YAML block is metadata; subsequent separators are slides.
    if text.startswith('---'):
        parts = re.split(r'^---\s*$', text, maxsplit=2, flags=re.M)
        if len(parts) != 3:
            raise ValueError(f'Incomplete front matter: {deck}')
        text = parts[2]
    return re.split(r'\n---\s*\n', text)


class _Videos(HTMLParser):
    def __init__(self):
        super().__init__()
        self.videos = []

    def handle_starttag(self, tag, attrs):
        if tag == 'video':
            values = dict(attrs)
            if not values.get('src') or not values.get('poster'):
                raise ValueError('Each presentation video needs a local src and poster')
            self.videos.append(values)


def source_references(root: Path = ROOT) -> list[dict]:
    references = []
    for deck in DECKS:
        for number, slide in enumerate(deck_slides(root, deck), 1):
            parser = _Videos()
            parser.feed(slide)
            for video in parser.videos:
                item = {'deck': deck, 'slide': number}
                for attr, key in [('src', 'path'), ('poster', 'poster')]:
                    path = local_path(root, 'source/' + video[attr])
                    item[key] = path.relative_to(root.resolve()).as_posix()
                references.append(item)
    return references


def _check_file(path: Path, expected: str, label: str):
    if not path.is_file():
        raise ValueError(f'Missing {label}: {path}')
    if digest(path) != expected:
        raise ValueError(f'{label} hash mismatch: {path}')


def _receipt_entry(root: Path, repo: Path, reference: dict, receipt_path: Path) -> dict:
    receipt = read_json(receipt_path)
    output = local_path(root, reference['path'])
    poster = local_path(root, reference['poster'])
    if (repo / receipt['output']).resolve() != output:
        raise ValueError(f'Receipt output does not match source reference: {receipt_path}')
    if (repo / receipt['poster']).resolve() != poster:
        raise ValueError(f'Receipt poster does not match source reference: {receipt_path}')
    _check_file(output, receipt['output_sha256'], 'video')
    _check_file(poster, receipt['poster_sha256'], 'poster')
    overlays = output.with_suffix('.ass')
    # ASS is a rebuild input, not a slide asset. Portable cores need only the
    # referenced MP4/poster and pinned receipt; check ASS too when it is retained.
    if overlays.is_file():
        _check_file(overlays, receipt['ass_sha256'], 'overlay')
    probe = receipt['probe']
    try:
        correct = ((probe['width'], probe['height'], probe['r_frame_rate'], probe['avg_frame_rate'],
                    int(probe['nb_read_frames']), float(probe['duration']), probe['codec_name'], probe['pix_fmt'])
                   == (1920, 1080, '30/1', '30/1', 300, 10.0, 'h264', 'yuv420p'))
    except (KeyError, TypeError, ValueError):
        correct = False
    if not correct:
        raise ValueError(f'Unexpected recorded video probe/format: {receipt_path}')
    decoded = receipt['decode']
    # Bind the full decode to this exact output, including error-on-corruption flags.
    expected_decode = ['ffmpeg', '-hide_banner', '-v', 'error', '-nostdin', '-xerror',
                       '-err_detect', 'explode', '-i', receipt['output'], '-map', '0:v:0', '-an', '-f', 'null', '-']
    if (decoded.get('command') != expected_decode or decoded.get('exit_code') != 0
            or decoded.get('stderr', '').strip() or decoded.get('all_frames_decoded') is not True):
        raise ValueError(f'Invalid complete-decode receipt/input: {receipt_path}')
    return {'scene': receipt['scene'], 'path': reference['path'],
            'sha256': receipt['output_sha256'], 'bytes': output.stat().st_size,
            'poster': {'path': reference['poster'], 'sha256': receipt['poster_sha256'], 'bytes': poster.stat().st_size},
            'overlays': {'path': overlays.relative_to(root.resolve()).as_posix(), 'sha256': receipt['ass_sha256']},
            'receipt': {'path': receipt_path.resolve().relative_to(root.resolve()).as_posix(), 'sha256': digest(receipt_path)},
            'probe': probe, 'full_decode_verification': decoded}


def create_index(root: Path = ROOT, *, repo: Path | None = None,
                 receipt_paths: dict[str, Path] | None = None) -> dict:
    root = root.resolve()
    repo = (repo or root.parents[1]).resolve()
    references = source_references(root)
    entries = []
    seen = set()
    for ref in references:
        if ref['path'] in seen:
            continue
        seen.add(ref['path'])
        receipt = (receipt_paths or {}).get(ref['path'], root / 'data' / (Path(ref['path']).stem + '.json'))
        if not receipt.is_file():
            raise ValueError(f'Missing current video receipt: {receipt}')
        entries.append(_receipt_entry(root, repo, ref, receipt))
    return {'schema_version': 1, 'role': 'Current source-referenced presentation derivatives; historical media receipts are preserved.',
            'source_decks': [f'source/{deck}.md' for deck in DECKS],
            'source_references': references, 'entries': entries,
            'verification': 'MP4/poster/overlay hashes and pinned historical probe/full-decode receipt; no fresh decode implied.'}


def load_current_media(root: Path = ROOT, *, repo: Path | None = None, verify_assets: bool = True) -> dict:
    root = root.resolve()
    repo = (repo or root.parents[1]).resolve()
    index = read_json(root / INDEX)
    references = source_references(root)
    if index.get('source_references') != references:
        raise ValueError('Current media index does not match source video/poster references; rebuild the current index')
    paths = {ref['path'] for ref in references}
    entries = index.get('entries', [])
    if len(entries) != len(paths) or {entry['path'] for entry in entries} != paths:
        raise ValueError('Current media entries do not exactly cover source references')
    if verify_assets:
        refs = {ref['path']: ref for ref in references}
        for entry in entries:
            receipt = local_path(root, entry['receipt']['path'])
            _check_file(receipt, entry['receipt']['sha256'], 'receipt')
            actual = _receipt_entry(root, repo, refs[entry['path']], receipt)
            if any(entry.get(key) != value for key, value in actual.items()):
                raise ValueError(f'Current entry differs from its pinned receipt: {entry["path"]}')
    return index


def reusable(entry: dict | None, identity: dict, root: Path = ROOT) -> bool:
    if not entry or entry.get('build_identity') != identity:
        return False
    try:
        _check_file(local_path(root, entry['path']), entry['sha256'], 'video')
        _check_file(local_path(root, entry['poster']['path']), entry['poster']['sha256'], 'poster')
        _check_file(local_path(root, entry['overlays']['path']), entry['overlays']['sha256'], 'overlay')
        _check_file(local_path(root, entry['receipt']['path']), entry['receipt']['sha256'], 'receipt')
    except (ValueError, OSError, KeyError):
        return False
    return True


def presentation_inputs(root: Path = ROOT, *, repo: Path | None = None) -> dict:
    index = load_current_media(root, repo=repo)
    entries = {entry['path']: entry for entry in index['entries']}
    videos = [{**ref, 'path': str(local_path(root, ref['path'])),
               'poster': str(local_path(root, ref['poster'])), 'sha256': entries[ref['path']]['sha256']}
              for ref in index['source_references']]
    return {'slides': len(deck_slides(root, 'final')),
            'decks': [{'deck': deck, 'slides': len(deck_slides(root, deck))} for deck in DECKS],
            'videos': videos, 'current_media_index': str((root / INDEX).resolve())}