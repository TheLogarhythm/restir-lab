"""Analyze paired single-frame Falcor ReSTIR PT captures against frozen HDR references.

Input paths may be absolute or relative to the manifest. Each pair is evaluated
individually; SMAPE is averaged across pair IDs, never after RGB averaging.
"""
import csv
import hashlib
import html
import json
from pathlib import Path
import re
import statistics

from PIL import Image
from src.image_io.exr import read_exr
from src.metrics.error_metrics import smape
from scripts.falcor.reference_extension_gallery import RECIPES, display
from scripts.analysis.relative_paths import rebase_record, relative_to_document

METRIC = {
    'name': 'luminance SMAPE',
    'formula': '100 * mean(abs(Y-Yref)/(abs(Y)+abs(Yref)+1e-4))',
    'luminance_rgb': [0.2126, 0.7152, 0.0722],
    'factor_two': False,
    'domain': 'unclipped scene-linear RGB, full image including background',
    'reduction': 'SMAPE per paired single frame, then equal mean over pairs',
    'relative_improvement': '100 * (mean baseline SMAPE - mean CGNS SMAPE) / mean baseline SMAPE',
    'provenance': 'restir-lab metric; exact author offline evaluation pipeline not verified',
}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _input(record, directory):
    if not isinstance(record, dict) or not isinstance(record.get('path'), str):
        raise ValueError('Each image requires path and sha256')
    digest = record.get('sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', digest):
        raise ValueError('Invalid image sha256')
    path = Path(record['path'])
    path = (path if path.is_absolute() else directory / path).resolve(strict=True)
    if not path.is_file() or sha(path) != digest.lower():
        raise ValueError('Image hash differs: ' + str(path))
    return {'path': str(path), 'sha256': digest.lower()}


def _read(record):
    path = Path(record['path'])
    if sha(path) != record['sha256']:
        raise ValueError('Image hash changed before read: ' + str(path))
    rgb = read_exr(path)
    if sha(path) != record['sha256']:
        raise ValueError('Image hash changed during read: ' + str(path))
    return rgb


def _pair_id(pair):
    value = pair.get('id')
    if type(value) is int and value >= 0:
        return value
    if type(value) is str and value.strip():
        return value
    raise ValueError('Pair id must be a nonnegative integer or nonempty string')


def _fmt(x):
    return 'n/a' if x is None else f'{x:.4f}'


def _write_preview(path, image, method, ev):
    Image.fromarray(display(image, method, ev)).save(path, format='PNG')
    return {'path': path.name, 'sha256': sha(path), 'transform': method, 'exposure_ev': ev}


def valid_settings(settings, temporal_required):
    return (isinstance(settings, dict)
            and settings.get('temporal_reuse') is temporal_required
            and type(settings.get('spp_per_frame')) is int
            and settings['spp_per_frame'] == 1)


