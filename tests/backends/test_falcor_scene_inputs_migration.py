"""Migration verification uses synthetic history, without ignored archives/assets."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from scripts.falcor import verify_scene_inputs_migration as migration


def fixture(root):
    old_sky, new_sky = 'runs/history/sky.exr', 'assets/prepared/sky.exr'
    def write(path, value):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(value, sort_keys=True).encode()
        target.write_bytes(data)
        return hashlib.sha256(data).hexdigest()
    def digest(path):
        return hashlib.sha256((root / path).read_bytes()).hexdigest()
    prior = 'runs/falcor-pt-spatial-comparison/provenance/relocations/bistro-portable-v1.json'
    write(prior, {'kind': 'synthetic historical receipt'})
    sky = root / new_sky
    sky.parent.mkdir(parents=True)
    sky.write_bytes(b'synthetic prepared sky; no renderer or downloaded assets')
    before = {
        migration.SPEC: {'camera': {'position': [1,2,3]}, 'environment': old_sky},
        migration.RECEIPT: {'output': old_sky, 'settings': {'exposure': 0}},
        migration.PLAN: {'scene': {'environment': old_sky, 'dependencies': []}},
        migration.INTERIOR: {'resources': [], 'sources': [], 'camera': {'position': [1,2,3]}},
    }
    for name in ('bistro-exterior', 'classroom', 'emerald-square', 'veach-ajar', 'zero-day-measure-seven'):
        before[migration.CONFIGS + name + '-reference.json'] = {
            'scene': name, 'environment': old_sky,
            'qualification': {'status': 'verified', 'evidence': 'runs/history', 'scout_hash': 'old', 'verified_hash': 'old'}}
    after = copy.deepcopy(before)
    for path in (migration.SPEC, migration.RECEIPT):
        key = 'environment' if path == migration.SPEC else 'output'
        after[path][key] = new_sky
    after[migration.PLAN]['scene']['environment'] = new_sky
    old_receipt_hash = hashlib.sha256(json.dumps(before[migration.RECEIPT], sort_keys=True).encode()).hexdigest()
    new_receipt_hash = hashlib.sha256(json.dumps(after[migration.RECEIPT], sort_keys=True).encode()).hexdigest()
    before[migration.PLAN]['scene']['dependencies'] = [{'path': migration.RECEIPT, 'sha256': old_receipt_hash}]
    after[migration.PLAN]['scene']['dependencies'] = [{'path': migration.RECEIPT, 'sha256': new_receipt_hash}]
    for values in (before, after):
        interior = values[migration.INTERIOR]
        interior['resources'] = [{'path': migration.RECEIPT, 'sha256': hashlib.sha256(json.dumps(values[migration.RECEIPT], sort_keys=True).encode()).hexdigest()}]
        for path in (migration.SPEC, migration.PLAN):
            data = json.dumps(values[path], sort_keys=True).encode()
            interior['sources'].append({'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
    rows = []
    for index, (path, original) in enumerate(before.items()):
        if path not in (migration.SPEC, migration.RECEIPT, migration.PLAN, migration.INTERIOR):
            after[path]['environment'] = new_sky
            after[path]['qualification'] = {'status': 'verified'}
        snapshot = f'runs/synthetic-history/{index}.json'
        rows.append({'path': path, 'snapshot': snapshot, 'old_sha256': write(snapshot, original),
                     'new_sha256': write(path, after[path])})
    inputs = migration.CONFIGS + 'scene-inputs.json'
    proof = {'schema_version': 1, 'kind': 'falcor_scene_inputs_v2_migration', 'changes': rows,
             'old_sky_path': old_sky, 'new_sky_path': new_sky, 'sky_sha256': digest(new_sky),
             'old_scene_migration_receipt_sha256': digest(prior),
             'scene_inputs_sha256': write(inputs, {'views': ['synthetic']})}
    write(migration.PROOF, proof)
    return proof


class SceneMigrationTest(unittest.TestCase):
    def test_proves_path_only_migration_and_rejects_changed_scene(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proof = fixture(root)
            self.assertEqual(migration.verify(root), 9)
            path = root / migration.SPEC
            data = json.loads(path.read_text(encoding='utf8'))
            data['camera']['position'][0] += 1
            path.write_text(json.dumps(data), encoding='utf8')
            for row in proof['changes']:
                if row['path'] == migration.SPEC:
                    row['new_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            (root / migration.PROOF).write_text(json.dumps(proof), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'non-path scene data'):
                migration.verify(root)
