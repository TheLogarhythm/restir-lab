"""Encode presentation derivatives; never modify the archived PNGs."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
ARCHIVE = REPO / 'runs/pdf-similarity-archive/artifacts/raw'
CONDITIONS = ('arcade-motion', 'bistro-interior-motion', 'bistro-exterior-motion', 'bistro-lighting')
FPS = 30
FRAMES = 96


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def probe(path):
    return json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
        '-show_entries', 'stream=width,height,r_frame_rate,nb_read_frames,duration,codec_name',
        '-of', 'json', str(path)], text=True))['streams'][0]


def encode(condition, kind, force=False):
    output = ROOT / 'assets/videos' / condition / (kind + '.mp4')
    output.parent.mkdir(parents=True, exist_ok=True)
    inputs = ['pdf-on', 'pdf-off'] if kind == 'comparison' else [kind]
    files = [ARCHIVE / condition / 'frames' / method / f'frame-{i:04d}.png'
             for method in inputs for i in range(1, FRAMES + 1)]
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(path)
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y']
    for method in inputs:
        command += ['-framerate', str(FPS), '-start_number', '1', '-i',
                    str(ARCHIVE / condition / 'frames' / method / 'frame-%04d.png')]
    color = 'scale=in_range=full:out_range=tv:out_color_matrix=bt709,format=yuv420p'
    if kind == 'comparison':
        # Top of divider is to the RIGHT of its bottom: `/`. On is left.
        # Extra travel puts the entire divider beyond the frame at both ends.
        boundary = '(-0.01+1.26*T/(95/30)-0.24*Y/H)*W'
        expr = f'if(lt(abs(X-({boundary})),1.6*W/1920),255,if(lt(X,({boundary})),A,B))'
        font = r"C\:/Windows/Fonts/segoeui.ttf"
        labels = (f"drawtext=fontfile='{font}':text='PDF ON':x=32:y=28:fontsize=28:"
                  "fontcolor=white:box=1:boxcolor=black@0.60:boxborderw=10:enable='gte(t,0.34)',"
                  f"drawtext=fontfile='{font}':text='PDF OFF':x=w-tw-32:y=28:fontsize=28:"
                  "fontcolor=white:box=1:boxcolor=black@0.60:boxborderw=10:enable='lte(t,2.33)'")
        filters = f"[0:v]format=gbrp[on];[1:v]format=gbrp[off];[on][off]blend=all_expr='{expr}',{labels},{color}[out]"
        command += ['-filter_complex', filters, '-map', '[out]']
    else:
        command += ['-vf', color]
    command += ['-frames:v', str(FRAMES), '-an', '-c:v', 'libx264', '-preset', 'slow',
                '-crf', '20', '-pix_fmt', 'yuv420p', '-g', '30', '-keyint_min', '30',
                '-sc_threshold', '0', '-color_primaries', 'bt709', '-colorspace', 'bt709',
                '-color_trc', 'iec61966-2-1', '-movflags', '+faststart', str(output)]
    source_records=[dict(path=f.relative_to(REPO).as_posix(), sha256=digest(f)) for f in files]
    receipt=ROOT/'data/media.json'
    previous=next((e for e in json.loads(receipt.read_text())['entries'] if e['path']==output.relative_to(ROOT).as_posix()),None) if receipt.exists() else None
    reusable=output.is_file() and previous and previous['command']==command and previous['sources']==source_records and previous['sha256']==digest(output)
    if force or not reusable:
        print(f'Encoding {condition}/{kind}', flush=True)
        subprocess.run(command, check=True)
    info = probe(output)
    assert (info['width'], info['height'], int(info['nb_read_frames']), info['r_frame_rate']) == (1920, 1080, 96, '30/1'), info
    assert abs(float(info['duration']) - 3.2) < 0.0001, info
    return dict(path=output.relative_to(ROOT).as_posix(), condition=condition, kind=kind,
                sha256=digest(output), bytes=output.stat().st_size, probe=info,
                sources=source_records,
                command=command)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--condition', choices=CONDITIONS)
    args = parser.parse_args()
    entries = []
    for condition in ([args.condition] if args.condition else CONDITIONS):
        for kind in ('pdf-off', 'pdf-on', 'comparison'):
            entries.append(encode(condition, kind, args.force))
    receipt = ROOT / 'data/media.json'
    if args.condition and receipt.exists():
        entries = [e for e in json.loads(receipt.read_text())['entries'] if e['condition'] != args.condition] + entries
    receipt.parent.mkdir(exist_ok=True)
    poster=ROOT/'assets/results/bistro-exterior-motion-comparison.png'
    movie=ROOT/'assets/videos/bistro-exterior-motion/comparison.mp4'
    poster_record=None
    if movie.exists():
        poster.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-i',str(movie),
                        '-vf',r'select=eq(n\,47)','-frames:v','1',str(poster)],check=True)
        poster_record=dict(path=poster.relative_to(ROOT).as_posix(),sha256=digest(poster),source=movie.relative_to(ROOT).as_posix(),frame=48)
    receipt.write_text(json.dumps(dict(schema_version=1, role='lossy presentation derivatives; PNGs remain authoritative',
        frames=96, fps=30, width=1920, height=1080, divider='bottom-left to top-right /; left ON, right OFF',
        encoder=subprocess.check_output(['ffmpeg', '-version'], text=True).splitlines()[0],
        poster=poster_record, entries=entries), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'videos': len(entries), 'MiB': round(sum(e['bytes'] for e in entries)/1024**2, 2)}), flush=True)


if __name__ == '__main__':
    main()