def _analyze_view(view, source_directory, output, number, labels, checked):
    scene_id, view_id = view['scene_id'], view['view_id']
    first, second = labels
    first_metric, second_metric = first + '_smape_percent', second + '_smape_percent'
    pairs = view.get('pairs')
    if not isinstance(pairs, list) or not pairs:
        raise ValueError('A view requires at least one frame pair')
    reference = _input(view.get('reference'), source_directory)
    checked.append(reference)
    ref = _read(reference)
    method, ev = RECIPES.get((scene_id, view_id), ('reinhard', 0.0))
    previews = {
        'reference': _write_preview(
            output / f'view-{number:03d}-reference.png', ref, method, ev
        )
    }
    pair_results = []
    seen_ids = set()
    seen_by_method = {first: set(), second: set()}
    for index, pair in enumerate(pairs):
        if not isinstance(pair, dict):
            raise ValueError('Invalid frame pair')
        pair_id = _pair_id(pair)
        if pair_id in seen_ids:
            raise ValueError('Duplicate pair id')
        seen_ids.add(pair_id)
        item = {'id': pair_id}
        for label in labels:
            image_record = _input(pair.get(label), source_directory)
            if image_record['path'] in seen_by_method[label]:
                raise ValueError('Frame reused under multiple pair IDs')
            seen_by_method[label].add(image_record['path'])
            checked.append(image_record)
            image = _read(image_record)
            item[label] = rebase_record(image_record, source_directory, output)
            item[label + '_smape_percent'] = smape(image, ref)
            if index == 0:
                previews[label] = _write_preview(
                    output / f'view-{number:03d}-{label}.png', image, method, ev
                )
        item['improvement_percentage_points'] = item[first_metric] - item[second_metric]
        item['relative_improvement_percent'] = (
            100 * item['improvement_percentage_points'] / item[first_metric]
            if item[first_metric] else None
        )
        pair_results.append(item)
    avg_a = statistics.mean(pair[first_metric] for pair in pair_results)
    avg_b = statistics.mean(pair[second_metric] for pair in pair_results)
    difference = avg_a - avg_b
    sample_sd = (
        statistics.stdev(pair['improvement_percentage_points'] for pair in pair_results)
        if len(pair_results) > 1 else None
    )
    return {
        'scene_id': scene_id,
        'view_id': view_id,
        'reference': rebase_record(reference, source_directory, output),
        'pair_count': len(pair_results),
        'pairs': pair_results,
        first_metric: avg_a,
        second_metric: avg_b,
        'improvement_percentage_points': difference,
        'relative_improvement_percent': 100 * difference / avg_a if avg_a else None,
        'paired_difference_sample_sd_pp': sample_sd,
        'representative_pair_id': pair_results[0]['id'],
        'previews': previews,
    }


def _render_html(views, first, second, *, temporal_required, contrast):
    first_metric, second_metric = first + '_smape_percent', second + '_smape_percent'
    title = 'Falcor ReSTIR PT spatial comparison'
    heading = 'Falcor ReSTIR PT：spatial reuse 与 CGNS'
    description = '每帧 1 spp，关闭 temporal reuse；'
    first_caption, second_caption = '普通 spatial reuse', 'CGNS'
    summary_label = '普通 SMAPE '
    if contrast:
        title = 'Falcor ReSTIR PT temporal contrast'
        heading = 'Falcor ReSTIR PT：普通 spatial reuse temporal on / off'
        description = '每帧 1 spp，同一视角、普通 spatial reuse，比较 temporal reuse 开启与关闭；'
        first_caption = '普通 spatial reuse / temporal off'
        second_caption = '普通 spatial reuse / temporal on'
        summary_label = 'Temporal off SMAPE '
    elif temporal_required:
        description = (
            '每帧 1 spp，启用 temporal reuse；使用 point reservoirs，'
            '未启用 area reservoirs 或 reservoir splatting。'
        )
    description += (
        '逐帧计算全图线性 HDR 亮度 SMAPE，再对帧等权平均。'
        '预览仅用于显示，参考图有有限采样噪声。'
        '本项目指标与论文离线评估细节不保证完全一致。'
    )
    captions = (
        ('reference', 'Reference 16384 spp'),
        (first, first_caption),
        (second, second_caption),
    )
    sections = []
    for view in views:
        view_title = html.escape(view['scene_id'] + ' / ' + view['view_id'])
        cards = ''.join(
            '<figure><img src="'
            + html.escape(view['previews'][label]['path'], quote=True)
            + '"><figcaption>' + caption + '</figcaption></figure>'
            for label, caption in captions
        )
        summary = (
            f'{summary_label}{_fmt(view[first_metric])}% · '
            f'{second_caption} {_fmt(view[second_metric])}% · '
            f"改善 {_fmt(view['improvement_percentage_points'])} pp / "
            f"{_fmt(view['relative_improvement_percent'])}% · "
            f"{view['pair_count']} 帧；下图为第 "
            + html.escape(str(view['representative_pair_id'])) + ' 帧'
        )
        sections.append(
            '<section><h2>' + view_title + '</h2><p>' + summary
            + '</p><div class="grid">' + cards + '</div></section>'
        )
    style = (
        'body{background:#15191f;color:#eee;font:16px sans-serif;max-width:1600px;'
        'margin:30px auto;padding:0 18px}a{color:#9fcdff}'
        '.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}'
        'figure{margin:0}img{width:100%;height:auto}section{margin:32px 0}'
        '@media(max-width:700px){.grid{grid-template-columns:1fr}}'
    )
    return (
        '<!doctype html><html lang="zh"><meta charset="utf-8"><title>' + title
        + '</title><style>' + style + '</style><h1>' + heading + '</h1><p>'
        + description + '</p><p><a href="summary.json">完整数据</a> · '
        '<a href="summary.csv">汇总 CSV</a></p>' + ''.join(sections) + '</html>'
    )


