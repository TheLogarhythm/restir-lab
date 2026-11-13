"""Private, provenance-separate one-neighbor CGNS shader overlay."""
import hashlib
from pathlib import Path
from . import cgns_shader_overlay as legacy

ROOT=Path(__file__).resolve().parents[2]
MODULE=legacy.MODULE
FILES=legacy.FILES
LEGACY_MARKER=legacy.MARKER
MARKER='LAB_CGNS_SINGLE_SELECTOR_V1'
SELECTOR=Path(__file__).with_name('cgns_single_selector.slang')
LEGACY_SELECTOR=Path(__file__).with_name('cgns_single_selector_legacy.slang')
CORE=Path(__file__).with_name('cgns_single_wrs.h')

def digest(data):return hashlib.sha256(data).hexdigest()

def parameterize_selector(parameters):
    """Create an isolated Slang selector from validated experiment parameters."""
    from .spatial_experiment_config import validate_cgns_shader
    values=validate_cgns_shader(parameters)
    names=(('candidate_count','LAB_CGNS_CANDIDATE_COUNT'),
           ('position_scale','LAB_CGNS_POSITION_SCALE'),
           ('normal_exponent','LAB_CGNS_NORMAL_EXPONENT'),
           ('early_stop_score','LAB_CGNS_EARLY_STOP_SCORE'),
           ('early_stop_count','LAB_CGNS_EARLY_STOP_COUNT'))
    lines=[]
    for key,name in names:
        value=values[key]
        literal=str(value) if key in ('candidate_count','early_stop_count') else repr(float(value))+'f'
        lines.append('#define '+name+' '+literal)
    selector=SELECTOR.read_text(encoding='utf-8-sig')
    if MARKER not in selector:raise ValueError('Missing single-neighbor selector')
    return '\n'.join(lines)+'\n'+selector


def build_overlay(sources,selector=None,core=None,*,parameters=None):
    if any(MARKER in s for s in sources.values()):raise ValueError('Single-neighbor overlay already present')
    if selector is not None and parameters is not None:raise ValueError('Specify selector or parameters, not both')
    if selector is None:
        selector=(parameterize_selector(parameters) if parameters is not None
                  else LEGACY_SELECTOR.read_text(encoding='utf-8-sig'))
    core=CORE.read_text(encoding='utf-8-sig') if core is None else core
    if MARKER not in selector or 'LabCgnsSingleInsert' not in core:raise ValueError('Missing single-neighbor selector/core')
    # Reuse the reviewed integration anchors without mutating the M4 source.
    joined=core+'\n'+selector+'\n// '+LEGACY_MARKER+'\n'
    patched=legacy.build_overlay(sources,joined)
    return {name:text.replace(LEGACY_MARKER,MARKER) for name,text in patched.items()}

def apply_overlay(runtime_root,*,parameters=None):
    runtime=Path(runtime_root).resolve(strict=True)
    module=runtime/MODULE
    if not module.is_dir() or not (runtime/'Mogwai.exe').is_file():raise ValueError('Expected isolated Falcor runtime')
    protected=(ROOT/'renderers/falcor/upstream',ROOT/'build/falcor',ROOT/'build/falcor-reference-runtime',ROOT/'build/falcor-gltf-composite-runtime-v3',ROOT/'build/falcor-cgns-pt-reference',ROOT/'build/falcor-cgns-pt-gltf-v3',ROOT/'build/falcor-cgns-pt-smoke',ROOT/'build/falcor-cgns-stage-diagnostic')
    if any(runtime.is_relative_to(p.resolve()) for p in protected):raise ValueError('Refusing frozen runtime or previous CGNS build')
    source=ROOT/'renderers/falcor/upstream/Source/Modules/ReSTIRPathTracing'
    inputs={}
    for name in FILES:
        data=(module/name).read_bytes()
        if data!=(source/name).read_bytes():raise ValueError('Shader differs from pinned upstream: '+name)
        inputs[name]=data.decode('utf-8')
    outputs=build_overlay(inputs,parameters=parameters)
    receipt={}
    for name in FILES:
        original=inputs[name].encode('utf8');patched=outputs[name].encode('utf8')
        (module/name).write_bytes(patched)
        receipt[(MODULE/name).as_posix()]={'original_sha256':digest(original),'patched_sha256':digest(patched)}
    if parameters is None:
        return {'marker':MARKER,'selector_sha256':digest(LEGACY_SELECTOR.read_bytes()),'core_sha256':digest(CORE.read_bytes()),'files':receipt,
                'limitations':'Legacy point-reservoir selector; caller enforces radius/settings.'}
    from .spatial_experiment_config import validate_cgns_shader
    values=validate_cgns_shader(parameters)
    return {'marker':MARKER,'selector_sha256':digest(SELECTOR.read_bytes()),
            'generated_selector_sha256':digest(parameterize_selector(values).encode('utf8')),
            'parameters':values,'core_sha256':digest(CORE.read_bytes()),'files':receipt,
            'limitations':'Point reservoirs, unpaired, compact retrace, one neighbor; caller enforces radius/settings.'}
