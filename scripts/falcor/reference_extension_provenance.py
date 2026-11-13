"""Verify original reference images and frozen inputs before adding samples."""
from collections import Counter
from copy import deepcopy
from pathlib import Path, PureWindowsPath, PurePosixPath
import json
import numpy as np
from . import reference_runner, adapted_reference_runner
from .project_paths import resolve_workspace_path, workspace_path

ROOT=Path(__file__).resolve().parents[2]
SHA=adapted_reference_runner.file_sha256
IMAGE_SHAPE=(1080,1920,3)


def _baseline_paths(baseline, root, *, expand):
    """Copy known baseline paths across the workspace serialization boundary."""
    root=Path(root).resolve(strict=True)
    record=deepcopy(baseline)
    def convert(value):
        if not isinstance(value,str) or not value:
            raise ValueError('Invalid baseline path')
        if expand:
            if PureWindowsPath(value).drive or PureWindowsPath(value).root or '\\' in value or PurePosixPath(value).is_absolute():
                raise ValueError('Expected workspace-relative baseline path')
            resolved=resolve_workspace_path(value,root)
            if workspace_path(resolved,root)!=value:
                raise ValueError('Noncanonical baseline path')
            return str(resolved)
        path=Path(value)
        if not path.is_absolute():raise ValueError('Expected absolute in-memory baseline path')
        return workspace_path(path,root)
    record['old_root']=convert(record['old_root'])
    for view in record['views']:
        for field in ('config_path','old_reference'):
            view[field]=convert(view[field])
        for seed in view['old_seeds']:
            for field in ('image','manifest'):
                seed[field]=convert(seed[field])
    return record


def portable_baseline(baseline, root):
    """Produce a portable snapshot without altering the verified evidence."""
    if baseline.get('schema_version')!=1:raise ValueError('Expected in-memory baseline schema 1')
    record=_baseline_paths(baseline,root,expand=False)
    record['schema_version']=2;record['path_base']='workspace'
    return record


def expand_portable_baseline(baseline, root):
    """Resolve only the documented paths of a portable baseline inside root."""
    if baseline.get('schema_version')!=2 or baseline.get('path_base')!='workspace':
        raise ValueError('Invalid portable baseline format')
    return _baseline_paths(baseline,root,expand=True)


def _pure_path(value):
    """Interpret historical Windows paths independently of the host OS."""
    text=str(value)
    windows=PureWindowsPath(text)
    return windows if windows.drive or '\\' in text else PurePosixPath(text)


def historical_workspace(record):
    """Derive a historical workspace root from a frozen comparison root."""
    if not isinstance(record,dict) or not isinstance(record.get('old_root'),str):
        raise ValueError('Historical comparison root is missing')
    path=_pure_path(record['old_root'])
    if not path.is_absolute() or tuple(p.lower() for p in path.parts[-2:]) != ('runs','falcor-pt-spatial-comparison') or '..' in path.parts:
        raise ValueError('Unexpected historical comparison root')
    return path.parent.parent


def workspace_relative(value, workspace):
    """Return a contained path relative to a known workspace, never guess roots."""
    path=_pure_path(value)
    root=_pure_path(workspace)
    if (not root.is_absolute() or '..' in root.parts or '..' in path.parts or
            (path.root and not path.is_absolute())):
        raise ValueError('Invalid workspace path')
    if path.is_absolute() or path.drive:
        if type(path) is not type(root):raise ValueError('Path is outside workspace')
        try:path=path.relative_to(root)
        except ValueError as exc:raise ValueError('Path is outside workspace') from exc
    if path.is_absolute() or path.drive or not path.parts or any(p in ('.','..') for p in path.parts):
        raise ValueError('Path is outside workspace')
    return path.as_posix()


def _portable_file(root, value):
    """Resolve a receipt's POSIX relative path inside the current workspace."""
    if (not isinstance(value,str) or not value or '\\' in value or
            PureWindowsPath(value).drive or PurePosixPath(value).is_absolute() or
            any(part in ('.','..') for part in PurePosixPath(value).parts)):
        raise ValueError('Portable receipt requires a safe relative path')
    root=Path(root).resolve(strict=True)
    path=(root/value).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('Portable receipt path escapes workspace')
    return path


