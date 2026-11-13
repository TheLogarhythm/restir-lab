"""Read and validate the shared Falcor PT spatial-comparison configuration.

The configuration describes a one-neighbor, point-reservoir implementation.
Unsupported graph variants are rejected instead of silently producing a run
that does not correspond to the configured algorithm. The returned dictionaries
are independent copies and can safely be passed to graph creation code.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / 'experiments/configs/falcor-pt-spatial-comparison/restir-pt-spatial-comparison.json'
_FLOAT32_MIN_NORMAL = 1.1754943508222875e-38


def _keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(label + ' must contain exactly: ' + ', '.join(sorted(expected)))


def _integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{label} must be an integer in [{minimum}, {maximum}]')


def _number(value, minimum, maximum, label, *, include_minimum=True):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(label + ' must be a finite number')
    if (value < minimum if include_minimum else value <= minimum) or value > maximum:
        raise ValueError(label + ' is outside the supported range')


def _fixed(value, expected, label):
    if type(value) is not type(expected) or value != expected:
        raise ValueError(f'{label} must be {expected!r} for this implementation')


def validate_cgns_shader(parameters):
    """Return an independent, normalized shader-parameter dict or raise."""
    fields = ('candidate_count', 'position_scale', 'normal_exponent',
              'early_stop_score', 'early_stop_count')
    _keys(parameters, fields, 'CGNS shader parameters')
    _integer(parameters['candidate_count'], 1, 32, 'candidate_count')
    _number(parameters['position_scale'], 0, 1e6, 'position_scale', include_minimum=False)
    _number(parameters['normal_exponent'], 0, 1e6, 'normal_exponent', include_minimum=False)
    _number(parameters['early_stop_score'], 0, 1, 'early_stop_score')
    for key in ('position_scale', 'normal_exponent', 'early_stop_score'):
        if 0 < parameters[key] < _FLOAT32_MIN_NORMAL:
            raise ValueError(key + ' is too small for reliable GPU float32 evaluation')
    _integer(parameters['early_stop_count'], 1, parameters['candidate_count'], 'early_stop_count')
    return {
        'candidate_count': parameters['candidate_count'],
        'position_scale': float(parameters['position_scale']),
        'normal_exponent': float(parameters['normal_exponent']),
        'early_stop_score': float(parameters['early_stop_score']),
        'early_stop_count': parameters['early_stop_count'],
    }


def validate_config(value):
    """Validate a parsed config and return a detached, normalized copy."""
    _keys(value, ('schema_version', 'name', 'reference_catalog', 'render',
                  'graph', 'temporal_modes', 'methods'), 'Experiment config')
    _fixed(value['schema_version'], 1, 'schema_version')
    if not isinstance(value['name'], str) or not value['name'].strip():
        raise ValueError('Experiment name must be nonempty')
    catalog = value['reference_catalog']
    if (not isinstance(catalog, str) or not catalog or PurePosixPath(catalog).is_absolute()
            or PureWindowsPath(catalog).is_absolute() or PureWindowsPath(catalog).drive
            or '..' in PurePosixPath(catalog).parts or '..' in PureWindowsPath(catalog).parts
            or '\\' in catalog or not PurePosixPath(catalog).parts
            or PurePosixPath(catalog).parts[0].lower() == 'runs'):
        raise ValueError('reference_catalog must be a workspace-relative path')

    render = value['render']
    _keys(render, ('width', 'height', 'warmup_frames', 'capture_count', 'image_accumulation'), 'render')
    # The only supported reference catalog contains 1920×1080 images. Fail
    # before preparing runtimes rather than compare different resolutions.
    _fixed(render['width'], 1920, 'render.width (frozen reference)')
    _fixed(render['height'], 1080, 'render.height (frozen reference)')
    _integer(render['warmup_frames'], 0, 512, 'render.warmup_frames')
    _integer(render['capture_count'], 1, 128, 'render.capture_count')
    _fixed(render['image_accumulation'], False, 'render.image_accumulation')

    graph = value['graph']
    _keys(graph, ('samplesPerPixel', 'sampleGenerator', 'tracePassMode', 'useReSTIRPT',
                  'useRTXDI', 'emissiveSampler', 'maxSurfaceBounces', 'maxDiffuseBounces',
                  'maxSpecularBounces', 'maxTransmissionBounces', 'useRussianRoulette',
                  'reSTIRPathTracingOptions'), 'graph')
    for key, expected in (('samplesPerPixel', 1), ('sampleGenerator', 0),
                          ('tracePassMode', 'MinimalPayload'), ('useReSTIRPT', True),
                          ('useRTXDI', False), ('emissiveSampler', 'Power')):
        _fixed(graph[key], expected, 'graph.' + key)
    # The current catalog provides references for exactly these transport
    # settings. Other integrands need corresponding new references.
    _fixed(graph['useRussianRoulette'], True, 'graph.useRussianRoulette')
    for key in ('maxSurfaceBounces', 'maxDiffuseBounces', 'maxSpecularBounces', 'maxTransmissionBounces'):
        _fixed(graph[key], 10, 'graph.' + key)

    reuse = graph['reSTIRPathTracingOptions']
    _keys(reuse, ('useAreaReservoirs', 'useSpatialResampling', 'spatialIterations',
                  'spatialNeighborCount', 'spatialGatherRadius', 'usePairedNeighbors',
                  'useDoFReconnectionShift', 'useDoFReconnectionForTemporalReuse',
                  'deriveDoFReconnectionShiftProbabilityFromCoC', 'maxHistoryLength'),
          'graph.reSTIRPathTracingOptions')
    for key, expected in (('useAreaReservoirs', False), ('useSpatialResampling', True),
                          ('spatialIterations', 1), ('spatialNeighborCount', 1),
                          ('usePairedNeighbors', False), ('useDoFReconnectionShift', False),
                          ('useDoFReconnectionForTemporalReuse', False),
                          ('deriveDoFReconnectionShiftProbabilityFromCoC', False)):
        _fixed(reuse[key], expected, 'graph.reSTIRPathTracingOptions.' + key)
    # Both are uint32 in Falcor's ReSTIRPathTracingOptions; the upper bounds
    # match the renderer's supported UI ranges.
    _integer(reuse['spatialGatherRadius'], 1, 200, 'spatialGatherRadius')
    _integer(reuse['maxHistoryLength'], 1, 100, 'maxHistoryLength')

    modes = value['temporal_modes']
    _keys(modes, ('temporal-on', 'temporal-off'), 'temporal_modes')
    _fixed(modes['temporal-on'], True, 'temporal_modes.temporal-on')
    _fixed(modes['temporal-off'], False, 'temporal_modes.temporal-off')
    methods = value['methods']
    _keys(methods, ('spatial', 'cgns'), 'methods')
    _keys(methods['spatial'], ('kind',), 'methods.spatial')
    _fixed(methods['spatial']['kind'], 'baseline', 'methods.spatial.kind')
    _keys(methods['cgns'], ('kind', 'shader'), 'methods.cgns')
    _fixed(methods['cgns']['kind'], 'cgns', 'methods.cgns.kind')
    result = deepcopy(value)
    result['methods']['cgns']['shader'] = validate_cgns_shader(methods['cgns']['shader'])
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Invalid JSON constant: ' + value)


def load_config_snapshot(path=DEFAULT_CONFIG):
    """Read once, hash exactly the consumed bytes and return (config, sha256)."""
    raw = Path(path).read_bytes()
    try:
        value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object,
                           parse_constant=_invalid_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid experiment JSON') from exc
    return validate_config(value), hashlib.sha256(raw).hexdigest()


def load_config(path=DEFAULT_CONFIG):
    return load_config_snapshot(path)[0]


def graph_options(config, mode, method):
    """Return the Falcor options for a method and temporal mode."""
    value = validate_config(config)
    if method not in ('baseline', 'cgns'):
        raise ValueError('Unknown comparison method')
    if mode not in value['temporal_modes']:
        raise ValueError('Unknown temporal mode')
    graph = deepcopy(value['graph'])
    graph['reSTIRPathTracingOptions']['useTemporalResampling'] = value['temporal_modes'][mode]
    return graph
