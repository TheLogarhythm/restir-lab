"""Apply a frozen generic scene plan, transformed models, and material plans."""
import json
from pathlib import Path
from . import donut_scene_adapter, gltf_materials
from .project_paths import remap_plan_paths, resolve_workspace_path

ROOT=Path(__file__).resolve().parents[2]


def load_adapted_scene(builder, falcor, scene_plan, models, *, factor_shader_verified=False, material_optimization_disabled=False):
    """Each ordered model provides source, matrix, descriptor and material_plan."""
    if not factor_shader_verified or not material_optimization_disabled:
        raise ValueError('Verified factor shader and disabled material optimization are required')
    expected=[a for a in scene_plan['actions'] if a['kind']=='model']
    if len(models)!=len(expected): raise ValueError('Model action count mismatch')
    for model,action in zip(models,expected):
        if model['source']!=action['source'] or model['world_matrix']!=action['world_matrix']:
            raise ValueError('Model action source or matrix mismatch')
        if model['material_plan']['source']!=action['source']:
            raise ValueError('Material plan source differs from imported model')
    audits=[]
    iterator=iter(models)
    def load(source,matrix):
        model=next(iterator)
        if source!=model['source'] or matrix!=model['world_matrix']:
            raise ValueError('Model callback action differs from frozen plan')
        offset=len(list(builder.materials))
        builder.importScene(str(model['descriptor']))
        audit=gltf_materials.apply_material_plan(builder,model['material_plan'],falcor,
                factor_shader_verified=factor_shader_verified,material_optimization_disabled=material_optimization_disabled,material_offset=offset)
        audits.append(audit)
    issues=donut_scene_adapter.apply_plan(scene_plan,builder,falcor,load)
    return {'models':audits,'issues':issues}


def load_plan_file(builder,falcor,plan_file,*,factor_shader_verified=False,material_optimization_disabled=False,project_root=None):
    root=ROOT if project_root is None else Path(project_root)
    path=resolve_workspace_path(plan_file,root,strict=True)
    plan=json.loads(path.read_text(encoding='utf-8-sig'))
    if plan.get('path_format') not in (None,'workspace-relative-v1'):
        raise ValueError('Unsupported scene plan path format')
    normalized=remap_plan_paths({'scene':plan['scene'],'models':plan['models']},root,to_absolute=True)
    return load_adapted_scene(builder,falcor,normalized['scene'],normalized['models'],factor_shader_verified=factor_shader_verified,material_optimization_disabled=material_optimization_disabled)