def historical_copy_map(receipt, old_root, current_root):
    """Resolve an immutable historical copy receipt in the current workspace."""
    root=Path(current_root).resolve(strict=True);result={}
    if not isinstance(receipt,dict) or not isinstance(receipt.get('copies'),list):
        raise ValueError('Invalid historical copy receipt')
    for item in receipt['copies']:
        original=workspace_relative(item['original'],old_root)
        preserved=workspace_relative(item['preserved'],old_root)
        destination=(root/preserved).resolve()
        if not destination.is_relative_to(root) or original in result:
            raise ValueError('Invalid historical copy mapping')
        result[original]=destination
    return result


_SEMANTIC_PATH_FIELDS=frozenset(('path','source','descriptor','scene_file','asset_root',
                                 'ies_path','baked_hdr','bake_receipt','fallback_hdr','image'))


def validate_portable_json_semantics(old, new, historical_root, mapping, *, marker=False, current_root=None):
    """Reject JSON changes other than the approved relocation of path records."""
    def transform(value, key=None):
        if isinstance(value,list):return [transform(x) for x in value]
        if isinstance(value,dict):
            original_path=value.get('path')
            old_rel=workspace_relative(original_path,historical_root) if isinstance(original_path,str) else None
            row=mapping.get(old_rel)
            result={}
            for k,v in value.items():
                new_key=k
                if _pure_path(k).is_absolute():
                    old_key=workspace_relative(k,historical_root)
                    key_row=mapping.get(old_key)
                    new_key=key_row['new_path'] if key_row else old_key
                    if key_row and isinstance(v,str) and v==key_row.get('old_sha256'):
                        v=key_row['new_sha256']
                if row and k=='sha256':
                    if v!=row['old_sha256']:raise ValueError('Historical JSON path hash differs')
                    result[new_key]=row['new_sha256']
                elif row and k=='bytes':
                    if current_root is None:raise ValueError('Current root required for relocated file sizes')
                    result[new_key]=_portable_file(current_root,row['new_path']).stat().st_size
                else:result[new_key]=transform(v,k)
            return result
        if isinstance(value,str) and key in _SEMANTIC_PATH_FIELDS:
            relative=workspace_relative(value,historical_root)
            return mapping[relative]['new_path'] if relative in mapping else relative
        return value
    actual=deepcopy(new)
    if marker:
        if not isinstance(actual,dict) or actual.pop('path_format',None)!='workspace-relative-v1':
            raise ValueError('Missing portable plan path format')
    if transform(old)!=actual:raise ValueError('Portable JSON differs beyond approved paths')


