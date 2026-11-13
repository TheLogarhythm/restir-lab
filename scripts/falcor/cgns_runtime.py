# Reproducible private CGNS runtime preparation; frozen source runtimes remain untouched.
import argparse
import json
from pathlib import Path
import shutil

from . import reference_runtime, prepare_gltf_composite_runtime_v3 as gltf_runtime
from . import cgns_shader_overlay as overlay
from .process_utils import check_renderer_idle, exclusive_operation
from .run import sha

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {'reference': reference_runtime, 'gltf-v3': gltf_runtime}


def validate_request(kind, output):
    if kind not in SOURCES: raise ValueError('Unknown source runtime')
    dest = Path(output).resolve()
    build = (ROOT / 'build').resolve()
    if not dest.is_relative_to(build) or dest == build or dest.exists():
        raise ValueError('Destination must be a new directory inside build')
    protected = [build / 'falcor', *(module.DEST.resolve() for module in SOURCES.values())]
    if any(dest.is_relative_to(path) for path in protected):
        raise ValueError('Destination cannot be inside a frozen runtime or Falcor build')
    return dest


def prepare(kind, output):
    from .cgns_pt_smoke import _transient_runtime_file, validate_runtime_inventory
    dest = validate_request(kind, output)
    module = SOURCES[kind]
    source = (module.DEST / 'runtime').resolve(strict=True)
    with exclusive_operation(ROOT / 'build/falcor/.operation.lock'):
        check_renderer_idle()
        base = module.verify()
        source_receipt = module.DEST / 'receipt.json'
        source_receipt_hash = sha(source_receipt)
        validate_runtime_inventory(source, base['runtime_files_sha256'])
        # Create a new destination only after source checks; failed copies are preserved.
        dest.mkdir(parents=True, exist_ok=False)
        runtime = dest / 'runtime'
        runtime.mkdir()
        for name, expected in sorted(base['runtime_files_sha256'].items()):
            if _transient_runtime_file(name): continue
            src = source / name
            dst = runtime / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            if sha(dst) != expected: raise ValueError('Copy mismatch: ' + name)
        changes = overlay.apply_overlay(runtime)
        if sha(source_receipt) != source_receipt_hash:
            raise RuntimeError('Source receipt changed during preparation')
        receipt = {'schema_version': 2, 'kind': 'falcor_cgns_private_runtime',
                   'source_kind': kind, 'source_runtime': source.relative_to(ROOT.resolve()).as_posix(),
                   'source_receipt_sha256': source_receipt_hash,
                   'overlay': changes,
                   'limitations': 'Requires point reservoirs, non-paired spatial reuse, compact retracing, four neighbors; overlay only changes neighbor selection.'}
        (dest / 'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf8')
        verify_prepared(runtime)
        return dest / 'receipt.json'


def verify_prepared(runtime):
    import hashlib
    from .cgns_pt_smoke import validate_runtime_inventory
    runtime = Path(runtime).resolve(strict=True)
    receipt_path = runtime.parent / 'receipt.json'
    receipt = json.loads(receipt_path.read_text(encoding='utf8'))
    kind = receipt.get('source_kind')
    version = receipt.get('schema_version')
    if version not in (1, 2) or receipt.get('kind') != 'falcor_cgns_private_runtime' or kind not in SOURCES:
        raise ValueError('Invalid prepared runtime receipt')
    module = SOURCES[kind]
    source = (module.DEST / 'runtime').resolve(strict=True)
    expected_source = str(source) if version == 1 else source.relative_to(ROOT.resolve()).as_posix()
    if receipt.get('source_runtime') != expected_source or receipt.get('source_receipt_sha256') != sha(module.DEST / 'receipt.json'):
        raise ValueError('Runtime source receipt differs')
    base = module.verify()
    changes = receipt.get('overlay')
    if not isinstance(changes, dict) or changes.get('marker') != overlay.MARKER or changes.get('selector_sha256') != sha(overlay.SELECTOR):
        raise ValueError('Invalid overlay marker or selector')
    inputs = {name:(source / overlay.MODULE / name).read_bytes().decode('utf8') for name in overlay.FILES}
    outputs = overlay.build_overlay(inputs, overlay.SELECTOR.read_text(encoding='utf8'))
    expected = dict(base['runtime_files_sha256'])
    files = changes.get('files')
    names = {(overlay.MODULE / name).as_posix() for name in overlay.FILES}
    if not isinstance(files, dict) or set(files) != names: raise ValueError('Overlay receipt files differ')
    for name, text in outputs.items():
        rel=(overlay.MODULE / name).as_posix()
        before=hashlib.sha256(inputs[name].encode('utf8')).hexdigest()
        after=hashlib.sha256(text.encode('utf8')).hexdigest()
        if files[rel] != {'original_sha256': before, 'patched_sha256': after}:
            raise ValueError('Overlay receipt mismatch: '+rel)
        expected[rel] = after
    validate_runtime_inventory(runtime, expected)
    return {'kind':'verified_cgns_overlay_runtime', 'source_kind':kind,
            'source_receipt_sha256':receipt['source_receipt_sha256'],
            'receipt_sha256':sha(receipt_path), 'selector_sha256':sha(overlay.SELECTOR)}


def main():
    p=argparse.ArgumentParser(description='Prepare an isolated CGNS Falcor runtime')
    p.add_argument('--source', choices=tuple(SOURCES), required=True)
    p.add_argument('--output', type=Path, required=True)
    a=p.parse_args()
    print(prepare(a.source,a.output))

if __name__ == '__main__': main()
