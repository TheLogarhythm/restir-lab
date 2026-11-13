"""Freeze an explicitly configured Donut/glTF scene for adapted Falcor runs."""
import json
import os
from pathlib import Path
from . import donut_scene_adapter, gltf_materials
from .adapted_reference_runner import file_sha256
from .project_paths import remap_plan_paths, resolve_workspace_path, workspace_path

ROOT=Path(__file__).resolve().parents[2]


def record(path):
    path=resolve_workspace_path(path,ROOT,strict=True)
    return {'path':workspace_path(path,ROOT),'bytes':path.stat().st_size,'sha256':file_sha256(path)}


def build_scene_script():
    """Return the portable scene loader used for a new or migrated plan."""
    return ('from pathlib import Path\nimport sys, json, falcor\n'
        +"root = next((p for p in Path(__file__).resolve().parents if (p / 'scripts/falcor/adapted_scene_loader.py').is_file()), None)\n"
        +"if root is None: raise RuntimeError('Cannot locate project root for adapted scene')\n"
        +"sys.path.insert(0,str(root))\n"
        +'from scripts.falcor.adapted_scene_loader import load_plan_file\n'
        +"audit=load_plan_file(sceneBuilder,falcor,Path(__file__).resolve().with_name('scene-plan.json'),project_root=root,factor_shader_verified=True,material_optimization_disabled=True)\n"
        +"Path('scene-audit.json').write_text(json.dumps(audit,indent=2,allow_nan=False),encoding='utf-8')\n")


def prepare(spec_path,output,runtime_receipt_path):
    spec_path=resolve_workspace_path(spec_path,ROOT,strict=True)
    output=resolve_workspace_path(output,ROOT)
    runtime_receipt_path=resolve_workspace_path(runtime_receipt_path,ROOT,strict=True)
    spec=json.loads(spec_path.read_text(encoding='utf-8-sig'))
    scene_file=resolve_workspace_path(spec['scene_file'],ROOT,strict=True)
    asset_root=resolve_workspace_path(spec['asset_root'],ROOT,strict=True)
    env=dict(spec['environment'])
    for key in ('path','baked_hdr','bake_receipt','fallback_hdr'):
        if key in env and env[key] is not None:
            # Unselected fallback paths may be absent; the chosen image and
            # receipt are checked when the selected policy consumes them.
            env[key]=str(resolve_workspace_path(env[key],ROOT))
    sky_sources=[]
    if env['kind']=='procedural':
        receipt=json.loads(Path(env['bake_receipt']).read_text(encoding='utf-8-sig'))
        if file_sha256(env['baked_hdr'])!=receipt['sha256']:
            raise ValueError('Sky image differs from bake receipt')
        for source,digest in receipt['source_sha256'].items():
            resolved=resolve_workspace_path(source,ROOT,strict=True)
            if file_sha256(resolved)!=digest:raise ValueError('Sky bake source changed: '+source)
            sky_sources.append(resolved)
    ies_dirs=spec.get('ies_dirs')
    if ies_dirs is not None:
        ies_dirs=[str(resolve_workspace_path(path,ROOT,strict=True)) for path in ies_dirs]
    scene=donut_scene_adapter.plan_scene(scene_file,asset_root,
        animation_policy=spec['animation_policy'],camera_policy='external',
        source_lighting_model=spec['source_lighting_model'],environment=env,
        approximations=spec['approximations'],ignored_top_level=spec.get('ignored_top_level'),
        ies_dirs=ies_dirs)
    donut_scene_adapter.require_supported(scene)
    models=[]; model_actions=[x for x in scene['actions'] if x['kind']=='model']
    for action in model_actions:
        gltf=json.loads(Path(action['source']).read_text(encoding='utf-8-sig'))
        if 'KHR_lights_punctual' in gltf.get('extensionsUsed',[]) or 'KHR_lights_punctual' in gltf.get('extensionsRequired',[]) or 'KHR_lights_punctual' in gltf.get('extensions',{}) or any('KHR_lights_punctual' in n.get('extensions',{}) for n in gltf.get('nodes',[])):
            raise ValueError('Embedded glTF lights require explicit translation and auditing')
        material=gltf_materials.build_material_plan(action['source'],
            blend_policy=spec.get('blend_policy','reject'),asset_root=asset_root)
        models.append({'source':action['source'],'world_matrix':action['world_matrix'],
                       'material_plan':material})
    output.mkdir(parents=True,exist_ok=False)
    descriptors=[]
    for i,model in enumerate(models):
        desc=output/('model-%02d.labgltf'%i)
        source=resolve_workspace_path(model['source'],ROOT,strict=True)
        relative_source=Path(os.path.relpath(source,desc.parent)).as_posix()
        desc.write_text(relative_source+'\n'+' '.join(format(v,'.17g') for row in model['world_matrix'] for v in row)+'\n',encoding='utf-8')
        model['descriptor']=str(desc);descriptors.append(desc)
    plan=output/'scene-plan.json'
    portable=remap_plan_paths({'scene':scene,'models':models},ROOT,to_absolute=False)
    portable['path_format']='workspace-relative-v1'
    plan.write_text(json.dumps(portable,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    scene_script=output/'adapted.pyscene'
    scene_script.write_text(build_scene_script(),encoding='utf-8')
    sources=[spec_path,plan,scene_script,*descriptors,*sky_sources,
             ROOT/'scripts/falcor/adapted_scene_loader.py',
             ROOT/'scripts/falcor/project_paths.py',
             ROOT/'scripts/falcor/donut_scene_adapter.py',ROOT/'scripts/falcor/gltf_materials.py',
             Path(__file__).resolve()]
    resources=[*scene['dependencies']]
    for model in models:resources.extend(model['material_plan']['resources'])
    config={'schema_version':1,'scene_id':spec['scene_id'],'view_id':spec['view_id'],
            'ready_for_reference':False,'scene_source':workspace_path(scene_script,ROOT,strict=True),
            'camera':spec['camera'],'resources':remap_plan_paths(resources,ROOT,to_absolute=False),'sources':[record(p) for p in sources],
            'runtime_receipt_sha256':file_sha256(runtime_receipt_path),
            'expected_light_count':sum(x['kind']=='light' for x in scene['actions']),
            'expected_environment_present':scene['environment']['effective_kind']=='hdr',
            'expected_material_counts':[len(x['material_plan']['materials']) for x in models],
            'expected_texture_slots':[sum(v is not None for row in x['material_plan']['materials']
                                           for v in row['textures'].values()) for x in models],
            'limitations':[x['detail'] for x in scene['issues'] if x['severity']!='error']
                          +[s for m in models for s in m['material_plan']['limitations']]}
    config_path=output/'scout-config.json'
    config_path.write_text(json.dumps(config,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return config_path