def verify_bistro_migration_semantics(mapping, historical_root, current_root, reference_root):
    """Prove the portable scene plan, descriptors and sky retain source semantics."""
    prefix='runs/falcor-pt-spatial-comparison/scene-assets/bistro/'
    old_scene=prefix+'frozen-scene/'
    required={'experiments/configs/falcor-pt-spatial-comparison/bistro-gltf-direct-spec.json',
              old_scene+'scene-plan.json',old_scene+'adapted.pyscene',prefix+'sky/bake-receipt.json',
              *(old_scene+f'model-{i:02d}.labgltf' for i in range(3)),
              'scripts/falcor/adapted_scene_loader.py','scripts/falcor/prepare_adapted_scene.py'}
    if set(mapping)!=required:raise ValueError('Unexpected Bistro migration source set')
    root=Path(current_root).resolve(strict=True)
    def contents(relative):
        row=mapping[relative]
        return _portable_file(root,row['old_path']),_portable_file(root,row['new_path'])
    for name,marker in (('experiments/configs/falcor-pt-spatial-comparison/bistro-gltf-direct-spec.json',False),
                        (old_scene+'scene-plan.json',True)):
        before,after=contents(name)
        validate_portable_json_semantics(_load(before),_load(after),historical_root,mapping,
                                         marker=marker,current_root=root)
    before,after=contents(prefix+'sky/bake-receipt.json')
    original_sky=_load(before);portable_sky=_load(after)
    old_image=workspace_relative(original_sky['image'],historical_root)
    legacy=_load(Path(reference_root)/'scene-assets/bistro/migration-receipt.json')
    copies=historical_copy_map(legacy,historical_root,root)
    target=copies.get(old_image)
    if target is None or not target.is_file() or SHA(target)!=original_sky['sha256']:
        raise ValueError('Historic Bistro sky image cannot be verified')
    target_relative=target.relative_to(root).as_posix()
    sky_mapping={**mapping,old_image:{'new_path':target_relative,
                                     'old_sha256':original_sky['sha256'],
                                     'new_sha256':original_sky['sha256']}}
    validate_portable_json_semantics(original_sky,portable_sky,historical_root,sky_mapping,current_root=root)
    for i in range(3):
        before,after=contents(old_scene+f'model-{i:02d}.labgltf')
        old_data=before.read_bytes().split(b'\n',1);new_data=after.read_bytes().split(b'\n',1)
        if len(old_data)!=2 or len(new_data)!=2 or old_data[1]!=new_data[1]:
            raise ValueError('Bistro model descriptor transform differs')
        old_source=workspace_relative(old_data[0].decode('utf8').strip(),historical_root)
        new_source=new_data[0].decode('utf8').strip()
        if (not new_source or PureWindowsPath(new_source).drive or PurePosixPath(new_source).is_absolute()
                or '\\' in new_source):raise ValueError('Invalid portable model descriptor path')
        target=(after.parent/new_source).resolve(strict=True)
        if not target.is_relative_to(root) or target!=_portable_file(root,old_source):
            raise ValueError('Bistro model descriptor points to a different source')
    from .prepare_adapted_scene import build_scene_script
    _,script=contents(old_scene+'adapted.pyscene')
    if script.read_bytes()!=build_scene_script().encode('utf8'):
        raise ValueError('Portable Bistro scene loader differs from verified template')


