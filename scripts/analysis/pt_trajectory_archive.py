"""Read-only integrity and optional full-video decoding for the compact PT archive."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from records.archive import child, read, require, verify_inventory
from records.provenance import sha256 as sha

DEFAULT = ROOT / 'runs/pt-4-trajectories-spatial-compare'
VIEWS = {'classroom', 'bistro-interior', 'bistro-exterior', 'zero-day'}
METHODS = {'baseline', 'pdf-similarity', 'cgns'}
CAPABILITIES = {'final_video_playback': True, 'timing_reanalysis': True, 'raw_production_hdr': False,
                'full_frame_reencoding': False, 'motion_validation_raw_aovs': True}

def check_inventory(root, manifest):
    require(child(root, "archive-manifest.json").is_file(), "Missing archive file: archive-manifest.json")
    require(manifest.get('capabilities') == CAPABILITIES, 'Incorrect retained capabilities')
    records = verify_inventory(
        root, manifest['files'], allowed_unindexed={'archive-manifest.json'},
        changed_message='Changed file', extra_message='Missing or unindexed files',
    )
    require(all(n.startswith('validation/') for n in records if Path(n).suffix.lower() == '.exr'), 'Unexpected production HDR')
    return records

def check_timing(rows, raw, watermarks):
    require(len(rows) == len(watermarks) == 300, 'Incomplete video timing coverage')
    raw_rows = {r['gpu_measured_frame']: r for r in raw if r.get('gpu_measured_frame') in range(41, 341)}
    require(len(raw_rows) == 300, 'Incomplete native timing coverage')
    require(sum(r.get('gpu_measured_frame') in range(41, 341) for r in raw) == 300, 'Duplicate native timing frames')
    for i, (row, watermark) in enumerate(zip(rows, watermarks)):
        require(row['frame'] == i+41 and row['video_frame'] == watermark['video_frame'] == i, 'Timing alignment mismatch')
        require(abs(row['video_time_seconds']-i/30) < 1e-9, 'Incorrect video time')
        events = raw_rows[i+41]['events_previous_frame']
        for name, value in row['gpu_events_ms'].items():
            require(math.isfinite(value) and value == events[name]['value'], 'Stage timing mismatch')
        ms = events['/onFrameRender/gpu_time']['value']
        require(math.isfinite(ms) and ms > 0 and ms == row['gpu_ms_raw'], 'Invalid raw GPU time')
        window = rows[max(0,i-14):i+1]
        mean = sum(r['gpu_ms_raw'] for r in window)/len(window)
        require(row['smoothing_frames'] == len(window), 'Incorrect smoothing window')
        require(math.isclose(row['gpu_ms_mean15'], mean, rel_tol=1e-12), 'Smoothed GPU time mismatch')
        require(math.isclose(row['gpu_fps_mean15'], 1000/mean, rel_tol=1e-12), 'GPU FPS mismatch')
        suffix = f'GPU {mean:.2f} ms | {1000/mean:.2f} GPU FPS | Playback 30 FPS'
        require(watermark['label'].endswith(suffix), 'Watermark/timing mismatch')

def check_probe(probe):
    require((probe['codec_name'], probe['width'], probe['height'], probe['pix_fmt'], probe['r_frame_rate'],
             int(probe['nb_read_frames']), float(probe['duration'])) ==
            ('h264', 1920, 1080, 'yuv420p', '30/1', 300, 10.0), 'Unexpected video format')

def verify(root=DEFAULT, decode=False):
    root = Path(root).resolve()
    m = read(root / 'archive-manifest.json')
    require(m['kind'] == 'falcor_pt_trajectory_media_archive' and m['schema_version'] == 1, 'Unsupported archive')
    require(set(m['views']) == VIEWS and set(m['methods']) == METHODS, 'Unexpected experiment coverage')
    indexed = check_inventory(root,m)
    original = read(child(root,m['production_manifest']))
    require(original['status'] == 'completed' and len(original['jobs']) == 12, 'Incomplete production')
    require({(j['trajectory'], j['method']) for j in original['jobs']} == {(v,t) for v in VIEWS for t in METHODS}, 'Missing/duplicate job')
    retired = {r['source']: r for r in read(root/'records/retired-files.json')}
    require(len(retired) == 10807, 'Retired-file coverage mismatch')
    relocated = read(root/'records/relocations.json')
    for r in relocated:
        require(all(indexed[r['path']][k] == r[k] for k in ('sha256','bytes')), 'Relocation mismatch')
    require(len(retired)+len(relocated) == read(root/'records/source-verification.json')['hashed_source_files'], 'Incomplete disposition inventory')
    original_prefix = 'runs/pt-4-trajectories-spatial-compare-20261116/'
    videos = []
    route_hashes = {}
    for job in original['jobs']:
        view, method = job['trajectory'], job['method']
        prefix = f'{view}/{method}'
        require(job['status'] == 'completed', 'Incomplete job')
        for phase,info in job['phases'].items():
            manifest_path = child(root, info['manifest'])
            require(sha(manifest_path) == info['sha256'], 'Historical manifest changed')
            phase_m = read(manifest_path)
            for a in phase_m['artifacts']:
                rel = f'{prefix}/{phase}/{a["path"]}'
                record = indexed.get(rel) or retired.get(original_prefix+rel)
                require(record is not None and record['sha256'] == a['sha256'], 'Artifact evidence mismatch: '+rel)
        base = root/prefix
        capture,timing,encode = [read(base/p/'manifest.json') for p in ('capture','timing','encode')]
        for key in ('trajectory_sha256','requested_method','requested_graph_options','resolution','temporal_reuse','experiment_config_sha256','scene_config_sha256'):
            require(capture[key] == timing[key], 'Capture/timing mismatch: '+key)
        require(capture['resolution'] == [1920,1080] and capture['warmup_frames'] == 40 and capture['temporal_reuse'], 'Capture schedule mismatch')
        require(capture['trajectory_sha256'] == encode['trajectory_sha256'], 'Encode trajectory mismatch')
        route_hashes.setdefault(view,set()).add(encode['trajectory_sha256'])
        rows = read(base/'timing/gpu-frame-timings.json')
        require(rows == read(base/'encode/gpu-frame-timings.json'), 'Timing copy mismatch')
        val = read(base/'timing/timing-validation.json')
        require(val['measured_gpu_frames'] == list(range(41,341)) and val['profiler_latency_frames'] == 1, 'Profiler alignment mismatch')
        require(sha(base/'timing/timings.json') == val['sha256'], 'Native timing digest mismatch')
        check_timing(rows,read(base/'timing/timings.json'),read(base/'encode/watermarks.json'))
        check_probe(read(base/'encode/video-probe.json')['streams'][0])
        video = base/'encode/video.mp4'
        if decode:
            probe = subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-count_frames','-show_entries',
                'stream=codec_name,width,height,pix_fmt,r_frame_rate,nb_read_frames,duration','-of','json',str(video)],
                capture_output=True,text=True,check=True)
            check_probe(json.loads(probe.stdout)['streams'][0])
            result = subprocess.run(['ffmpeg','-hide_banner','-v','error','-nostdin','-xerror','-err_detect','explode',
                '-i',str(video),'-map','0:v:0','-an','-f','null','-'],capture_output=True,text=True,check=True)
            require(not result.stderr.strip(),'Video decode reported errors')
        videos.append({'path':video.relative_to(root).as_posix(),'sha256':sha(video),'full_decode_passed':decode})
    require(all(len(h)==1 for h in route_hashes.values()), 'Methods use different trajectories')
    diagnostics = [p for p in indexed if p.startswith('validation/') and p.endswith('.exr')]
    require(len(diagnostics)==560,'Diagnostic AOVs missing')
    outcomes={}
    for trial in ('classroom','classroom-walking','bistro-walking','bistro-walking-320'):
        d = root / 'validation' / trial
        outcomes[trial] = read(d / 'manifest.json')['status']
        require(outcomes[trial] == ('failed' if trial=='bistro-walking' else 'completed'),'Diagnostic outcome changed')
        if trial!='bistro-walking':
            s = read(d / 'motion-summary.json')
            require(s['status'] == 'passed', 'Invalid motion summary')
            for a in s['artifacts']:
                require(indexed[f'validation/{trial}/{a["path"]}']['sha256']==a['sha256'],'Diagnostic evidence changed')
    return {'status':'verified','hashed_archive_files':len(indexed),'final_videos':12,'video_timing_rows':3600,
            'retained_diagnostic_exrs':560,'historical_motion_outcomes':outcomes,'retired_files':len(retired),
            'full_video_decode':decode,'videos':videos,'renderer_launched':False}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=DEFAULT)
    p.add_argument('--decode', action='store_true')
    a = p.parse_args()
    print(json.dumps(verify(a.root,a.decode),indent=2))

if __name__ == '__main__':
    main()