def _write_reports(result, output, first, second, *, temporal_required, contrast):
    columns = (
        'scene_id', 'view_id', 'pair_count',
        first + '_smape_percent', second + '_smape_percent',
        'improvement_percentage_points', 'relative_improvement_percent',
        'paired_difference_sample_sd_pp',
    )
    with (output / 'summary.csv').open('x', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for view in result['views']:
            writer.writerow([view[key] for key in columns])
    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + '\n',
        encoding='utf8',
    )
    page = _render_html(
        result['views'], first, second,
        temporal_required=temporal_required, contrast=contrast,
    )
    (output / 'index.html').write_text(page, encoding='utf8')


def analyze(manifest_path, output, *, temporal_required=True, contrast=False):
    source = Path(manifest_path).resolve(strict=True)
    source_hash = sha(source)
    manifest = json.loads(source.read_text(encoding='utf-8-sig'))
    if sha(source) != source_hash:
        raise ValueError('Input manifest changed while reading')
    settings = manifest.get('settings')
    if contrast:
        if (not isinstance(settings, dict)
                or settings.get('comparison_kind') != 'baseline-temporal-on-off'
                or type(settings.get('spp_per_frame')) is not int
                or settings['spp_per_frame'] != 1):
            raise ValueError('Require baseline-temporal-on-off comparison and spp_per_frame=1')
    elif not valid_settings(settings, temporal_required):
        raise ValueError(
            f'Require temporal_reuse={str(temporal_required).lower()} and spp_per_frame=1'
        )
    labels = ('temporal_off', 'temporal_on') if contrast else ('baseline', 'cgns')
    metric = dict(METRIC)
    if contrast:
        metric['relative_improvement'] = (
            '100 * (mean temporal-off SMAPE - mean temporal-on SMAPE) / '
            'mean temporal-off SMAPE'
        )
    views = manifest.get('views')
    if not isinstance(views, list) or not views:
        raise ValueError('Require at least one view')
    if contrast and len(views) != 1:
        raise ValueError('Temporal contrast requires exactly one view')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report_settings = dict(settings)
    catalog = settings.get('source_catalog')
    if isinstance(catalog, dict) and isinstance(catalog.get('path'), str):
        report_settings['source_catalog'] = rebase_record(catalog, source.parent, output)
    kind = (
        'falcor_baseline_temporal_comparison' if contrast else
        'falcor_temporal_spatial_comparison' if temporal_required else
        'falcor_spatial_comparison'
    )
    result = {
        'schema_version': 1,
        'kind': kind,
        'metric': metric,
        'path_base': 'summary_directory',
        'settings': report_settings,
        'input_manifest': {
            'path': relative_to_document(source, output), 'sha256': source_hash,
        },
        'views': [],
    }
    seen_views = set()
    checked = []
    for number, view in enumerate(views, 1):
        if not isinstance(view, dict):
            raise ValueError('Invalid view')
        identity = (view.get('scene_id'), view.get('view_id'))
        if (any(not isinstance(value, str) or not value for value in identity)
                or identity in seen_views):
            raise ValueError('Invalid or duplicate view identity')
        seen_views.add(identity)
        result['views'].append(
            _analyze_view(view, source.parent, output, number, labels, checked)
        )
    if sha(source) != source_hash:
        raise ValueError('Input manifest changed during analysis')
    for item in checked:
        if sha(item['path']) != item['sha256']:
            raise ValueError('Input image changed during analysis: ' + item['path'])
    _write_reports(
        result, output, *labels, temporal_required=temporal_required, contrast=contrast
    )
    return output