def portable_bistro_entry(entry, historical_root, current_root, reference_root):
    """Verify the versioned path migration without changing historical records.

    Every changed inventory entry must map to a separately hashed historical
    snapshot and current file. All other scene settings and records are equal.
    """
    current_root=Path(current_root).resolve(strict=True)
    reference_root=Path(reference_root).resolve(strict=True)
    if not reference_root.is_relative_to(current_root):raise ValueError('Reference root escapes workspace')
    history=reference_root/'scene-assets/bistro/frozen-scene/scout-config.json'
    active=current_root/'experiments/configs/falcor-pt-spatial-comparison/bistro-interior-reference.json'
    receipt_path=reference_root/'provenance/relocations/bistro-portable-v1.json'
    try:
        receipt=_load(receipt_path);old=_load(history);new=_load(active)
        if (receipt.get('schema_version')!=1 or receipt.get('kind')!='bistro_portable_scene_v1'
                or receipt.get('historical_config_sha256')!=entry['config_sha256']
                or SHA(history)!=entry['config_sha256'] or SHA(active)!=receipt.get('portable_config_sha256')):
            raise ValueError('Bistro portable config provenance differs')
        rows=receipt['files']
        if not isinstance(rows,list):raise ValueError('Invalid Bistro migration file list')
        mapping={};new_paths=set()
        for row in rows:
            if not isinstance(row,dict) or set(row)!={'historical_path','old_path','old_sha256','new_path','new_sha256'}:
                raise ValueError('Invalid Bistro migration mapping')
            historic=workspace_relative(row['historical_path'],historical_root)
            if historic!=row['historical_path'] or historic in mapping or row['new_path'] in new_paths:
                raise ValueError('Duplicate or nonportable Bistro mapping')
            old_file=_portable_file(current_root,row['old_path']);new_file=_portable_file(current_root,row['new_path'])
            if SHA(old_file)!=row['old_sha256'] or SHA(new_file)!=row['new_sha256']:
                raise ValueError('Bistro migration source hash differs')
            mapping[historic]=row;new_paths.add(row['new_path'])
        seen=set()
        def mapped_path(value):
            relative=workspace_relative(value,historical_root)
            if relative in mapping:
                seen.add(relative);return mapping[relative]['new_path']
            return relative
        def mapped_records(records):
            if not isinstance(records,list):raise ValueError('Invalid Bistro source records')
            result=[]
            for item in records:
                if not isinstance(item,dict):raise ValueError('Invalid Bistro source record')
                copy=deepcopy(item);relative=workspace_relative(item['path'],historical_root)
                copy['path']=mapped_path(item['path'])
                if relative in mapping:
                    row=mapping[relative]
                    if item.get('sha256')!=row['old_sha256']:raise ValueError('Historical source record differs')
                    copy['sha256']=row['new_sha256']
                    if 'bytes' in copy:copy['bytes']=_portable_file(current_root,row['new_path']).stat().st_size
                result.append(copy)
            return result
        expected=deepcopy(old)
        expected['scene_source']=mapped_path(old['scene_source'])
        expected['resources']=mapped_records(old['resources'])
        expected['sources']=mapped_records(old['sources'])
        added=receipt['added_sources']
        if not isinstance(added,list) or len(added)!=1 or added[0].get('path')!='scripts/falcor/project_paths.py':
            raise ValueError('Unexpected additional Bistro sources')
        extra=added[0]
        if set(extra)!={'path','sha256','bytes'}:raise ValueError('Invalid additional Bistro source')
        extra_file=_portable_file(current_root,extra['path'])
        if SHA(extra_file)!=extra['sha256'] or extra_file.stat().st_size!=extra['bytes']:
            raise ValueError('Additional Bistro source differs')
        expected['sources'].append(extra)
        if seen!=set(mapping):raise ValueError('Unreferenced Bistro migration mapping')
        if new!=expected:raise ValueError('Bistro config differs beyond approved path migration')
        verify_bistro_migration_semantics(mapping,historical_root,current_root,reference_root)
        def mapped_inventory(inventory):
            if not isinstance(inventory,dict):raise ValueError('Invalid historical inventory')
            result={}
            for key,digest in inventory.items():
                relative=workspace_relative(key,historical_root)
                row=mapping.get(relative)
                if row and row['old_sha256']!=digest:raise ValueError('Historical inventory hash differs')
                target=row['new_path'] if row else relative
                value=row['new_sha256'] if row else digest
                if target in result:raise ValueError('Duplicate migrated inventory path')
                result[target]=value
            return result
        assets=mapped_inventory(entry['asset_sha256']);sources=mapped_inventory(entry['source_sha256'])
        if extra['path'] in sources:raise ValueError('Additional source already present')
        sources[extra['path']]=extra['sha256']
        # Avoid repeatedly hashing the entire texture set during catalog lookup.
        # reference_extension_batch.recheck_view() verifies both inventories
        # against these derived hashes before and after each actual render.
    except (OSError,KeyError,TypeError) as exc:
        raise ValueError('Bistro portable migration data is incomplete') from exc
    return {**entry,'config_path':str(active),'config_sha256':receipt['portable_config_sha256'],
            'asset_sha256':assets,'source_sha256':sources}


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _bistro_equivalent(old, new, old_root, seed):
    base=old_root/'scene-assets/bistro'
    original_config=base/'provenance/frozen-scene-06/reference-config.json'
    original_plan=base/'provenance/frozen-scene-06/scene-plan.json'
    migrated_plan=base/'frozen-scene/scene-plan.json'
    archived=_load(original_config);a=_load(original_plan);b=_load(migrated_plan)
    if SHA(original_config)!=seed['config_sha256'] or archived!=old:
        raise ValueError('Historical Bistro configuration mismatch')
    for key in ('camera','expected_material_counts','expected_texture_slots','expected_light_count','expected_environment_present','runtime_receipt_sha256'):
        if archived[key]!=new[key]:raise ValueError('Bistro setting differs: '+key)
    for key in ('actions','approximations','animation','source_lighting_model','ignored_top_level','runtime_requirements','cameras'):
        if a['scene'].get(key)!=b['scene'].get(key):raise ValueError('Bistro scene differs: '+key)
    for model1,model2 in zip(a['models'],b['models']):
        for key in ('source','world_matrix','material_plan'):
            if model1[key]!=model2[key]:raise ValueError('Bistro model differs: '+key)
    if len(a['models'])!=len(b['models']):raise ValueError('Bistro model count differs')
    env1=dict(a['scene']['environment']);env2=dict(b['scene']['environment'])
    for e in (env1,env2):
        e.pop('path',None);e.pop('bake_receipt',None)
        if 'source_config' in e:
            e['source_config']=dict(e['source_config']);e['source_config'].pop('baked_hdr',None);e['source_config'].pop('bake_receipt',None)
    if env1!=env2:raise ValueError('Bistro environment differs')
    if Counter(x['sha256'] for x in a['scene']['dependencies'])!=Counter(x['sha256'] for x in b['scene']['dependencies']):raise ValueError('Bistro dependency content differs')
    original_assets=seed['asset_sha256'];assets=adapted_reference_runner.inventory_resources(new['resources'],ROOT)
    oldprefix='runs/bistro-gltf-general-20261111/sky-03/';newprefix='runs/falcor-pt-spatial-comparison/scene-assets/bistro/sky/'
    remapped={(newprefix+k[len(oldprefix):] if k.startswith(oldprefix) else k):v for k,v in original_assets.items()}
    portable_path=old_root/'provenance/relocations/bistro-portable-v1.json'
    portable=_load(portable_path) if portable_path.is_file() else None
    if portable is not None:
        for row in portable['files']:
            historic=row['historical_path']
            if historic in remapped:
                if remapped[historic]!=row['old_sha256']:raise ValueError('Historical Bistro asset hash differs')
                del remapped[historic]
                if row['new_path'] in remapped:raise ValueError('Duplicate portable Bistro asset')
                remapped[row['new_path']]=row['new_sha256']
    if remapped!=assets:raise ValueError('Bistro asset paths or hashes differ beyond sky relocation')
    relocated=adapted_reference_runner.inventory_resources(new['sources'],ROOT)
    receipt=_load(base/'migration-receipt.json')
    baseline=old_root/'provenance/original/reference/baseline.json'
    historic_root=historical_workspace(_load(baseline)) if baseline.is_file() else ROOT
    source_copies=historical_copy_map(receipt,historic_root,ROOT)
    portable_copies={}
    if portable is not None:
        portable_copies={row['historical_path']:_portable_file(ROOT,row['old_path']) for row in portable['files']}
    for key,digest in seed['source_sha256'].items():
        relative=workspace_relative(key,historic_root)
        candidates=[p for p in (source_copies.get(relative),portable_copies.get(relative),ROOT/relative) if p is not None]
        if not any(p.is_file() and SHA(p)==digest for p in candidates):raise ValueError('Historical Bistro source changed: '+key)
    return assets,relocated


