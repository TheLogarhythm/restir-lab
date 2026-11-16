"""Prepare and verify private PDF-guided ReSTIR PT shader variants.

Every requested variant copies the runnable baseline inventory without PDBs,
cache, or logs. There are no hardlinks or junctions to a frozen runtime. Falcor's
default cache location is consequently private to this executable directory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from . import reference_runtime, prepare_gltf_composite_runtime_v3 as gltf_runtime
from . import pdf_pt_overlay as overlay, runtime_common as common
from .runtime_common import is_transient_runtime_file as _transient_runtime_file, validate_runtime_inventory
from .process_utils import check_renderer_idle, exclusive_operation
from .runtime_common import sha256_file as sha


ROOT = Path(__file__).resolve().parents[2]
SOURCES = {'reference': reference_runtime, 'gltf-v3': gltf_runtime}
KIND = 'falcor_pdf_pt_private_runtime'
SCHEMA_VERSION = 2


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf8')


def _implementation_sha256():
    result = overlay.implementation_sha256()
    result[Path(__file__).resolve().relative_to(ROOT.resolve()).as_posix()] = sha(Path(__file__))
    return result


def _identity(kind, parameters, profile):
    if kind not in SOURCES:
        raise ValueError('Unknown PDF PT source runtime')
    return {'parameters': overlay.validate_parameters(parameters),
            'profile': overlay.validate_profile(profile), 'source_kind': kind,
            'source_receipt_sha256': sha(SOURCES[kind].DEST / 'receipt.json'),
            'implementation_sha256': _implementation_sha256()}


def variant_destination(kind, parameters, profile='normal'):
    identity = _identity(kind, parameters, profile)
    fingerprint = hashlib.sha256(_canonical(identity)).hexdigest()
    return ROOT / 'build' / ('falcor-pdf-pt-' + kind + '-' + profile + '-' + fingerprint[:16])


def validate_request(kind, output):
    if kind not in SOURCES:
        raise ValueError('Unknown PDF PT source runtime')
    dest = Path(output).absolute()
    build = ROOT.absolute() / 'build'
    if (dest.parent != build or not dest.name.startswith('falcor-pdf-pt-')
            or dest.exists() or dest.is_symlink()):
        raise ValueError('Destination must be a new direct build/falcor-pdf-pt-* child')
    overlay.reject_link(build)
    return dest


def _check_tree(root):
    """Compatibility wrapper for callers of the former PDF-private helper."""
    return common.check_tree(root)


def _read_base(kind):
    """Compatibility wrapper; new method adapters use the neutral helper."""
    return common.read_baseline(SOURCES[kind])


def _prepare_locked(kind, dest, parameters, profile='normal'):
    identity = _identity(kind, parameters, profile)
    dest = validate_request(kind, dest)
    source, base = _read_base(kind)
    source_receipt = SOURCES[kind].DEST / 'receipt.json'
    if sha(source_receipt) != identity['source_receipt_sha256']:
        raise RuntimeError('Source receipt changed during preparation')
    names = overlay.source_names()
    inventory = base['runtime_files_sha256']
    if not set(names).issubset(inventory):
        raise ValueError('PDF PT shader inputs are missing from the baseline receipt')
    dest.mkdir(exist_ok=False)
    runtime = dest / 'runtime'
    runtime.mkdir()
    # All shaders stay independent writable copies. No cache, PDB, or renderer
    # log is copied, and no file link can propagate a later edit to the source.
    for name, expected in sorted(inventory.items()):
        if _transient_runtime_file(name):
            continue
        src, dst = source / name, runtime / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if sha(dst) != expected or dst.stat().st_nlink != 1:
            raise ValueError('Copied PDF PT runtime file differs: ' + name)
    changes = overlay.apply_overlay(runtime, identity['parameters'], profile=profile)
    (runtime / '.shadercache').mkdir(exist_ok=False)
    if sha(source_receipt) != identity['source_receipt_sha256']:
        raise RuntimeError('Source receipt changed during preparation')
    if _identity(kind, parameters, profile) != identity:
        raise RuntimeError('PDF PT implementation changed during preparation')
    receipt = {'schema_version': SCHEMA_VERSION, 'kind': KIND, **identity,
               'source_runtime': source.resolve().relative_to(ROOT.resolve()).as_posix(),
               'overlay': changes, 'cache_policy': 'private-runtime/.shadercache',
               'copy_policy': 'independent-files-without-pdb-cache-or-logs',
               'limitations': 'Independent PDF-guided PT port; caller must enforce qualified graph settings.'}
    (dest / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf8')
    verify_prepared(runtime, expected_parameters=parameters, profile=profile)
    return dest / 'receipt.json'


def prepare(kind, output, *, parameters, profile='normal'):
    with exclusive_operation(ROOT / 'build/falcor/.operation.lock'):
        check_renderer_idle()
        return _prepare_locked(kind, output, parameters, profile=profile)


def ensure_variant(kind, parameters, profile='normal'):
    """Create once or verify, rejecting incomplete existing variants unchanged."""
    with exclusive_operation(ROOT / 'build/falcor/.operation.lock'):
        check_renderer_idle()
        dest = variant_destination(kind, parameters, profile=profile)
        if dest.exists() or dest.is_symlink():
            overlay.reject_link(dest)
            verified = verify_prepared(dest / 'runtime', expected_parameters=parameters, profile=profile)
            if verified['source_kind'] != kind:
                raise ValueError('PDF PT variant source kind differs')
        else:
            _prepare_locked(kind, dest, parameters, profile=profile)
        return dest / 'runtime'


def verify_prepared(runtime, expected_parameters=None, profile='normal'):
    runtime = Path(runtime).absolute()
    build = ROOT.absolute() / 'build'
    if (runtime.name != 'runtime' or runtime.parent.parent != build
            or not runtime.parent.name.startswith('falcor-pdf-pt-')):
        raise ValueError('PDF PT verification requires a private runtime')
    for path in (build, runtime.parent, runtime, runtime.parent / 'receipt.json'):
        overlay.reject_link(path)
    _check_tree(runtime)
    receipt_path = runtime.parent / 'receipt.json'
    receipt = json.loads(receipt_path.read_text(encoding='utf8'))
    kind = receipt.get('source_kind')
    if (receipt.get('schema_version') != SCHEMA_VERSION or receipt.get('kind') != KIND
            or kind not in SOURCES):
        raise ValueError('Invalid current PDF PT runtime receipt; use verify_snapshot for historical packages')
    values = overlay.validate_parameters(receipt.get('parameters'))
    requested_profile = overlay.validate_profile(profile)
    if receipt.get('profile') != requested_profile:
        raise ValueError('PDF PT runtime compile profile differs')
    if expected_parameters is not None and values != overlay.validate_parameters(expected_parameters):
        raise ValueError('PDF PT runtime shader parameters differ')
    identity = _identity(kind, values, requested_profile)
    if any(receipt.get(key) != value for key, value in identity.items()):
        raise ValueError('PDF PT runtime implementation or source receipt differs')
    source, base = _read_base(kind)
    if receipt.get('source_runtime') != source.resolve().relative_to(ROOT.resolve()).as_posix():
        raise ValueError('PDF PT runtime source path differs')
    if (receipt.get('cache_policy') != 'private-runtime/.shadercache'
            or receipt.get('copy_policy') != 'independent-files-without-pdb-cache-or-logs'):
        raise ValueError('PDF PT runtime isolation policy differs')
    changes = receipt.get('overlay')
    if (not isinstance(changes, dict) or changes.get('marker') != overlay.MARKER
            or changes.get('parameters') != values or changes.get('profile') != requested_profile
            or changes.get('implementation_sha256') != overlay.implementation_sha256()):
        raise ValueError('PDF PT overlay receipt differs')
    inputs = overlay.read_sources(source)
    outputs = overlay.build_overlay(inputs, values, profile=requested_profile)
    files = changes.get('files')
    if not isinstance(files, dict) or set(files) != set(outputs):
        raise ValueError('PDF PT overlay file inventory differs')
    expected = dict(base['runtime_files_sha256'])
    for name, output in outputs.items():
        before = overlay.digest(inputs[name].encode('utf8'))
        after = overlay.digest(output.encode('utf8'))
        if files[name] != {'original_sha256': before, 'patched_sha256': after}:
            raise ValueError('PDF PT overlay source hash differs: ' + name)
        if (runtime / name).stat().st_nlink != 1:
            raise ValueError('PDF PT shader must be an independent file: ' + name)
        expected[name] = after
    validate_runtime_inventory(runtime, expected)
    cache = runtime / '.shadercache'
    if not cache.is_dir():
        raise ValueError('PDF PT private shader cache is missing')
    fingerprint = hashlib.sha256(_canonical(identity)).hexdigest()
    return {'kind': 'verified_pdf_pt_overlay_runtime', **identity,
            'receipt_sha256': sha(receipt_path), 'variant_fingerprint': fingerprint,
            'runtime_inventory_sha256': hashlib.sha256(_canonical({name: value for name, value in expected.items()
                                           if not _transient_runtime_file(name)})).hexdigest(),
            'shader_sha256': {name: files[name]['patched_sha256'] for name in sorted(files)}}


def verify_snapshot(runtime, *, expected_receipt_sha256):
    """Inspect recorded package bytes, including old schema 1, without rendering.

    Supply the trusted receipt digest saved in a capture manifest. The frozen
    baseline is required; current shader/helper bytes are deliberately ignored.
    This result cannot replace verify_prepared() in a rendering entry point.
    """
    runtime, receipt, source, base = common.read_snapshot(
        runtime, root=ROOT, prefix='falcor-pdf-pt-', kind=KIND, versions=(1, SCHEMA_VERSION),
        sources=SOURCES, expected_receipt_sha256=expected_receipt_sha256)
    if receipt.get('source_runtime') != source.resolve().relative_to(ROOT.resolve()).as_posix():
        raise ValueError('Historical PDF runtime source path differs')
    changes = receipt.get('overlay')
    if not isinstance(changes, dict) or changes.get('marker') != overlay.MARKER:
        raise ValueError('Invalid historical PDF overlay record')
    files = changes.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('Historical PDF overlay inventory is missing')
    expected = dict(base['runtime_files_sha256'])
    patched = {}
    for name, record in files.items():
        common.safe_name(name)
        if (name not in expected or not isinstance(record, dict)
                or set(record) != {'original_sha256', 'patched_sha256'}
                or record['original_sha256'] != expected[name]):
            raise ValueError('Historical PDF overlay source hash differs: ' + name)
        patched[name] = record['patched_sha256']
    common.validate_hash_inventory(patched, 'Historical PDF shader record')
    validate_runtime_inventory(runtime, {**expected, **patched})
    return {'kind': 'historical_pdf_pt_runtime_snapshot', 'current_implementation': False,
            'verification_scope': 'recorded-bytes-only', 'source_kind': receipt['source_kind'],
            'receipt_sha256': expected_receipt_sha256, 'shader_sha256': patched}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=tuple(SOURCES), required=True)
    parser.add_argument('--history-limit', type=int, default=20)
    parser.add_argument('--history-decay', type=float, default=0.95)
    parser.add_argument('--profile', choices=overlay.PROFILES, default='normal')
    args = parser.parse_args()
    print(ensure_variant(args.source, {'history_limit': args.history_limit,
                                     'history_decay': args.history_decay}, profile=args.profile))


if __name__ == '__main__':
    main()
