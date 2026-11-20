"""Verify current presentation sources, timing, figures and pinned media evidence."""
from pathlib import Path
import html
import json
import re

from presentation_media import DECKS, ROOT, deck_slides, digest, load_current_media

REPO = ROOT.parents[1]


def verify():
    slides = deck_slides(ROOT, 'final')
    appendix = deck_slides(ROOT, 'appendix')
    for required in ('Group 7', 'Luoyi Zhang', 'Zelin Gao', 'ReSTIR'):
        assert required in slides[0], required
    media = load_current_media(ROOT)
    demo_slides = {ref['slide'] for ref in media['source_references'] if ref['deck'] == 'final'}
    schedule, spoken, last = [], [], 0
    for number, slide in enumerate(slides, 1):
        notes = [note for note in re.findall(r'<!--(.*?)-->', slide, re.S)
                 if '| rehearsal target' in note or '| demo' in note]
        assert len(notes) == 1, (number, notes)
        line, words, *rest = notes[0].strip().split('\n\n')
        times = re.search(r'(\d+):(\d+) to (\d+):(\d+) \| (\d+) seconds', line)
        assert times, (number, line)
        a, b, c, d, duration = map(int, times.groups())
        start, end = a * 60 + b, c * 60 + d
        assert start == last and end - start == duration, (number, start, end, last)
        last = end
        count = len(re.findall(r"\b[\w'-]+\b", words))
        schedule.append({'slide': number, 'start_seconds': start, 'end_seconds': end,
                         'spoken_words': count, 'demo': number in demo_slides})
        spoken.append(f'## Slide {number} · {line.split(" | ", 1)[0]}\n\n{words}\n\n' + '\n\n'.join(rest))
    assert last == 280, last
    demo_seconds = sum(row['end_seconds'] - row['start_seconds'] for row in schedule if row['demo'])
    durations = {entry['path']: float(entry['probe']['duration']) for entry in media['entries']}
    for ref in media['source_references']:
        if ref['deck'] == 'final':
            slot = schedule[ref['slide'] - 1]
            assert slot['end_seconds'] - slot['start_seconds'] >= durations[ref['path']], ref
            assert ' loop ' not in slides[ref['slide'] - 1], ref
    assert demo_seconds == 109, demo_seconds
    links = []
    for deck in DECKS:
        source = ROOT / 'source' / f'{deck}.md'
        content = source.read_text(encoding='utf-8-sig')
        for ref in set(re.findall(r'(?:src|poster)="([^"]+)"', content)):
            path = (source.parent / html.unescape(ref)).resolve()
            assert path.is_file(), str(path)
            links.append({'path': path.relative_to(ROOT).as_posix(), 'sha256': digest(path)})
        generated = (ROOT / f'{deck}.html').read_text(encoding='utf-8')
        assert 'src="../assets/' not in generated and 'poster="../assets/' not in generated
        theme = re.search(r'^theme:\s*(\S+)\s*$', content, re.M)
        assert theme, f'Missing theme in {deck}'
        css = ROOT / 'source/theme.css'
        assert css.is_file(), str(css)
        assert re.search(r'@theme\s+' + re.escape(theme[1]) + r'\b', css.read_text(encoding='utf-8'))
    links.append({'path': 'source/theme.css', 'sha256': digest(ROOT / 'source/theme.css')})
    figures = json.loads((ROOT / 'data/figures.json').read_text(encoding='utf-8-sig'))
    for rel, info in figures['inputs'].items():
        assert digest(REPO / rel) == info['sha256'], rel
    for asset in figures['assets']:
        assert digest(REPO / asset['path']) == asset['sha256'], asset['path']
    panels = json.loads((ROOT / 'data/results-panels.json').read_text(encoding='utf-8-sig'))
    for rel, sha in {**panels['inputs'], **panels['outputs']}.items():
        assert digest(REPO / rel) == sha, rel
    record = {'main_slides': len(slides), 'appendix_slides': len(appendix),
              'duration_target_seconds': last, 'demo_seconds': demo_seconds,
              'timing_status': 'rehearsal target, not measured narration',
              'spoken_word_count': sum(row['spoken_words'] for row in schedule), 'schedule': schedule,
              'all_media_links_exist': True, 'asset_hashes': links, 'renderer_launched': False,
              'figure_source_hashes_verified': len(figures['inputs']), 'figure_output_hashes_verified': len(figures['assets']),
              'video_hashes_and_decode_receipts_verified': len(media['entries']),
              'current_media_index': 'data/current-media.json',
              'decode_verification': 'Pinned historical full-decode receipts bound to unchanged current MP4 hashes; no fresh decode'}
    build = ROOT / 'build'
    build.mkdir(parents=True, exist_ok=True)
    (build / 'verification.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    (build / 'rehearsal-script.md').write_text(
        '# Speech manuscript\n\nRehearsal target **4:40**. Speak the prose. The cues give slide changes and video landmarks.\n\n'
        + '\n\n'.join(spoken) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in record.items() if key not in ('schedule', 'asset_hashes')}))


if __name__ == '__main__':
    verify()