def verify_baseline(old_root,config_paths):
    """Recheck six 8192-spp views, scene identity, runtime and source provenance.

    config_paths is an iterable of six JSON paths. Return JSON-serializable
    evidence; raise before GPU work on any mismatch. Historical Bistro paths are
    checked against the documented byte-identical relocation, not rewritten.
    """
    from src.image_io.exr import read_exr
    old_root=Path(old_root).resolve(strict=True)
    if not old_root.is_relative_to(ROOT):raise ValueError('Reference outside workspace')
    index=_load(old_root/'manifest.json');configs={}
    for p in config_paths:
        path=Path(p).resolve(strict=True);c=_load(path);key=(c['scene_id'],c['view_id'])
        if key in configs:raise ValueError('Duplicate scene config')
        configs[key]=(path,c)
    wanted={(v['scene_id'],v['view_id']) for v in index['views']}
    if len(wanted)!=6 or set(configs)!=wanted:raise ValueError('Need the six distinct existing views')
    graph=SHA(ROOT/'scripts/falcor/reference_graph.py');views=[]
    for view in index['views']:
        key=(view['scene_id'],view['view_id']);path,config=configs[key];adapted=key==('bistro','view-a')
        receipt=ROOT/('build/falcor-gltf-composite-runtime-v3/receipt.json' if adapted else 'build/falcor-reference-runtime/receipt.json');runtime_sha=SHA(receipt)
        if len(view['seeds'])!=8:raise ValueError('Need exactly 8 old seed images')
        seed_records=[];first=None;total=None
        for number,record in enumerate(view['seeds']):
            if record['index']!=number:raise ValueError('Old seed order differs')
            manifest=(old_root/record['manifest']).resolve(strict=True);image=(old_root/record['path']).resolve(strict=True)
            if not manifest.is_relative_to(old_root) or not image.is_relative_to(old_root):raise ValueError('Old seed escapes root')
            if SHA(manifest)!=record['manifest_sha256'] or SHA(image)!=record['sha256']:raise ValueError('Old seed artifact hash mismatch')
            m=_load(manifest)
            if (m['status']!='completed' or m['seed_index']!=number or m['samples_per_pixel']!=1024 or m['resolution']!=[1920,1080] or m['sample_seed_first']!=number*1024 or m['sample_seed_last']!=number*1024+1023):raise ValueError('Old seed budget mismatch')
            if m['graph_sha256']!=graph or m.get('runtime_receipt_sha256',m.get('isolated_runtime_receipt_sha256'))!=runtime_sha:raise ValueError('Old graph or runtime receipt differs')
            comparison={k:m.get(k) for k in ('scene_config','config_sha256','asset_sha256','source_sha256','graph_sha256','runtime_receipt_sha256','isolated_runtime_receipt_sha256')}
            if first is None:first=comparison;seed=m
            elif comparison!=first:raise ValueError('Old seeds have differing provenance')
            im=read_exr(image,require_float32=True)
            if im.shape!=IMAGE_SHAPE:raise ValueError('Old seed image dimensions differ')
            if total is None:total=np.zeros(im.shape,dtype=np.float64)
            total+=im.astype(np.float64)/8
            seed_records.append({'index':number,'image':str(image),'sha256':record['sha256'],'manifest':str(manifest),'manifest_sha256':record['manifest_sha256'],'sample_seed_first':m['sample_seed_first'],'sample_seed_last':m['sample_seed_last']})
        ref=(old_root/view['reference']).resolve(strict=True)
        if not ref.is_relative_to(old_root) or SHA(ref)!=view['reference_sha256']:raise ValueError('Old reference hash mismatch')
        if not np.array_equal(total.astype(np.float32),read_exr(ref,require_float32=True)):raise ValueError('Old reference is not average of 8 seeds')
        if adapted:
            assets,sources=_bistro_equivalent(seed['scene_config'],config,old_root,seed)
        else:
            if SHA(path)!=seed['config_sha256'] or config!=seed['scene_config']:raise ValueError('Scene configuration differs')
            assets=reference_runner.asset_inventory(config);sources={}
            if assets!=seed['asset_sha256']:raise ValueError('Scene assets differ')
        views.append({'scene_id':key[0],'view_id':key[1],'adapted':adapted,'config_path':str(path),'config_sha256':SHA(path),'old_config_sha256':seed['config_sha256'],'graph_sha256':graph,'runtime_receipt_sha256':runtime_sha,'asset_sha256':assets,'source_sha256':sources,'old_reference':str(ref),'old_reference_sha256':view['reference_sha256'],'old_seeds':seed_records,'old_reference_average_verified':True,'notes':'Scene moved; historical config and source files verified through relocation receipt; current config remains unqualified.' if adapted else 'Original config and asset inventory match.'})
    return {'schema_version':1,'kind':'reference_extension_baseline','old_root':str(old_root),'views':views}

