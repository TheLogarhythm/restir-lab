"""Prepare a fingerprinted isolated runtime for Falcor's 128-bit sampler."""
import json
from pathlib import Path
import shutil

if __package__:
    from . import build, run
    from .process_utils import check_renderer_idle, exclusive_operation
else:
    import build
    import run
    from process_utils import check_renderer_idle, exclusive_operation

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / 'build/falcor-reference-runtime'
PATCH = Path('shaders/RenderPasses/PathTracer/LightTileRISHelper.slang')
OLD = 'SampleGenerator(neeSeed)'
NEW = 'SampleGenerator(uint2(0, 0), neeSeed)'


def patch_shader(source):
    if source.count(OLD) != 1:
        raise ValueError('Expected exactly one upstream sampler call')
    return source.replace(OLD, NEW)


def prepare():
    with exclusive_operation(ROOT / 'build/falcor/.operation.lock'):
        check_renderer_idle()
        record = build.verify_build()
        source = (ROOT / record['executable']).parent
        if DEST.exists():
            raise FileExistsError(DEST)
        DEST.mkdir(parents=True)
        target = DEST / 'runtime'
        shutil.copytree(source, target, ignore=shutil.ignore_patterns('.shadercache'))
        modified = target / PATCH
        before = run.sha(modified)
        original = modified.read_bytes()
        old = OLD.encode('ascii')
        new = NEW.encode('ascii')
        if original.count(old) != 1:
            raise ValueError('Unexpected upstream shader; incomplete copy preserved')
        modified.write_bytes(original.replace(old, new))
        inventory = {}
        for p in sorted(target.rglob('*')):
            if not p.is_file():
                continue
            rel = p.relative_to(target)
            src = source / rel
            source_hash = run.sha(src)
            actual_hash = run.sha(p)
            if rel != PATCH and source_hash != actual_hash:
                raise RuntimeError('Runtime copy differs: ' + str(rel))
            inventory[rel.as_posix()] = actual_hash
        if before != run.sha(source / PATCH):
            raise RuntimeError('Original shader changed during copy')
        receipt = {'schema_version': 1, 'kind': 'isolated_reference_runtime',
                   'upstream_commit': record['commit'],
                   'source_build_sha256': run.sha(ROOT / 'build/falcor/build.json'),
                   'source_executable': record['executable'],
                   'patch_file': PATCH.as_posix(), 'original_sha256': before,
                   'patched_sha256': run.sha(modified), 'old': OLD, 'new': NEW,
                   'limitations': 'Light Tile RIS must remain disabled; patch only repairs shader type checking.',
                   'runtime_files_sha256': inventory}
        run.save(DEST / 'receipt.json', receipt)
        return DEST / 'receipt.json'


def verify():
    receipt = json.loads((DEST / 'receipt.json').read_text())
    if receipt['source_build_sha256'] != run.sha(ROOT / 'build/falcor/build.json'):
        raise RuntimeError('Reference runtime source build record changed')
    for name, expected in receipt['runtime_files_sha256'].items():
        file = DEST / 'runtime' / name
        if not file.is_file() or run.sha(file) != expected:
            raise RuntimeError('Reference runtime changed: ' + name)
    patched = DEST / 'runtime' / PATCH
    if OLD in patched.read_text(encoding='utf-8') or NEW not in patched.read_text(encoding='utf-8'):
        raise RuntimeError('Reference runtime shader patch missing')
    return receipt


if __name__ == '__main__':
    print(prepare())
