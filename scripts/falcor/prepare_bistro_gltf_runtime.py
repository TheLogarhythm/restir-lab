"""Prepare a separate, fingerprinted runtime for Bistro glTF diagnostics."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
from bistro_gltf_shader_patch import patch_sources
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'build/falcor-reference-runtime'
DEST=ROOT/'build/falcor-bistro-gltf-runtime'
FILES={'standard':'shaders/Rendering/Materials/StandardMaterial.slang',
       'system':'shaders/Scene/Material/MaterialSystem.slang',
       'finalize':'shaders/Scene/Lights/FinalizeIntegration.cs.slang'}

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def prepare():
    if DEST.exists(): raise FileExistsError(DEST)
    receipt=json.loads((SOURCE/'receipt.json').read_text(encoding='utf8'))
    source=SOURCE/'runtime'; target=DEST/'runtime'
    original={key:(source/rel).read_text(encoding='utf8') for key,rel in FILES.items()}
    patches=patch_sources(original)
    target.mkdir(parents=True)
    for rel,expected in receipt['runtime_files_sha256'].items():
        src=source/rel
        if digest(src)!=expected: raise RuntimeError('Source runtime mismatch: '+rel)
        dst=target/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
        if digest(dst)!=expected: raise RuntimeError('Copy mismatch: '+rel)
    changed={}
    for key,rel in FILES.items():
        p=target/rel;p.write_text(patches[key],encoding='utf8',newline='\n')
        changed[rel]={'source_sha256':digest(source/rel),'patched_sha256':digest(p)}
    inventory={p.relative_to(target).as_posix():digest(p) for p in sorted(target.rglob('*')) if p.is_file()}
    result={'kind':'bistro_gltf_factor_diagnostic_only','source_receipt_sha256':digest(SOURCE/'receipt.json'),
      'patch_source_sha256':digest(ROOT/'scripts/falcor/bistro_gltf_shader_patch.py'),
      'changes':changed,'limitations':'Requires DontOptimizeMaterials; alpha BLEND remains unsupported; diagnostic only.',
      'runtime_files_sha256':inventory}
    (DEST/'receipt.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print('Created diagnostic runtime:',len(inventory),'files')

def verify():
    record=json.loads((DEST/'receipt.json').read_text(encoding='utf8'))
    if digest(SOURCE/'receipt.json')!=record['source_receipt_sha256']:raise RuntimeError('Source receipt changed')
    if digest(ROOT/'scripts/falcor/bistro_gltf_shader_patch.py')!=record['patch_source_sha256']:raise RuntimeError('Patch source changed')
    for rel,expected in record['runtime_files_sha256'].items():
        if digest(DEST/'runtime'/rel)!=expected:raise RuntimeError('Runtime mismatch: '+rel)
    print('Verified diagnostic runtime:',len(record['runtime_files_sha256']),'files')
    return record

if __name__=='__main__':
    if sys.argv[1:]==['--verify']:verify()
    elif not sys.argv[1:]:prepare()
    else:raise SystemExit('Usage: prepare_bistro_gltf_runtime.py [--verify]')
