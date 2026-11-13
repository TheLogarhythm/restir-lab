"""Build a fingerprinted, isolated Falcor runtime for marked glTF materials."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
from gltf_factor_shader_patch import patch_sources

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'build/falcor-reference-runtime'
DEST = ROOT / 'build/falcor-gltf-factor-runtime'
PLUGIN = ROOT / 'build/gltf-factor-material/GltfFactorMaterial.dll'
FILES = {'standard': 'shaders/Rendering/Materials/StandardMaterial.slang',
         'system': 'shaders/Scene/Material/MaterialSystem.slang',
         'finalize': 'shaders/Scene/Lights/FinalizeIntegration.cs.slang'}
INPUTS = [ROOT / 'scripts/falcor/gltf_factor_shader_patch.py',
          ROOT / 'scripts/falcor/gltf_factor_material.cpp',
          ROOT / 'scripts/falcor/prepare_gltf_factor_runtime.py', PLUGIN]

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()

def prepare():
    if DEST.exists():
        raise FileExistsError(DEST)
    source = SOURCE / 'runtime'
    source_receipt = json.loads((SOURCE / 'receipt.json').read_text(encoding='utf8'))
    originals = {k: (source / p).read_text(encoding='utf8') for k, p in FILES.items()}
    patched = patch_sources(originals)
    if not PLUGIN.is_file():
        raise FileNotFoundError(PLUGIN)
    target = DEST / 'runtime'
    target.mkdir(parents=True)
    for rel, expected in source_receipt['runtime_files_sha256'].items():
        src = source / rel
        if digest(src) != expected:
            raise RuntimeError('Baseline mismatch: ' + rel)
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if digest(dst) != expected:
            raise RuntimeError('Copy mismatch: ' + rel)
    changes = {}
    for k, rel in FILES.items():
        dst = target / rel
        dst.write_text(patched[k], encoding='utf8', newline='\n')
        changes[rel] = {'source_sha256': digest(source / rel), 'patched_sha256': digest(dst)}
    plugin_dst = target / 'plugins/GltfFactorMaterial.dll'
    shutil.copy2(PLUGIN, plugin_dst)
    manifest = target / 'plugins/plugins.json'
    old_manifest = digest(manifest)
    entries = json.loads(manifest.read_text(encoding='utf8'))
    if 'GltfFactorMaterial' in entries:
        raise RuntimeError('Plugin already in baseline manifest')
    entries.append('GltfFactorMaterial')
    manifest.write_text(json.dumps(entries, indent=2) + '\n', encoding='utf8')
    inventory = {p.relative_to(target).as_posix(): digest(p) for p in sorted(target.rglob('*')) if p.is_file()}
    receipt = {'schema_version': 1, 'kind': 'falcor_marked_gltf_factor_runtime',
        'baseline_receipt_sha256': digest(SOURCE / 'receipt.json'),
        'input_sha256': {p.relative_to(ROOT).as_posix(): digest(p) for p in INPUTS},
        'shader_changes': changes, 'manifest_original_sha256': old_manifest,
        'marker_bit': 20, 'required_scene_settings': {'dont_optimize_materials': True, 'scene_cache': False},
        'limitations': 'BLEND is approximated as mask when explicitly configured; differentiable material path is unsupported. BSDF and thin transmission equivalence to RTXDI are not asserted.',
        'runtime_files_sha256': inventory}
    (DEST / 'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf8')
    print('Created', DEST, 'with', len(inventory), 'verified files')

def verify():
    receipt = json.loads((DEST / 'receipt.json').read_text(encoding='utf8'))
    if digest(SOURCE / 'receipt.json') != receipt['baseline_receipt_sha256']:
        raise RuntimeError('Baseline receipt changed')
    for rel, expected in receipt['input_sha256'].items():
        if digest(ROOT / rel) != expected:
            raise RuntimeError('Input changed: ' + rel)
    for rel, expected in receipt['runtime_files_sha256'].items():
        if digest(DEST / 'runtime' / rel) != expected:
            raise RuntimeError('Runtime changed: ' + rel)
    print('Verified', len(receipt['runtime_files_sha256']), 'runtime files')
    return receipt

if __name__ == '__main__':
    if sys.argv[1:] == ['--verify']:
        verify()
    elif not sys.argv[1:]:
        prepare()
    else:
        raise SystemExit('Usage: prepare_gltf_factor_runtime.py [--verify]')
