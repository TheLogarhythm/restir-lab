"""Build and verify separate M=1 CGNS runtimes without modifying M=4 artifacts."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from . import reference_runtime, prepare_gltf_composite_runtime_v3 as gltf_runtime
from . import cgns_single_overlay as overlay
from .process_utils import check_renderer_idle, exclusive_operation
from .run import sha

ROOT=Path(__file__).resolve().parents[2]
SOURCES={'reference':reference_runtime,'gltf-v3':gltf_runtime}
KIND='falcor_cgns_single_private_runtime'

def validate_request(kind,output):
    if kind not in SOURCES:raise ValueError('Unknown source runtime')
    dest=Path(output).resolve()
    build=(ROOT/'build').resolve()
    # New immediate build subdirectory; existing frozen trees cannot be nested into.
    if dest.parent!=build or dest.exists():raise ValueError('Destination must be a new direct child of build')
    return dest

def variant_destination(kind, parameters):
    """Stable destination bound to parameters, implementation, and source."""
    from .spatial_experiment_config import validate_cgns_shader
    if kind not in SOURCES:raise ValueError('Unknown source runtime')
    values=validate_cgns_shader(parameters)
    identity={'parameters':values,'selector_sha256':sha(overlay.SELECTOR),
              'core_sha256':sha(overlay.CORE),
              'overlay_sha256':sha(Path(overlay.__file__)),
              'overlay_integration_sha256':sha(Path(overlay.legacy.__file__)),
              'source_receipt_sha256':sha(SOURCES[kind].DEST/'receipt.json')}
    encoded=json.dumps(identity,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf8')
    return ROOT/'build'/('falcor-cgns-single-'+kind+'-'+hashlib.sha256(encoded).hexdigest()[:16])


def _prepare_locked(kind,dest,parameters):
    from .cgns_pt_smoke import _transient_runtime_file,validate_runtime_inventory
    if parameters is not None:
        from .spatial_experiment_config import validate_cgns_shader
        parameters=validate_cgns_shader(parameters)
    dest=validate_request(kind,dest); module=SOURCES[kind]
    source=(module.DEST/'runtime').resolve(strict=True)
    if kind=='gltf-v3':module.quarantine_transients()
    base=module.verify(); source_receipt=module.DEST/'receipt.json'; source_hash=sha(source_receipt)
    validate_runtime_inventory(source,base['runtime_files_sha256'])
    dest.mkdir(parents=True,exist_ok=False); runtime=dest/'runtime';runtime.mkdir()
    for name,expected in sorted(base['runtime_files_sha256'].items()):
        if _transient_runtime_file(name):continue
        src=source/name;dst=runtime/name;dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)
        if sha(dst)!=expected:raise ValueError('Copied runtime file differs: '+name)
    changes=overlay.apply_overlay(runtime,parameters=parameters)
    if sha(source_receipt)!=source_hash:raise RuntimeError('Source receipt changed during preparation')
    receipt={'schema_version':3 if parameters is None else 4,'kind':KIND,'source_kind':kind,
             'source_runtime':source.relative_to(ROOT.resolve()).as_posix(),
             'source_receipt_sha256':source_hash,'overlay':changes,
             'limitations':'Point reservoirs, unpaired spatial reuse, compact retracing, M=1; caller must enforce settings.'}
    (dest/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf8')
    verify_prepared(runtime,expected_parameters=parameters)
    return dest/'receipt.json'


def prepare(kind,output,*,parameters=None):
    with exclusive_operation(ROOT/'build/falcor/.operation.lock'):
        check_renderer_idle()
        return _prepare_locked(kind,output,parameters)


def ensure_variant(kind,parameters):
    """Create or verify a parameter-specific runtime under the operation lock.

    Call only while the caller is not holding the operation lock. An incomplete
    existing directory is rejected rather than modified or silently replaced.
    """
    with exclusive_operation(ROOT/'build/falcor/.operation.lock'):
        check_renderer_idle()
        dest=variant_destination(kind,parameters)
        if dest.is_symlink():raise ValueError('Runtime destination is a symlink')
        if not dest.exists():
            _prepare_locked(kind,dest,parameters)
        else:
            verify_prepared(dest/'runtime',expected_parameters=parameters)
        runtime=dest/'runtime'
        return runtime

def verify_prepared(runtime,*,expected_parameters=None):
    from .cgns_pt_smoke import validate_runtime_inventory
    runtime=Path(runtime).resolve(strict=True);receipt_path=runtime.parent/'receipt.json'
    receipt=json.loads(receipt_path.read_text(encoding='utf8'))
    kind=receipt.get('source_kind')
    version=receipt.get('schema_version')
    if version not in (1,2,3,4) or receipt.get('kind')!=KIND or kind not in SOURCES:raise ValueError('Invalid single-neighbor runtime receipt')
    module=SOURCES[kind];source=(module.DEST/'runtime').resolve(strict=True)
    expected_source=str(source) if version in (1,2) else source.relative_to(ROOT.resolve()).as_posix()
    if receipt.get('source_runtime')!=expected_source or receipt.get('source_receipt_sha256')!=sha(module.DEST/'receipt.json'):raise ValueError('Runtime source receipt differs')
    base=module.verify();changes=receipt.get('overlay')
    if not isinstance(changes,dict) or changes.get('marker')!=overlay.MARKER or changes.get('core_sha256')!=sha(overlay.CORE):raise ValueError('Single-neighbor selector receipt differs')
    if version in (1,3):
        if expected_parameters is not None:raise ValueError('Legacy runtime does not record configurable parameters')
        if changes.get('selector_sha256')!=sha(overlay.LEGACY_SELECTOR):raise ValueError('Legacy selector receipt differs')
        parameters=None
    else:
        from .spatial_experiment_config import validate_cgns_shader
        parameters=validate_cgns_shader(changes.get('parameters'))
        if expected_parameters is not None and parameters!=validate_cgns_shader(expected_parameters):raise ValueError('Runtime shader parameters differ')
        generated=overlay.parameterize_selector(parameters)
        if (changes.get('selector_sha256')!=sha(overlay.SELECTOR)
                or changes.get('generated_selector_sha256')!=hashlib.sha256(generated.encode('utf8')).hexdigest()):
            raise ValueError('Parameterized selector receipt differs')
    inputs={name:(source/overlay.MODULE/name).read_bytes().decode('utf8') for name in overlay.FILES}
    outputs=overlay.build_overlay(inputs,parameters=parameters); expected=dict(base['runtime_files_sha256']);files=changes.get('files')
    names={(overlay.MODULE/name).as_posix() for name in overlay.FILES}
    if not isinstance(files,dict) or set(files)!=names:raise ValueError('Overlay receipt files differ')
    for name,text in outputs.items():
        rel=(overlay.MODULE/name).as_posix()
        before=hashlib.sha256(inputs[name].encode('utf8')).hexdigest();after=hashlib.sha256(text.encode('utf8')).hexdigest()
        if files[rel]!={'original_sha256':before,'patched_sha256':after}:raise ValueError('Overlay receipt mismatch: '+rel)
        expected[rel]=after
    validate_runtime_inventory(runtime,expected)
    result={'kind':'verified_cgns_single_overlay_runtime','source_kind':kind,'source_receipt_sha256':receipt['source_receipt_sha256'],
            'receipt_sha256':sha(receipt_path),'selector_sha256':changes['selector_sha256'],'core_sha256':sha(overlay.CORE)}
    if version in (2,4):result['parameters']=parameters
    return result

def main():
    from .spatial_experiment_config import DEFAULT_CONFIG,load_config
    p=argparse.ArgumentParser(description='Prepare an isolated single-neighbor CGNS runtime')
    p.add_argument('--source',choices=tuple(SOURCES),required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    a=p.parse_args();parameters=load_config(a.config)['methods']['cgns']['shader']
    print(prepare(a.source,a.output,parameters=parameters))
if __name__=='__main__':main()
