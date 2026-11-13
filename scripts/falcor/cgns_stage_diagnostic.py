"""Instrument an already-patched private point-CGNS runtime for GPU stage checks.

Exactly one selected slot's x/y is carried in unused validity-mask bits from
workload to compact retrace and resampling. Run separate diagnostics for slots
0..3. A mismatch emits an unmistakably high magenta radiance. Never use this
diagnostic overlay for comparison results. Requires width,height < 4095.
"""
from pathlib import Path
import hashlib
from .cgns_shader_overlay import MODULE, MARKER

DIAGNOSTIC_MARKER = 'LAB_CGNS_STAGE_DIAGNOSTIC_V1'
ANCHOR = ('LabCgnsPointSelection labCgnsSelected = labCgnsSelectPointNeighbors('
          'params, vbuffer, neighborOffsets, pixel, gSpatialRoundId, spatialRadius, gNeighborCount);')
FILES = ('ResamplingCommon.slang', 'GenerateRetraceWorkload.cs.slang',
         'SpatialPathRetrace.cs.slang', 'SpatialResampling.cs.slang')

def build_diagnostic(sources, slot, *, inject_fault=False):
    if type(slot) is not int or not 0 <= slot < 4:
        raise ValueError('Diagnostic slot must be in [0,3]')
    if type(inject_fault) is not bool:
        raise ValueError('inject_fault must be boolean')
    if set(sources) != set(FILES) or any(DIAGNOSTIC_MARKER in s for s in sources.values()):
        raise ValueError('Unexpected or already instrumented shader source')
    if any(MARKER not in s for s in sources.values()):
        raise ValueError('CGNS overlay must already be applied')
    expected = {'GenerateRetraceWorkload.cs.slang': 1,
                'SpatialPathRetrace.cs.slang': 2, 'SpatialResampling.cs.slang': 1}
    for name, count in expected.items():
        if sources[name].count(ANCHOR) != count:
            raise ValueError('Unexpected selector calls in ' + name)
    result = dict(sources)
    encode = r'''
// LAB_CGNS_STAGE_DIAGNOSTIC_V1
uint labCgnsDiagnosticEncode(int2 p)
{
    if (any(p < 0) || any(p >= 4095)) return 0x00ffffffu;
    return uint(p.x) | (uint(p.y) << 12);
}
'''
    common = result['ResamplingCommon.slang']
    insertion = '// Retrace the primary ray for reused sample at different pixel (domain)'
    if common.count(insertion) != 1: raise ValueError('Common insertion point changed')
    result['ResamplingCommon.slang'] = common.replace(insertion, encode+'\n'+insertion)
    # Native setValid modifies only low neighbor bits. Bits 4..27 carry exact
    # coordinate payload; bit 31 reports any compact-retrace disagreement.
    after_work = ('\n        // '+DIAGNOSTIC_MARKER+'\n'
                  '        neighborValidMask[centralOffset].data = '
                  '(labCgnsDiagnosticEncode(labCgnsSelected.pixels['+str(slot)+']) << 4);')
    name='GenerateRetraceWorkload.cs.slang'
    result[name]=result[name].replace(ANCHOR, ANCHOR+after_work, 1)
    actual = 'labCgnsSelected.pixels['+str(slot)+']'
    if inject_fault: actual = '('+actual+' + int2(1, 0))'
    after_retrace = ('\n        // '+DIAGNOSTIC_MARKER+'\n'
                     '        if (int(retraceIndex / 2) == '+str(slot)+')\n'
                     '        {\n'
                     '            uint labExpected = (neighborValidMask[centralOffset].data >> 4) & 0x00ffffffu;\n'
                     '            if (labExpected != labCgnsDiagnosticEncode('+actual+'))\n'
                     '            { uint labIgnored; InterlockedOr(neighborValidMask[centralOffset].data, 0x80000000u, labIgnored); }\n'
                     '        }')
    name='SpatialPathRetrace.cs.slang'
    result[name]=result[name].replace(ANCHOR, ANCHOR+after_retrace, 1)
    after_resample = ('\n        // '+DIAGNOSTIC_MARKER+'\n'
                      '        uint labData = neighborValidMask[centralOffset].data;\n'
                      '        bool labMismatch = (labData & 0x80000000u) != 0u ||\n'
                      '            ((labData >> 4) & 0x00ffffffu) != labCgnsDiagnosticEncode(labCgnsSelected.pixels['+str(slot)+']);')
    name='SpatialResampling.cs.slang'
    result[name]=result[name].replace(ANCHOR, ANCHOR+after_resample, 1)
    write='reservoirs[centralOffset] = dstReservoir;'
    if result[name].count(write) != 1: raise ValueError('Unexpected reservoir write')
    poison=('// '+DIAGNOSTIC_MARKER+'\n'
            '        if (labMismatch) { dstReservoir.integrand = float3(1e20f, 0.f, 1e20f); dstReservoir.weight = 1.f; }\n'
            '        '+write)
    result[name]=result[name].replace(write, poison, 1)
    return result

def apply_diagnostic(runtime_root, slot, *, inject_fault=False):
    runtime=Path(runtime_root).resolve(strict=True)
    if not (runtime/'Mogwai.exe').is_file(): raise ValueError('Expected private runtime')
    module=runtime/MODULE
    original={name:(module/name).read_bytes().decode('utf8') for name in FILES}
    changed=build_diagnostic(original, slot, inject_fault=inject_fault)
    files={}
    for name in FILES:
        data=changed[name].encode('utf8')
        (module/name).write_bytes(data)
        files[name]=hashlib.sha256(data).hexdigest()
    return {'marker':DIAGNOSTIC_MARKER,'slot':slot,'inject_fault':inject_fault,
            'max_dimension_exclusive':4095,'files':files,
            'semantics':'Exact 24-bit coordinate comparison; retrace only for work items actually dispatched. Nonproduction overlay.'}
