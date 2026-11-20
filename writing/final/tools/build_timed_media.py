"""Build the timed release from approved previews and retained renderer videos."""
from io import BytesIO
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw, ImageFont

import build_media as course
import presentation_media as current

ROOT, REPO = course.ROOT, course.REPO
ASSETS = ROOT / 'assets/videos'
RESULTS = 'cgns-nrd-results'
ORDER = ('bistro-interior', 'bistro-exterior', 'zero-day', 'classroom')
TITLES = ('Bistro Interior', 'Bistro Exterior', 'Zero Day Measure Seven', 'Classroom')
PREVIEWS = {
    'bistro-interior': ('bistro-interior-fps-2s-7s.mp4', (60, 210),
        '935c36bc79d2edbe00f41d341bbc8aed58ce00d221bfe5ffbb1b445766c45c91'),
    'bistro-exterior': ('bistro-exterior-fps-pauses.mp4', (190, 299),
        '45f1579f1f4a80ed288bec03fefa37c4371c93b2b9cee1fc961e8d2783a093de'),
}
COLORS = ('#30231D', '#785385', '#AC4E24')
INK, CREAM, MUTED = '#2D1C13', '#F3ECE2', '#594A40'
SIZE, FPS = (1920, 1080), 30


def font(size):
    path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/bahnschrift.ttf'
    face = ImageFont.truetype(str(path), size)
    face.set_variation_by_name('Bold')
    return face


def pinned(path, expected):
    current._check_file(path, expected, 'timed-media source')
    return {'path': course.relative(path), 'sha256': expected}


def frame(path, index, filters=()):
    chain = ','.join((f'select=eq(n\\,{index})', *filters))
    png = subprocess.check_output(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path),
        '-vf', chain, '-frames:v', '1', '-f', 'image2pipe', '-c:v', 'png', 'pipe:1'])
    return Image.open(BytesIO(png)).convert('RGB')


def chart(title, timings):
    left, right, top, bottom = 804, 1824, 54, 149
    values = [[row['gpu_fps_mean15'] for row in rows] for rows in timings]
    low_raw = min(min(line) for line in values)
    high_raw = max(max(line) for line in values)
    tick = max(1, math.ceil((high_raw - low_raw) / 6))
    low = math.floor(low_raw / tick) * tick
    high = max(math.ceil(high_raw / tick) * tick, low + 3 * tick)
    scale = 2

    def points(index, value):
        return (round(left + (right - left) * index / 300) * scale,
                round(bottom - (bottom - top) * (value - low) / (high - low)) * scale)

    base = Image.new('RGB', (1920 * scale, 304 * scale), 'white')
    draw = ImageDraw.Draw(base)

    def text(x, y, message, size, fill=INK, anchor='lt'):
        draw.text((x * scale, y * scale), message, font=font(size * scale), fill=fill, anchor=anchor)

    draw.rectangle((0, 0, 1920 * scale - 1, 198 * scale), fill=CREAM)
    draw.line((0, 199 * scale, 1920 * scale, 199 * scale), fill='#E5D9CD', width=2)
    text(74, 99, title, 57, anchor='lm')
    text(left, 16, 'GPU FPS', 29)
    text(right, 19, 'Trajectory time (s)', 23, MUTED, 'rt')
    for tick_value in range(low, high + 1, tick):
        _, y = points(0, tick_value)
        draw.line((left * scale, y, right * scale, y), fill='#DED2C6', width=2)
        text(left - 16, y // scale, str(tick_value), 21, MUTED, 'rm')
    for second in range(0, 11, 2):
        x, _ = points(second * FPS, low)
        draw.line((x, bottom * scale, x, (bottom + 5) * scale), fill='#AD9988', width=2)
        text(x // scale, 161, str(second), 22, MUTED, 'mt')
    for x, name, color in zip((328, 960, 1592), course.LABELS, COLORS):
        text(x, 245, name, 41, color, 'mm')
    traces = [[points(i, y) for i, y in enumerate(line)] for line in values]

    def draw_frame(index):
        page = base.copy()
        draw = ImageDraw.Draw(page)
        x = traces[0][index][0]
        draw.line((x, top * scale, x, bottom * scale), fill='#AA9989', width=2)
        for trace, color in zip(traces, COLORS):
            if index:
                draw.line(trace[:index+1], fill=color, width=6, joint='curve')
        for trace, color, radius in zip(traces, COLORS, (10, 7, 4)):
            x, y = trace[index]
            radius *= scale
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), outline='white', width=5)
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), outline=color, width=3)
        return page.resize((1920, 304), Image.Resampling.LANCZOS).tobytes()

    return draw_frame


