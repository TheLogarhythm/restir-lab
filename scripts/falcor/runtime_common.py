"""Shared byte and path checks for private Falcor runtime packages.

These checks are independent of a resampling method. Snapshot verification
requires a receipt digest from a trusted saved record and never authorizes a
package as the implementation of the current source tree.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat


def implementation_files():
    # Only the standard library is imported: this is the complete live helper
    # dependency of the package checks, including their file hashing operation.
    return (Path(__file__).resolve(),)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def safe_name(name):
    """Accept only canonical runtime-relative POSIX file names."""
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name or '\x00' in name
            or PurePosixPath(name).is_absolute() or PureWindowsPath(name).drive
            or any(part in ('.', '..') for part in name.split('/'))
            or PurePosixPath(name).as_posix() != name):
        raise ValueError('Invalid runtime-relative file name: ' + repr(name))
    return name


def reject_link(path):
    """Inspect before resolving so a Windows junction cannot hide its target."""
    path = Path(path)
    info = path.lstat()
    if path.is_symlink() or (getattr(info, 'st_file_attributes', 0)
                             & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
        raise ValueError('Refusing runtime reparse point: ' + str(path))
    return info


def check_tree(root):
    """Inspect each directory before descending; never follow reparse points."""
    pending = [Path(root)]
    while pending:
        current = pending.pop()
        info = reject_link(current)
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError('Runtime root is not a directory')
        for child in current.iterdir():
            info = reject_link(child)
            if stat.S_ISDIR(info.st_mode):
                pending.append(child)
            elif not stat.S_ISREG(info.st_mode):
                raise ValueError('Unexpected runtime file type: ' + str(child))


def is_transient_runtime_file(name):
    return (name.startswith('.shadercache/') or name.endswith('.pdb')
            or bool(re.fullmatch(r'Mogwai\.exe\.\d+\.log', name)))


def validate_hash_inventory(inventory, label='Runtime inventory'):
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError(label + ' must be a nonempty file hash mapping')
    for name, digest in inventory.items():
        try:
            safe_name(name)
        except ValueError as exc:
            raise ValueError(label + ': ' + str(exc)) from exc
        if not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None:
            raise ValueError(label + ' has an invalid SHA-256: ' + name)
    return dict(inventory)


def validate_runtime_inventory(runtime, expected):
    runtime = Path(runtime)
    expected = validate_hash_inventory(expected)
    check_tree(runtime)
    files = {p.relative_to(runtime).as_posix() for p in runtime.rglob('*') if p.is_file()}
    wanted = {name for name in expected if not is_transient_runtime_file(name)}
    actual = {name for name in files if not is_transient_runtime_file(name)}
    if actual != wanted:
        raise ValueError('Runtime inventory differs; missing=' + repr(sorted(wanted-actual)[:5])
                         + ' extra=' + repr(sorted(actual-wanted)[:5]))
    for name in sorted(wanted):
        if sha256_file(runtime / name) != expected[name]:
            raise ValueError('Runtime hash mismatch: ' + name)


def read_baseline(module):
    """Read a frozen baseline through its existing verifier without mutating it."""
    source = module.DEST / 'runtime'
    receipt_path = module.DEST / 'receipt.json'
    for path in (module.DEST, source, receipt_path):
        reject_link(path)
    # Validate file names before the legacy verifier opens receipt-derived paths.
    recorded = json.loads(receipt_path.read_text(encoding='utf8'))
    inventory = validate_hash_inventory(recorded.get('runtime_files_sha256'))
    check_tree(source)
    receipt = module.verify()
    if receipt.get('runtime_files_sha256') != inventory:
        raise ValueError('Source runtime inventory changed during verification')
    validate_runtime_inventory(source, inventory)
    return source, receipt


def private_runtime_path(runtime, *, root, prefix):
    runtime = Path(runtime).absolute()
    build = Path(root).absolute() / 'build'
    if (runtime.name != 'runtime' or runtime.parent.parent != build
            or not runtime.parent.name.startswith(prefix)):
        raise ValueError('Expected a private runtime under build/' + prefix + '*')
    for path in (build, runtime.parent, runtime, runtime.parent / 'receipt.json'):
        reject_link(path)
    return runtime


def read_snapshot(runtime, *, root, prefix, kind, versions, sources, expected_receipt_sha256):
    """Read a pinned historical receipt; current implementation identity is ignored.

    Callers must still validate the complete recorded output inventory. The
    trusted receipt digest must come from outside this package, for example a
    frozen capture manifest; accepting a package's own claimed digest is unsafe.
    Frozen baseline files and their existing verifier are still required. This
    is package inspection, not a standalone archive reader or render approval.
    """
    if (not isinstance(expected_receipt_sha256, str)
            or re.fullmatch('[0-9a-f]{64}', expected_receipt_sha256) is None):
        raise ValueError('A trusted snapshot receipt SHA-256 is required')
    runtime = private_runtime_path(runtime, root=root, prefix=prefix)
    receipt_path = runtime.parent / 'receipt.json'
    raw = receipt_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_receipt_sha256:
        raise ValueError('Snapshot receipt SHA-256 differs from the trusted record')
    receipt = json.loads(raw)
    if not isinstance(receipt, dict):
        raise ValueError('Invalid historical runtime receipt')
    source_kind = receipt.get('source_kind')
    if (receipt.get('kind') != kind or receipt.get('schema_version') not in versions
            or source_kind not in sources):
        raise ValueError('Invalid historical runtime receipt')
    module = sources[source_kind]
    for path in (module.DEST, module.DEST / 'receipt.json'):
        reject_link(path)
    if sha256_file(module.DEST / 'receipt.json') != receipt.get('source_receipt_sha256'):
        raise ValueError('Historical runtime source receipt differs')
    source, base = read_baseline(module)
    return runtime, receipt, source, base
