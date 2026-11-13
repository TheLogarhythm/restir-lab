"""Apply the point-only CGNS shader overlay to an isolated Falcor runtime.

Call only on a private runtime copy. CGNS is the overlay itself; the original
runtime is the baseline. The caller MUST enforce point reservoirs, unpaired
neighbors, compact retracing and four neighbors before running. Inserting this
selector does not change native path shifting, MIS, or rejection.
"""
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[2]
MODULE = Path('shaders/ReSTIRPathTracing')
SELECTOR = Path(__file__).with_name('cgns_point_selector.slang')
MARKER = 'LAB_CGNS_POINT_SELECTOR_V1'
FILES = {
    'ResamplingCommon.slang': 0,
    'GenerateRetraceWorkload.cs.slang': 1,
    'SpatialPathRetrace.cs.slang': 2,
    'SpatialResampling.cs.slang': 1,
}

def _sha(data):
    return hashlib.sha256(data).hexdigest()

def build_overlay(sources, selector):
    """Return verified modified source strings without modifying input."""
    if set(sources) != set(FILES) or MARKER not in selector:
        raise ValueError('Unexpected source set or selector marker')
    if any(MARKER in text for text in sources.values()):
        raise ValueError('Overlay already present')
    result = dict(sources)
    common = sources['ResamplingCommon.slang']
    import_anchor = 'import Utils.Sampling.SampleGenerator;'
    marker_anchor = '// Retrace the primary ray for reused sample at different pixel (domain)'
    if common.count(import_anchor) != 1 or common.count(marker_anchor) != 1:
        raise ValueError('Unexpected common shader structure')
    common = common.replace(import_anchor, import_anchor + '\nimport Utils.Sampling.TinyUniformSampleGenerator;', 1)
    result['ResamplingCommon.slang'] = common.replace(marker_anchor, selector + '\n\n' + marker_anchor, 1)
    inject = ('float spatialRadius = gGatherRadius;\n'
              '        // ' + MARKER + '\n'
              '        LabCgnsPointSelection labCgnsSelected = labCgnsSelectPointNeighbors('
              'params, vbuffer, neighborOffsets, pixel, gSpatialRoundId, spatialRadius, gNeighborCount);')
    for name, expected in FILES.items():
        if not expected:
            continue
        text = sources[name]
        anchor = 'float spatialRadius = gGatherRadius;'
        if text.count(anchor) != expected:
            raise ValueError('Unexpected spatial setup in ' + name)
        text = text.replace(anchor, inject)
        # Both compact retrace and normal per-pixel paths have distinct index expressions.
        for index in ('retraceIndex / 2', 'i'):
            before = 'getNextNeighborPixel(startIndex, neighborOffsets, pixel, ' + index + ', spatialRadius)'
            after = 'labCgnsSelected.pixels[' + index + '] /* ' + MARKER + ' */'
            text = text.replace(before, after)
        if text.count('/* ' + MARKER + ' */') != expected or 'getNextNeighborPixel(' in text:
            raise ValueError('Unexpected neighbor consumers in ' + name)
        result[name] = text
    return result

def apply_overlay(runtime_root):
    runtime = Path(runtime_root).resolve(strict=True)
    module = runtime / MODULE
    source_module = ROOT / 'renderers/falcor/upstream/Source/Modules/ReSTIRPathTracing'
    if not module.is_dir() or not (runtime/'Mogwai.exe').is_file():
        raise ValueError('Expected an isolated Falcor runtime root')
    # Refuse source trees, build roots, and all known frozen reference runtimes.
    protected_roots = (ROOT/'renderers/falcor/upstream', ROOT/'build/falcor',
                       ROOT/'build/falcor-reference-runtime', ROOT/'build/falcor-gltf-composite-runtime-v3')
    if any(runtime.is_relative_to(p.resolve()) for p in protected_roots):
        raise ValueError('Refusing to alter a frozen runtime or upstream build')
    inputs = {}
    for name in FILES:
        data = (module/name).read_bytes()
        if data != (source_module/name).read_bytes():
            raise ValueError('Shader differs from pinned upstream: ' + name)
        inputs[name] = data.decode('utf-8')
    outputs = build_overlay(inputs, SELECTOR.read_text(encoding='utf-8'))
    receipt = {}
    for name in FILES:
        original = inputs[name].encode('utf-8')
        patched = outputs[name].encode('utf-8')
        (module/name).write_bytes(patched)
        receipt[(MODULE/name).as_posix()] = {'original_sha256': _sha(original), 'patched_sha256': _sha(patched)}
    return {'marker': MARKER, 'selector_sha256': _sha(SELECTOR.read_bytes()), 'files': receipt,
            'limitations': 'Point reservoirs, non-paired, compact retrace, 4 neighbors only. K=32; radius and settings enforced by caller. Recomputes the same list across GPU passes.'}