def encode_comparison(scene, target):
    archive = current.read_json(course.SOURCE / 'manifest.json')
    records, timing = course.source_records(scene, archive)
    legacy = current.read_json(ROOT / 'data' / f'{scene}-course-v2.json')
    source = REPO / legacy['output']
    inputs = [pinned(source, legacy['output_sha256'])]
    inputs.extend(x['artifacts']['gpu-frame-timings.json'] for x in records)
    draw_frame = chart(TITLES[ORDER.index(scene)], timing)
    command = ['ffmpeg','-v','error','-nostdin','-y','-i',str(source),'-f','rawvideo',
               '-pixel_format','rgb24','-video_size','1920x304','-framerate','30','-i','pipe:0',
               '-filter_complex','[0:v][1:v]overlay=0:0:shortest=1[out]','-map','[out]',
               '-an','-frames:v','300','-c:v','libx264','-threads','4','-preset','fast',
               '-crf','17','-pix_fmt','yuv420p','-movflags','+faststart',str(target)]
    with subprocess.Popen(command, stdin=subprocess.PIPE) as process:
        try:
            for index in range(300):
                process.stdin.write(draw_frame(index))
        finally:
            process.stdin.close()
        if process.wait():
            raise RuntimeError(f'FPS overlay encode failed for {scene}')
    return inputs


