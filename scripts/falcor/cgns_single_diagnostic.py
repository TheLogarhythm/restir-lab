"""Single-neighbor CGNS cross-stage diagnostic; never use for production capture."""
import hashlib
from pathlib import Path
from . import cgns_single_overlay as single
from . import cgns_stage_diagnostic as legacy

MARKER='LAB_CGNS_SINGLE_STAGE_DIAGNOSTIC_V1'
FILES=tuple(single.FILES)

def build_diagnostic(sources,*,inject_fault=False):
    if type(inject_fault) is not bool:raise ValueError('inject_fault must be boolean')
    if set(sources)!=set(FILES) or any(MARKER in text or single.LEGACY_MARKER in text for text in sources.values()):
        raise ValueError('Unexpected or already instrumented shader set')
    if any(single.MARKER not in text for text in sources.values()):raise ValueError('Single-neighbor overlay required')
    translated={n:text.replace(single.MARKER,single.LEGACY_MARKER) for n,text in sources.items()}
    instrumented=legacy.build_diagnostic(translated,0,inject_fault=inject_fault)
    return {n:text.replace(single.LEGACY_MARKER,single.MARKER).replace(legacy.DIAGNOSTIC_MARKER,MARKER) for n,text in instrumented.items()}

def apply_diagnostic(runtime_root,*,inject_fault=False):
    runtime=Path(runtime_root).resolve(strict=True)
    if not (runtime/'Mogwai.exe').is_file() or (runtime.parent/'receipt.json').exists():
        raise ValueError('Diagnostic requires a private copy without a production receipt')
    module=runtime/single.MODULE;source=single.ROOT/'renderers/falcor/upstream/Source/Modules/ReSTIRPathTracing'
    pristine={n:(source/n).read_bytes().decode('utf8') for n in FILES}
    expected=single.build_overlay(pristine)
    inputs={n:(module/n).read_bytes().decode('utf8') for n in FILES}
    if inputs!=expected:raise ValueError('Diagnostic runtime differs from M1 production overlay')
    outputs=build_diagnostic(inputs,inject_fault=inject_fault); hashes={}
    for name,text in outputs.items():
        data=text.encode('utf8');(module/name).write_bytes(data);hashes[name]=hashlib.sha256(data).hexdigest()
    return {'marker':MARKER,'slot':0,'inject_fault':inject_fault,'max_dimension_exclusive':4095,'files':hashes,
            'semantics':'Exact coordinate check; retrace only for dispatched work items; diagnostic only.'}
