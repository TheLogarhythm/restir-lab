"""Optionally verify the path-only migration against preserved historical snapshots.

Normal rendering does not import or call this verifier. The snapshots under
runs/ are only needed when independently auditing the historical migration.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROOF = 'experiments/references/falcor-scene-inputs-migration-v2.json'
CONFIGS = 'experiments/configs/falcor-pt-spatial-comparison/'
RECEIPT = 'scenes/configs/falcor/bistro-gltf/sky-bake-receipt.json'
PLAN = 'scenes/configs/falcor/bistro-gltf/scene-plan.json'
SPEC = CONFIGS + 'bistro-gltf-direct-spec.json'
INTERIOR = CONFIGS + 'bistro-interior-reference.json'


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _read(root, path):
    path = Path(path)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Migration path must be workspace-relative')
    target = (root / path).resolve(strict=True)
    if not target.is_relative_to(root):
        raise ValueError('Migration path escapes workspace')
    return target.read_bytes()


def _replace(value, old, new):
    if isinstance(value, dict):
        return {k: _replace(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace(v, old, new) for v in value]
    return new if value == old else value


def verify(root=ROOT):
    root = Path(root).resolve(strict=True)
    proof = json.loads(_read(root, PROOF))
    if proof.get('schema_version') != 1 or proof.get('kind') != 'falcor_scene_inputs_v2_migration':
        raise ValueError('Unsupported migration receipt')
    rows = proof['changes']
    if len(rows) != 9 or len({row['path'] for row in rows}) != 9:
        raise ValueError('Unexpected migration file set')
    old, new, raw = {}, {}, {}
    for row in rows:
        before = _read(root, row['snapshot'])
        after = _read(root, row['path'])
        if _sha(before) != row['old_sha256'] or _sha(after) != row['new_sha256']:
            raise ValueError('Migration file hash mismatch: ' + row['path'])
        old[row['path']] = json.loads(before.decode('utf-8-sig'))
        new[row['path']] = json.loads(after.decode('utf-8-sig'))
        raw[row['path']] = after
    if set(old) != {SPEC, INTERIOR, PLAN, RECEIPT, *(CONFIGS + x for x in (
            'bistro-exterior-reference.json', 'classroom-reference.json',
            'emerald-square-reference.json', 'veach-ajar-reference.json',
            'zero-day-measure-seven-reference.json'))}:
        raise ValueError('Unexpected migration paths')
    prior = _read(root, 'runs/falcor-pt-spatial-comparison/provenance/relocations/bistro-portable-v1.json')
    if _sha(prior) != proof['old_scene_migration_receipt_sha256']:
        raise ValueError('Prior migration receipt changed')
    sky = _read(root, proof['new_sky_path'])
    if _sha(sky) != proof['sky_sha256']:
        raise ValueError('Prepared sky differs')
    for path, before in old.items():
        expected = _replace(copy.deepcopy(before), proof['old_sky_path'], proof['new_sky_path'])
        if path == PLAN:
            for item in expected['scene']['dependencies']:
                if item['path'] == RECEIPT:
                    item['sha256'] = _sha(raw[RECEIPT])
        elif path == INTERIOR:
            for item in expected['resources']:
                if item['path'] == RECEIPT:
                    item['sha256'] = _sha(raw[RECEIPT])
            for item in expected['sources']:
                if item['path'] in (SPEC, PLAN):
                    item['sha256'] = _sha(raw[item['path']])
                    item['bytes'] = len(raw[item['path']])
        elif path not in (SPEC, RECEIPT):
            qualification = expected.get('qualification', {})
            if isinstance(qualification, dict):
                qualification.pop('evidence', None)
                for key in list(qualification):
                    if key.startswith(('scout_', 'verified_')):
                        qualification.pop(key)
        if expected != new[path]:
            raise ValueError('Migration changed non-path scene data: ' + path)
    scene_inputs = _read(root, CONFIGS + 'scene-inputs.json')
    if _sha(scene_inputs) != proof['scene_inputs_sha256']:
        raise ValueError('Scene input manifest changed')
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=ROOT)
    args = parser.parse_args()
    print('Verified migrated scene files:', verify(args.workspace))


if __name__ == '__main__':
    main()
