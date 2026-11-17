"""Build/cache the current course-style clips from approved encoded trajectories.

No renderer is launched. --check validates existing evidence, --index-only adopts
existing receipts without encoding, and --describe supplies browser/PPTX inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess

import presentation_media as current

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
SOURCE = REPO / 'runs/pt-4-trajectories-spatial-compare'
FPS, FRAMES, WIDTH, HEIGHT = 30, 300, 1920, 1080
METHODS = ('baseline', 'pdf-similarity', 'cgns')
LABELS = ('Bitterli et al. [2020]', 'PDF Similarity', 'CGNS')
SCENES = {
    'classroom': {'title': 'Classroom', 'crop': [640, 360, 640, 360],
                  'detail': 'Chalkboard, walls and desks'},
    'bistro-interior': {'title': 'Bistro Interior', 'crop': [1024, 640, 640, 360],
                        'detail': 'Floor, furniture and indirect light'},
    'bistro-exterior': {'title': 'Bistro Exterior', 'crop': [640, 600, 640, 360],
                        'detail': 'Facade, pavement and shadow edges'},
    'zero-day': {'title': 'Zero Day', 'crop': [256, 320, 640, 360],
                 'detail': 'Panels, machinery and dark surfaces'},
}


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(REPO.resolve()).as_posix()


def run(command: list[str], capture: bool = False):
    return subprocess.run(command, cwd=REPO, check=True, text=True,
                          capture_output=capture)


def probe(path: Path) -> dict:
    command = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
               '-show_entries', 'stream=width,height,r_frame_rate,avg_frame_rate,nb_read_frames,duration,codec_name,pix_fmt',
               '-of', 'json', relative(path)]
    info = json.loads(run(command, True).stdout)['streams'][0]
    expected = (WIDTH, HEIGHT, '30/1', '30/1', '300')
    actual = tuple(info[k] for k in ('width', 'height', 'r_frame_rate', 'avg_frame_rate', 'nb_read_frames'))
    if actual != expected or abs(float(info['duration']) - 10.0) > 1e-6:
        raise ValueError(f'Unexpected video format: {path}: {info}')
    return info


def decode(path: Path) -> dict:
    command = ['ffmpeg', '-hide_banner', '-v', 'error', '-nostdin', '-xerror',
               '-err_detect', 'explode', '-i', relative(path), '-map', '0:v:0',
               '-an', '-f', 'null', '-']
    result = run(command, True)
    if result.stderr.strip():
        raise ValueError(f'Decode reported errors: {path}: {result.stderr}')
    return {'command': command, 'exit_code': result.returncode,
            'stderr': result.stderr, 'all_frames_decoded': True}


def source_records(scene: str, production: dict):
    records, timing = [], []
    jobs = {(j['trajectory'], j['method']): j for j in production['jobs']}
    trajectory_hashes = []
    for method in METHODS:
        job = jobs[(scene, method)]
        if job['status'] != 'completed':
            raise ValueError(f'Unfinished production job: {scene}/{method}')
        folder = SOURCE / scene / method / 'encode'
        manifest_path = folder / 'manifest.json'
        expected_manifest = job['phases']['encode']['sha256']
        if digest(manifest_path) != expected_manifest:
            raise ValueError(f'Production manifest hash mismatch: {manifest_path}')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if (manifest['status'], manifest['frame_count'], manifest['resolution'],
            manifest['fps_playback'], manifest['duration_seconds']) != ('completed', 300, [1920, 1080], 30, 10):
            raise ValueError(f'Unexpected source settings: {manifest_path}')
        trajectory_hashes.append(manifest['trajectory_sha256'])
        artifacts = {a['path']: a for a in manifest['artifacts']}
        checks = {}
        for name in ('video.mp4', 'gpu-frame-timings.json', 'watermarks.json', 'video-probe.json'):
            path = folder / name
            sha = digest(path)
            if sha != artifacts[name]['sha256']:
                raise ValueError(f'Production artifact hash mismatch: {path}')
            checks[name] = {'path': relative(path), 'sha256': sha, 'bytes': path.stat().st_size}
        values = json.loads((folder / 'gpu-frame-timings.json').read_text(encoding='utf-8'))
        watermarks = json.loads((folder / 'watermarks.json').read_text(encoding='utf-8'))
        if len(values) != FRAMES or len(watermarks) != FRAMES:
            raise ValueError(f'Missing per-frame GPU timing: {folder}')
        for frame, (value, watermark) in enumerate(zip(values, watermarks)):
            if value['video_frame'] != frame or watermark['video_frame'] != frame:
                raise ValueError(f'Timing alignment mismatch: {folder}, {frame}')
            if abs(value['video_time_seconds'] - frame / FPS) > 1e-8:
                raise ValueError(f'Timing PTS mismatch: {folder}, {frame}')
            ms, gpu_fps = value['gpu_ms_mean15'], value['gpu_fps_mean15']
            if not (math.isfinite(ms) and math.isfinite(gpu_fps) and ms > 0 and gpu_fps > 0):
                raise ValueError(f'Invalid GPU timing: {folder}, {frame}')
            suffix = f'GPU {ms:.2f} ms | {gpu_fps:.2f} GPU FPS | Playback 30 FPS'
            if not watermark['label'].endswith(suffix):
                raise ValueError(f'GPU values disagree with original watermark: {folder}, {frame}')
        video = folder / 'video.mp4'
        records.append({'method': method, 'display_label': LABELS[METHODS.index(method)],
                        'manifest': {'path': relative(manifest_path), 'sha256': expected_manifest},
                        'artifacts': checks, 'probe': probe(video),
                        'display_transform': manifest['display_transform'],
                        'gpu_timing_source': manifest['gpu_timing_source'],
                        'gpu_total_event': manifest['gpu_total_event'],
                        'gpu_smoothing': manifest['gpu_smoothing'],
                        'trajectory_sha256': manifest['trajectory_sha256']})
        timing.append(values)
    if len(set(trajectory_hashes)) != 1:
        raise ValueError(f'Methods have different camera trajectories: {scene}')
    return records, timing


def ass_time(frame: int) -> str:
    # ASS uses centiseconds. Floor every boundary so the label is current at
    # each exact frame PTS n/30; nearest rounding can lag by one video frame.
    total = frame * 100 // FPS
    return f'{total // 360000}:{total // 6000 % 60:02d}:{total // 100 % 60:02d}.{total % 100:02d}'


COURSE_LAYOUT = {'full_view': [608, 342], 'detail_view': [608, 342],
                 'columns_x': [24, 656, 1288], 'full_y': 290, 'detail_y': 656,
                 'background': 'white', 'header': '#f4ece2', 'footer': '#23150e',
                 'crop_box': '#FF0080', 'crop_box_width_px': 4}


def ass_text(scene: str, timing: list) -> str:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Text,Arial,38,&H000E1523,&H000E1523,&H00FFFFFF,&H00FFFFFF,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Bold,Arial,42,&H000E1523,&H000E1523,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]

    def event(text, x, y, start=0, end=FRAMES, bold=False, size=38, color='0E1523', align=8):
        tag = f'\\an{align}\\pos({x},{y})\\fs{size}\\c&H{color}&'
        lines.append(f'Dialogue: 0,{ass_time(start)},{ass_time(end)},{"Bold" if bold else "Text"},,0,0,0,,{{{tag}}}{text}\n')

    event(SCENES[scene]['title'], 74, 48, bold=True, size=52, align=7)
    for i, label in enumerate(LABELS):
        center = 328 + i * 632
        event(label, center, 178, bold=True, size=42, color=['0E1523', '947381', '285CB6'][i])
        for frame, value in enumerate(timing[i]):
            event(f"GPU {value['gpu_ms_mean15']:.2f} ms | {value['gpu_fps_mean15']:.2f} GPU FPS",
                  center, 236, frame, frame + 1, size=36, color='4B5869')
    return ''.join(lines)


def command_for(scene: str, ass: Path, output: Path) -> list[str]:
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-filter_complex_threads', '1']
    for method in METHODS:
        command += ['-i', relative(SOURCE / scene / method / 'encode/video.mp4')]
    cx, cy, cw, ch = SCENES[scene]['crop']
    filters = []
    for i in range(3):
        filters.append(f'[{i}:v]trim=end_frame=300,setpts=N/(30*TB),split=2[f{i}][c{i}]')
        filters.append(f'[f{i}]scale=608:342:flags=lanczos,setsar=1,drawbox=x=0:y=0:w=608:h=18:color=white:t=fill,'
                       f'drawbox=x={cx*608/1920}:y={cy*342/1080}:w={cw*608/1920}:h={ch*342/1080}:color=0xff0080:t=4[full{i}]')
        filters.append(f'[c{i}]crop={cw}:{ch}:{cx}:{cy},scale=608:342:flags=lanczos,setsar=1[crop{i}]')
    filters.append('[full0][full1][full2][crop0][crop1][crop2]xstack=inputs=6:layout=24_290|656_290|1288_290|24_656|656_656|1288_656:fill=white[stack]')
    filters.append(f"[stack]pad=1920:1080:0:0:color=white,drawbox=x=0:y=0:w=1920:h=156:color=0xf4ece2:t=fill,"
                   f"drawbox=x=0:y=1050:w=1920:h=30:color=0x23150e:t=fill,ass=filename='{relative(ass)}',format=yuv420p[out]")
    command += ['-filter_complex', ';'.join(filters), '-map', '[out]', '-frames:v', '300', '-r', '30', '-an',
                '-c:v', 'libx264', '-preset', 'medium', '-crf', '16', '-pix_fmt', 'yuv420p', '-g', '30',
                '-movflags', '+faststart', relative(output)]
    return command


def recipe_identity(entry: dict, encoder: str) -> dict:
    """Validate every source byte and fingerprint inputs, recipe, fonts and scripts."""
    receipt_path = current.local_path(ROOT, entry['receipt']['path'])
    current._check_file(receipt_path, entry['receipt']['sha256'], 'receipt')
    receipt = current.read_json(receipt_path)
    scene = entry['scene']
    timing = []
    for source in receipt['sources']:
        for artifact in [source['manifest'], *source['artifacts'].values()]:
            current._check_file(REPO / artifact['path'], artifact['sha256'], 'approved source')
        timing.append(current.read_json(REPO / source['artifacts']['gpu-frame-timings.json']['path']))
    if [s['method'] for s in receipt['sources']] != list(METHODS):
        raise ValueError(f'Unexpected source methods: {scene}')
    # Historical Windows text output uses CRLF; keep those exact overlay bytes.
    overlays = ass_text(scene, timing).replace('\n', '\r\n').encode('utf-8')
    overlay_hash = hashlib.sha256(overlays).hexdigest()
    expected_command = command_for(scene, ROOT / entry['overlays']['path'], ROOT / entry['path'])
    return {'recipe': 'course-v2', 'sources': receipt['sources'],
            'production_manifest_sha256': digest(SOURCE / 'manifest.json'),
            'command': expected_command, 'layout': COURSE_LAYOUT, 'ass_sha256': overlay_hash,
            'encoder': encoder,
            'fonts': {font: digest(Path('C:/Windows/Fonts') / font) for font in ('arial.ttf', 'arialbd.ttf')},
            'scripts': {name: digest(Path(__file__).parent / name)
                        for name in ('build_media.py', 'presentation_media.py')}}


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def index_existing() -> dict:
    """Adopt only outputs whose old receipt exactly matches this course recipe."""
    index = current.create_index(ROOT)
    encoder = run(['ffmpeg', '-version'], True).stdout.splitlines()[0]
    for entry in index['entries']:
        receipt = current.read_json(ROOT / entry['receipt']['path'])
        identity = recipe_identity(entry, encoder)
        if (receipt['command'] != identity['command'] or receipt['layout'] != identity['layout']
                or receipt['ass_sha256'] != identity['ass_sha256']):
            raise ValueError(f'Historical receipt is not the current course recipe: {entry["path"]}')
        entry['build_identity'] = identity
        entry['cache_origin'] = 'Existing course-v2 output adopted after receipt/source/recipe validation; no encoding'
    write_json(ROOT / current.INDEX, index)
    return index


def build(index: dict, scene: str | None, force: bool) -> dict:
    encoder = run(['ffmpeg', '-version'], True).stdout.splitlines()[0]
    production = None
    for entry in index['entries']:
        if scene and entry['scene'] != scene:
            continue
        identity = recipe_identity(entry, encoder)
        if not force and current.reusable(entry, identity, ROOT):
            print(f'Reusing current course clip: {entry["path"]}', flush=True)
            continue
        if production is None:
            production = current.read_json(SOURCE / 'manifest.json')
            if production['status'] != 'completed' or len(production['jobs']) != 12:
                raise ValueError('Expected twelve completed approved production jobs')
        sources, timing = source_records(entry['scene'], production)
        output = ROOT / entry['path']
        poster = ROOT / entry['poster']['path']
        ass = ROOT / entry['overlays']['path']
        ass.write_bytes(ass_text(entry['scene'], timing).replace('\n', '\r\n').encode('utf-8'))
        command = command_for(entry['scene'], ass, output)
        print(f'Encoding current course clip: {entry["path"]}', flush=True)
        run(command)
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-i', relative(output),
             '-vf', 'select=eq(n\\,150)', '-frames:v', '1', relative(poster)])
        receipt = {'scene': entry['scene'], 'sources': sources, 'command': command,
                   'probe': probe(output), 'decode': decode(output), 'output': relative(output),
                   'output_sha256': digest(output), 'poster': relative(poster), 'poster_sha256': digest(poster),
                   'ass_sha256': digest(ass), 'layout': COURSE_LAYOUT,
                   'timing': 'Original per-frame mean15 GPU timing, unchanged; no retiming'}
        # New build receipts go under build/; original data/*-course-v2.json are history.
        receipt_path = ROOT / 'build/media-receipts' / f'{output.stem}-{receipt["output_sha256"][:16]}.json'
        write_json(receipt_path, receipt)
        ref = next(ref for ref in index['source_references'] if ref['path'] == entry['path'])
        updated = current._receipt_entry(ROOT, REPO, ref, receipt_path)
        updated['build_identity'] = recipe_identity(updated, encoder)
        entry.clear()
        entry.update(updated)
        write_json(ROOT / current.INDEX, index)
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', choices=SCENES)
    parser.add_argument('--force', action='store_true', help='Re-encode selected current clips')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='Validate current assets and pinned receipts without encoding')
    mode.add_argument('--index-only', action='store_true', help='Adopt existing course receipts; never encode')
    mode.add_argument('--describe', action='store_true', help='Print validated source-derived deck/video inputs as JSON')
    parser.add_argument('--pptx-inputs', type=Path, help='Write validated source-derived PPTX input JSON; never encode')
    args = parser.parse_args(argv)
    if args.force and (args.check or args.index_only or args.describe or args.pptx_inputs):
        parser.error('--force is only available when building media')
    if args.index_only:
        index = index_existing()
    else:
        # A build can restore a missing output; read-only modes require all assets.
        index = current.load_current_media(ROOT, verify_assets=bool(args.check or args.describe or args.pptx_inputs))
    if args.describe or args.pptx_inputs:
        inputs = current.presentation_inputs(ROOT)
        if args.pptx_inputs:
            write_json(args.pptx_inputs.resolve(), inputs)
        if args.describe:
            print(json.dumps(inputs))
        return
    if not args.check and not args.index_only:
        index = build(index, args.scene, args.force)
        current.load_current_media(ROOT)
    print(json.dumps({'current_videos': len(index['entries']), 'encoded': False if args.check or args.index_only else 'cache-dependent',
                      'index': current.INDEX, 'renderer_launched': False}))


if __name__ == '__main__':
    main()