def results_video(target, poster):
    root = REPO / 'runs/pt-denoiser-showcase-20261119'
    sources, paths = [], []
    for scene in ORDER:
        folder = root / f'{scene}-nrd'
        if scene == 'bistro-exterior':
            folder = REPO / 'runs/bistro-exterior-cgns-nrd-preview-20261119'
        evidence = current.read_json(folder / 'preview-manifest.json')
        source = folder / f'{scene}-cgns-nrd.mp4'
        if evidence['status'] != 'completed' or evidence['video_probe']['nb_read_frames'] != '300':
            raise ValueError(f'Incomplete NRD video for {scene}')
        sources.append(pinned(source, evidence['video_sha256']))
        paths.append(source)
    with TemporaryDirectory(prefix='nrd-headers-', dir=ROOT / 'build') as folder:
        command = ['ffmpeg','-v','error','-nostdin','-y']
        for path in paths:
            command += ['-threads','2','-i',str(path)]
        for i,title in enumerate(TITLES):
            header = Image.new('RGB',(1920,72),CREAM)
            draw = ImageDraw.Draw(header)
            draw.text((64,36),title,font=font(36),fill=INK,anchor='lm')
            draw.text((1856,36),'CGNS + NRD',font=font(34),fill=COLORS[-1],anchor='rm')
            title_png = Path(folder) / f'{i}.png'
            header.save(title_png)
            command += ['-framerate','30','-i',str(title_png)]
        videos = [
            f'[{i}:v]scale=1792:1008:flags=lanczos,pad=1920:1080:64:72:color=white,'
            f'setsar=1,setpts=PTS-STARTPTS[scene{i}];'
            f'[scene{i}][{i+len(TITLES)}:v]overlay=eof_action=repeat:repeatlast=1[v{i}]'
            for i in range(len(TITLES))]
        command += ['-filter_complex_threads','2','-filter_complex',';'.join(videos) +
                    ';[v0][v1][v2][v3]concat=n=4:v=1:a=0[out]','-map','[out]','-an','-frames:v','1200',
                    '-r','30','-c:v','libx264','-threads','4','-preset','fast','-crf','17',
                    '-pix_fmt','yuv420p','-movflags','+faststart',str(target)]
        subprocess.run(command,check=True,cwd=REPO)

    board = Image.new('RGB', SIZE, 'white')
    d = ImageDraw.Draw(board)
    d.rectangle((0,0,1919,83),fill=CREAM)
    d.text((60,40),'Final renders with CGNS + NRD',font=font(42),fill=INK,anchor='lm')
    for i,(title,source) in enumerate(zip(TITLES, paths)):
        x = 60 + (i % 2) * 921
        y = 122 + (i // 2) * 478
        picture = frame(source,150).resize((817,460), Image.Resampling.LANCZOS)
        board.paste(picture,(x,y))
        d.text((x,y-8),title,font=font(25),fill=MUTED,anchor='ls')
    board.save(poster)
    return sources


def motivation():
    source = course.SOURCE / 'bistro-exterior/baseline/encode/video.mp4'
    evidence = current.read_json(source.with_name('manifest.json'))
    expected = next(x['sha256'] for x in evidence['artifacts'] if x['path'] == source.name)
    origin = pinned(source, expected)
    output = ROOT / 'assets/figures/bistro-shadow-boundary.png'
    picture = frame(source,150,('crop=640:360:640:600',))
    draw = ImageDraw.Draw(picture)
    for x,y,character,fill,tx,ty in ((400,132,'A','#30231D',424,106),(400,155,'B','#AC4E24',427,174)):
        draw.line((x,y,tx,ty),fill=fill,width=3)
        draw.ellipse((x-6,y-6,x+6,y+6),fill=fill,outline='white',width=2)
        draw.ellipse((tx-11,ty-11,tx+11,ty+11),fill=fill,outline='white',width=2)
        draw.text((tx,ty),character,font=font(14),fill='white',anchor='mm')
    picture.save(output)
    course.write_json(ROOT / 'data/bistro-shadow-boundary.json', {
        'origin':origin,'video_frame':150,'crop_xywh':[640,600,640,360],
        'marker_xy':[[400,132],[400,155]],'output':course.relative(output),
        'sha256':course.digest(output)})


def make(scene, force):
    stem = RESULTS if scene == RESULTS else f'{scene}-fps'
    target, poster = (ASSETS / f'{stem}.{ext}' for ext in ('mp4','png'))
    receipt_path = ROOT / 'data' / f'{stem}.json'
    if not force and all(p.exists() for p in (target,poster,receipt_path)):
        receipt = current.read_json(receipt_path)
        if (course.digest(target),course.digest(poster)) == (receipt['output_sha256'],receipt['poster_sha256']):
            return
    frames, holds = 300, ()
    if scene in PREVIEWS:
        name, holds, checksum = PREVIEWS[scene]
        source = ROOT / 'build/presentation-preview-20261119' / name
        origins = [pinned(source, checksum)]
        shutil.copyfile(source,target)
        frames = 420
    elif scene == RESULTS:
        origins = results_video(target, poster)
        frames = 1200
    else:
        origins = encode_comparison(scene,target)
    if scene != RESULTS:
        frame(target,holds[0] if holds else 150).save(poster)
    receipt = {'scene':scene,'sources':origins,'frame_count':frames,
               'hold_source_frames':list(holds),'hold_added_frames':60 if holds else 0,
               'output':course.relative(target),'output_sha256':course.digest(target),
               'poster':course.relative(poster),'poster_sha256':course.digest(poster),
               'probe':course.probe(target,frames),'decode':course.decode(target)}
    course.write_json(receipt_path,receipt)
    print(f'Verified {stem}: {frames} frames',flush=True)


def build(scene=None, force=False):
    for name in (*ORDER,RESULTS):
        if not scene or name == scene:
            make(name, force)
    if not scene:
        motivation()
    index = current.create_index(ROOT)
    course.write_json(ROOT / current.INDEX,index)
    return index
