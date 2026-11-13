"""Recompute Falcor comparison reports from a relocated per-view catalog.

Run with --catalog <root>/manifest.json --mode temporal-on|temporal-off
--output <new-report-directory>. The generated input manifest is retained next
to the report; the catalog and all images are hash-checked and never modified.
"""
import argparse
import json
from pathlib import Path
import re

from scripts.analysis import falcor_spatial_comparison, falcor_temporal_comparison
from scripts.analysis.relative_paths import rebase_record, relative_to_document


FRAMES = tuple(range(41, 49))
MODES = ('temporal-on', 'temporal-off')
KIND = 'falcor_pt_spatial_view_catalog'
sha = falcor_temporal_comparison.sha


def _resolve(root, record):
    """Check a catalog-relative image or manifest path and its content hash."""
    if not isinstance(record, dict):
        raise ValueError('Expected file record')
    relative, expected = record.get('path'), record.get('sha256')
    if not isinstance(relative, str) or not relative:
        raise ValueError('Expected relative file path')
    path = Path(relative)
    if path.is_absolute() or path.drive or '..' in path.parts:
        raise ValueError('Path must remain within the catalog root')
    if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', expected):
        raise ValueError('Expected SHA-256')
    root = Path(root).resolve(strict=True)
    path = (root / path).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Path escapes catalog root or is not a file')
    if sha(path) != expected.lower():
        raise ValueError('File hash differs: ' + str(path))
    return {'path': str(path), 'sha256': expected.lower()}


def _method_frames(root, method, scene, view, mode, label):
    if not isinstance(method, dict):
        raise ValueError('Missing method records')
    metadata_record = _resolve(root, {'path': method.get('manifest'),
                                      'sha256': method.get('manifest_sha256')})
    metadata = json.loads(Path(metadata_record['path']).read_text(encoding='utf8'))
    graph = metadata.get('requested_graph_options', {}).get('reSTIRPathTracingOptions', {})
    actual_temporal = graph.get('useTemporalResampling')
    if (metadata.get('status') != 'completed'
            or metadata.get('scene_id') != scene or metadata.get('view_id') != view
            or metadata.get('requested_method') != ('baseline' if label == 'spatial' else 'cgns')
            or type(metadata.get('spp_per_frame')) is not int
            or metadata['spp_per_frame'] != 1
            or metadata.get('capture_frames') != list(FRAMES)
            or actual_temporal is not (mode == 'temporal-on')):
        raise ValueError('Render manifest settings do not match catalog')
    records = method.get('frames')
    if not isinstance(records, list) or len(records) != len(FRAMES):
        raise ValueError('Expected exactly eight frame records')
    by_id, paths = {}, set()
    for record in records:
        if not isinstance(record, dict) or type(record.get('frame')) is not int:
            raise ValueError('Invalid frame record')
        frame = record['frame']
        if frame not in FRAMES or frame in by_id:
            raise ValueError('Invalid or repeated frame number')
        resolved = _resolve(root, record)
        if resolved['path'] in paths:
            raise ValueError('Image reused for multiple frames')
        paths.add(resolved['path'])
        by_id[frame] = resolved
    return by_id


def build_analysis_input(catalog_path, mode, input_directory=None):
    """Validate the relocated catalog and construct a paired analysis input."""
    if mode not in MODES:
        raise ValueError('Unknown temporal mode')
    source = Path(catalog_path).resolve(strict=True)
    input_directory = Path(input_directory).resolve() if input_directory is not None else source.parent
    source_hash = sha(source)
    catalog = json.loads(source.read_text(encoding='utf8'))
    if (not isinstance(catalog, dict) or catalog.get('schema_version') != 1
            or catalog.get('kind') != KIND
            or not isinstance(catalog.get('views'), list) or not catalog['views']):
        raise ValueError('Invalid view catalog')
    result = {'path_base': 'input_directory',
              'settings': {'temporal_reuse': mode == 'temporal-on', 'spp_per_frame': 1,
                           'source_catalog': {'path': relative_to_document(source, input_directory), 'sha256': source_hash}},
              'views': []}
    seen = set()
    for view in catalog['views']:
        if not isinstance(view, dict):
            raise ValueError('Invalid view record')
        scene, view_id = view.get('scene_id'), view.get('view_id')
        if (not isinstance(scene, str) or not scene or not isinstance(view_id, str)
                or not view_id or (scene, view_id) in seen):
            raise ValueError('Invalid or repeated view')
        seen.add((scene, view_id))
        ref = _resolve(source.parent, view.get('reference'))
        methods = view.get('comparisons', {}).get(mode, {})
        if not isinstance(methods, dict):
            raise ValueError('Missing comparison')
        spatial = _method_frames(source.parent, methods.get('spatial'), scene, view_id, mode, 'spatial')
        cgns = _method_frames(source.parent, methods.get('cgns'), scene, view_id, mode, 'cgns')
        result['views'].append({'scene_id': scene, 'view_id': view_id,
                                'reference': rebase_record(ref, source.parent, input_directory),
                                'pairs': [{'id': n,
                                           'baseline': rebase_record(spatial[n], source.parent, input_directory),
                                           'cgns': rebase_record(cgns[n], source.parent, input_directory)}
                                          for n in FRAMES]})
    if sha(source) != source_hash:
        raise ValueError('Catalog changed while reading')
    return result


def analyze_catalog(catalog_path, mode, output):
    """Write a new report and retain its generated, hash-bound analysis input."""
    output = Path(output).absolute()
    if output.exists():
        raise FileExistsError('Report already exists: ' + str(output))
    input_path = output.parent / (output.name + '-input.json')
    if input_path.exists():
        raise FileExistsError('Analysis input already exists: ' + str(input_path))
    data = build_analysis_input(catalog_path, mode, input_path.parent)
    with input_path.open('x', encoding='utf8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')
    analyzer = falcor_temporal_comparison if mode == 'temporal-on' else falcor_spatial_comparison
    result = analyzer.analyze(input_path, output)
    source = data['settings']['source_catalog']
    if sha(input_path.parent / source['path']) != source['sha256']:
        raise ValueError('Catalog changed during analysis')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--mode', choices=MODES, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(analyze_catalog(args.catalog, args.mode, args.output))


if __name__ == '__main__':
    main()
