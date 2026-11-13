# Bounded CGNS ReSTIR PT smoke runs for the six frozen reference views.
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess

from . import cgns_pt_smoke as smoke, cgns_runtime, reference_runner, reference_runtime
from . import adapted_reference_runner, prepare_gltf_composite_runtime_v3 as gltf_runtime
from . import run
from .process_utils import check_renderer_idle, exclusive_operation

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / 'runs/falcor-pt-spatial-comparison'
EXTENSION = REFERENCE / 'reference-16384-20261111'
BISTRO_INTERIOR_CONFIG = ROOT / 'experiments/configs/falcor-pt-spatial-comparison/bistro-interior-reference.json'
KEYS = {('bistro','view-a'),('bistro','view-b'),('classroom','view-a'),
        ('emerald-square','view-a'),('veach-ajar','view-a'),('zero-day-measure-seven','view-a')}
EMERALD_OLD_SCENE = 'scenes/configs/falcor/emerald-square-converted-scout.pyscene'
EMERALD_NEW_SCENE = 'scenes/configs/falcor/emerald-square-converted-reference.pyscene'


def _migrated():
    """Recognize the new view catalog without changing historical receipts."""
    index = json.loads((REFERENCE/'manifest.json').read_text(encoding='utf-8-sig'))
    return index.get('kind') == 'falcor_pt_spatial_view_catalog'


def historical_extension_manifest_path():
    if _migrated():
        return REFERENCE/'provenance/original/reference/extension-manifest.json'
    return EXTENSION/'manifest.json'


def historical_baseline_path():
    if _migrated():
        return REFERENCE/'provenance/original/reference/baseline.json'
    return EXTENSION/'baseline.json'


def old_manifest_path():
    if _migrated():
        return REFERENCE/'provenance/original/reference/old-manifest.json'
    return REFERENCE/'manifest.json'


def _historical_reference(key):
    manifest = json.loads(historical_extension_manifest_path().read_text(encoding='utf-8-sig'))
    matches = [v for v in manifest['views'] if (v['scene_id'],v['view_id']) == key]
    if len(matches) != 1 or matches[0].get('status') != 'completed':
        raise ValueError('Reference view missing')
    return matches[0]


def validate_reference_for_view(
    key, experiment=None, *, config=None, entry=None, require_image=False
):
    """Validate fixed-reference identity independently of historical runs and EXR presence."""
    from . import reference_catalog, spatial_experiment_config

    if experiment is None:
        experiment = spatial_experiment_config.load_config()
    catalog = reference_catalog.load_catalog(
        reference_catalog_path(experiment), ROOT, require_images=False
    )
    if set(catalog) != KEYS or key not in catalog:
        raise ValueError("Reference view set differs")
    if entry is None:
        entry = frozen_views()[key]
    if config is None:
        config = load_config(entry["config_path"])
    if (config.get("scene_id"), config.get("view_id")) != key:
        raise ValueError("Reference view identity differs")
    record = reference_catalog.validate_binding(catalog[key], config, entry, experiment)
    if require_image:
        path = (ROOT / record["path"]).resolve(strict=True)
        if (
            not path.is_relative_to(ROOT.resolve(strict=True))
            or not path.is_file()
            or run.sha(path) != record["sha256"]
        ):
            raise ValueError("Reference HDR hash differs or path escapes root")
    return record


def reference_for_view(key, experiment=None):
    """Resolve and verify one integrand-bound image from the independent reference set."""
    record = validate_reference_for_view(key, experiment, require_image=True)
    return (ROOT / record["path"]).resolve(strict=True)


def old_seed_manifest(entry, index):
    seed = entry['old_seeds'][index]
    if seed.get('index') != index: raise ValueError('Old seed index differs')
    if _migrated():
        root = REFERENCE.resolve(strict=True)
        path = (root/entry['scene_id']/entry['view_id']/'reference/seeds/old'/
                ('seed-%02d' % (index+1))/'attempt-01/manifest.json').resolve()
        if not path.is_relative_to(root): raise ValueError('Old seed path escapes root')
    else:
        path = Path(seed['manifest']).resolve()
    if not path.is_file() or run.sha(path) != seed['manifest_sha256']:
        raise ValueError('Historical seed manifest changed')
    return path


def _relocated_emerald_entry(entry):
    """Bind a name-only scene relocation to the immutable reference baseline.

    Historical configuration and scene snapshots prove the original hashes;
    the active configuration may differ only by the two scene-path substitutions.
    The returned entry is a detached view of the unchanged historical baseline.
    """
    if (entry.get('scene_id'),entry.get('view_id'),entry.get('adapted')) != ('emerald-square','view-a',False):
        raise ValueError('Unexpected Emerald reference entry')
    config=ROOT/'experiments/configs/falcor-pt-spatial-comparison/emerald-square-reference.json'
    snapshots=REFERENCE/'provenance/relocations'
    original_config=snapshots/'emerald-square-reference-before-rename.json'
    original_scene=snapshots/'emerald-square-converted-scout.pyscene'
    active_scene=ROOT/EMERALD_NEW_SCENE
    try:
        if Path(entry['config_path']).resolve()!=config.resolve():
            raise ValueError('Unexpected Emerald configuration path')
        assets=entry['asset_sha256']
        if not isinstance(assets,dict) or EMERALD_NEW_SCENE in assets:
            raise ValueError('Unexpected Emerald historical asset inventory')
        scene_hash=assets[EMERALD_OLD_SCENE]
        original=original_config.read_bytes()
        if hashlib.sha256(original).hexdigest()!=entry['config_sha256']:
            raise ValueError('Emerald historical config hash differs')
        if run.sha(original_scene)!=scene_hash or run.sha(active_scene)!=scene_hash:
            raise ValueError('Emerald scene contents differ from frozen reference')
        old,new=EMERALD_OLD_SCENE.encode('utf8'),EMERALD_NEW_SCENE.encode('utf8')
        if original.count(old)!=2:
            raise ValueError('Unexpected Emerald historical config paths')
        current=config.read_bytes()
        if current!=original.replace(old,new):
            raise ValueError('Emerald active config differs beyond scene rename')
    except (OSError,KeyError,TypeError) as exc:
        raise ValueError('Emerald relocation files or metadata are missing') from exc
    updated_assets=dict(assets)
    del updated_assets[EMERALD_OLD_SCENE]
    updated_assets[EMERALD_NEW_SCENE]=scene_hash
    return {**entry,'config_path':str(config.resolve()),
            'config_sha256':hashlib.sha256(current).hexdigest(),'asset_sha256':updated_assets}


def rebase_frozen_config(entry, historical_root, current_root):
    """Resolve an unchanged frozen configuration relative to its recorded root."""
    from . import reference_extension_provenance as provenance
    relative=provenance.workspace_relative(entry['config_path'],historical_root)
    root=Path(current_root).resolve(strict=True)
    path=(root/relative).resolve()
    if not path.is_relative_to(root):raise ValueError('Frozen config escapes workspace')
    return {**entry,'config_path':str(path)}


def historical_frozen_views():
    """Read and verify the immutable historical baseline for provenance only."""
    manifest=json.loads(historical_extension_manifest_path().read_text(encoding='utf-8-sig'))
    baseline=historical_baseline_path()
    if manifest.get('status')!='completed' or run.sha(baseline)!=manifest.get('baseline_sha256') or run.sha(old_manifest_path())!=manifest.get('old_manifest_sha256'):
        raise ValueError('Historical baseline hash mismatch')
    record=json.loads(baseline.read_text(encoding='utf-8-sig'))
    if record.get('schema_version')==2:
        from . import reference_extension_provenance as provenance
        record=provenance.expand_portable_baseline(record,ROOT)
    elif record.get('schema_version',1)!=1:
        raise ValueError('Unsupported historical baseline schema')
    entries=record.get('views',[])
    views={(v['scene_id'],v['view_id']):v for v in entries}
    if len(entries)!=len(KEYS) or set(views)!=KEYS:raise ValueError('Need unique historical views')
    for key,item in views.items():
        if type(item.get('adapted')) is not bool or item['adapted']!=(key==('bistro','view-a')):
            raise ValueError('Unexpected historical adaptation')
    return views


def historical_reference_for_view(key):
    """Verify a retained reference against its immutable historical hash."""
    if key not in KEYS:raise ValueError('Unknown reference view')
    item=_historical_reference(key)
    if _migrated():
        catalog=json.loads((REFERENCE/'manifest.json').read_text(encoding='utf-8-sig'))
        matches=[v for v in catalog.get('views',[]) if (v.get('scene_id'),v.get('view_id'))==key]
        if catalog.get('schema_version')!=1 or len(matches)!=1:raise ValueError('Historical reference catalog mismatch')
        ref=matches[0]['reference']
        if ref.get('sha256')!=item['reference_sha256']:raise ValueError('Historical reference hashes differ')
        root=REFERENCE.resolve(strict=True);path=(root/ref['path']).resolve()
    else:
        root=EXTENSION.resolve(strict=True);path=(root/item['reference']).resolve()
    if not path.is_relative_to(root) or not path.is_file() or run.sha(path)!=item['reference_sha256']:
        raise ValueError('Historical reference missing or hash differs')
    return path


def scene_manifest_path():
    folder = ROOT / "experiments/configs/falcor-pt-spatial-comparison"
    reusable = folder / "scene-inputs-v2.json"
    return reusable if reusable.is_file() else folder / "scene-inputs.json"


def reference_catalog_path(experiment=None):
    from . import spatial_experiment_config
    if experiment is None:
        experiment=spatial_experiment_config.load_config()
    path=(ROOT/experiment['reference_catalog']).resolve()
    root=ROOT.resolve(strict=True)
    if not path.is_relative_to(root):raise ValueError('Reference catalog escapes workspace')
    return path


def baseline_path():
    """Current scene-input identity, not a historical rendering baseline."""
    return scene_manifest_path()


def extension_manifest_path():
    """Current standalone reference-set identity."""
    return reference_catalog_path()


def frozen_views():
    """Load explicitly inventoried current scene inputs without reading runs/."""
    from .project_paths import resolve_workspace_path

    record = json.loads(scene_manifest_path().read_text(encoding="utf-8-sig"))
    if record.get("schema_version") == 2:
        from .scene_inputs import load_locked_views

        return load_locked_views(scene_manifest_path(), ROOT, KEYS)
    if (
        record.get("schema_version") != 1
        or record.get("kind") != "falcor_scene_inputs"
        or record.get("path_base") != "workspace"
    ):
        raise ValueError("Unsupported scene input manifest")
    entries = record.get("views")
    if not isinstance(entries, list):
        raise ValueError("Invalid scene input manifest")
    views = {}
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("Invalid scene input")
        key = (item.get("scene_id"), item.get("view_id"))
        if (
            key not in KEYS
            or key in views
            or type(item.get("adapted")) is not bool
            or item["adapted"] != (key == ("bistro", "view-a"))
        ):
            raise ValueError("Invalid or duplicate scene view")
        path = resolve_workspace_path(item["config_path"], ROOT, strict=True)
        if not path.is_file() or run.sha(path) != item.get("config_sha256"):
            raise ValueError("Scene config hash mismatch")
        for name in ("asset_sha256", "source_sha256"):
            if not isinstance(item.get(name), dict):
                raise ValueError("Invalid scene inventory")
        for name in ("graph_sha256", "runtime_receipt_sha256"):
            if not isinstance(item.get(name), str) or len(item[name]) != 64:
                raise ValueError("Invalid input hash")
        views[key] = {**item, "config_path": str(path)}
    if set(views) != KEYS:
        raise ValueError("Need six unique scene views")
    return views


def load_config(config_path):
    """Load a locked reusable view, or a retained migration-pinned schema-1 config."""
    from .scene_inputs import load_view

    path = Path(config_path).resolve(strict=True)
    active = frozen_views()
    matches = [
        v
        for v in active.values()
        if Path(v["config_path"]).resolve(strict=True) == path
    ]
    if not matches:
        legacy = (
            ROOT / "experiments/configs/falcor-pt-spatial-comparison/scene-inputs.json"
        )
        if legacy.is_file():
            record = json.loads(legacy.read_text(encoding="utf-8-sig"))
            matches = [
                v
                for v in record.get("views", [])
                if (ROOT / v["config_path"]).resolve() == path
            ]
    if len(matches) != 1 or run.sha(path) != matches[0]["config_sha256"]:
        raise ValueError("Config is not a locked reference configuration")
    config, inputs = load_view(path, ROOT)
    if matches[0].get("input_sha256", inputs) != inputs:
        raise ValueError("Scene profile or inventory changed")
    if (config.get("scene_id"), config.get("view_id")) != (
        matches[0]["scene_id"],
        matches[0]["view_id"],
    ):
        raise ValueError("Config identity mismatch")
    current = active.get((config["scene_id"], config["view_id"]))
    if current is not None and Path(current["config_path"]).resolve() != path:
        # Retained filenames are validated aliases; execution uses the active
        # deduplicated profile and independently recorded camera.
        return load_view(current["config_path"], ROOT)[0]
    return config


def render_script(scene, camera, output, frames, method, *, adapted, options=None):
    from .spatial_render_script import build_script

    options = smoke.graph_options(method) if options is None else options
    return build_script(scene, camera, output, frames, options, adapted=adapted,
                        record_scene_state=True)


def validate_reference_state(expected,actual):
    if actual != expected:raise ValueError('Full scene state differs from frozen reference')


def validate_current_scene_state(config,state,audit=None):
    """Validate the current render without consulting historical runs."""
    if not isinstance(state,dict) or not isinstance(state.get('lights'),list):
        raise ValueError('Invalid scene state')
    for name in ('environment_present','useAnalyticLights','useEnvLight','useEmissiveLights'):
        if type(state.get(name)) is not bool:raise ValueError('Invalid scene lighting state')
    if not isinstance(state.get('stats'),dict):raise ValueError('Invalid scene statistics')
    for light in state['lights']:
        if not isinstance(light,dict) or not isinstance(light.get('name'),str) or type(light.get('active')) is not bool:
            raise ValueError('Invalid light record')
        intensity=light.get('intensity')
        if not isinstance(intensity,list) or len(intensity)!=3 or not all(type(x) in (int,float) and math.isfinite(x) for x in intensity):
            raise ValueError('Invalid light intensity')
    if 'expected_material_counts' in config:
        if not isinstance(audit,dict):raise ValueError('Adapted scene audit missing')
        validate_adapted_state(config,audit,state)
    elif audit is not None:
        raise ValueError('Unexpected scene audit')


def validate_adapted_state(config,audit,state):
    if len(state['lights'])!=config['expected_light_count'] or any(not light['active'] for light in state['lights']):raise ValueError('Active light count differs')
    if state['environment_present']!=config['expected_environment_present'] or not all(state[k] for k in ('useAnalyticLights','useEnvLight','useEmissiveLights')):raise ValueError('Light settings differ')
    if [m['material_count'] for m in audit['models']]!=config['expected_material_counts'] or [len(m['loaded_texture_slots']) for m in audit['models']]!=config['expected_texture_slots']:
        raise ValueError('Adapted material or texture audit differs')


def portable_adapted_audit(audit,root):
    from . import reference_extension_provenance as provenance
    result=copy.deepcopy(audit)
    if not isinstance(result,dict) or 'path_base' in result:raise ValueError('Invalid unmarked scene audit')
    try:
        for model in result['models']:
            for slot in model['loaded_texture_slots']:
                slot['path']=provenance.workspace_relative(slot['path'],root)
    except (KeyError,TypeError) as exc:raise ValueError('Invalid scene audit') from exc
    result['path_base']='workspace'
    return result


def validate_adapted_audit(expected, actual, *, old_root=None, current_root=None):
    """Compare audits after normalizing only workspace-local texture paths."""
    from . import reference_extension_provenance as provenance
    if old_root is None:
        record=json.loads(historical_baseline_path().read_text(encoding='utf-8-sig'))
        old_root=ROOT if record.get('schema_version')==2 and record.get('path_base')=='workspace' else provenance.historical_workspace(record)
    if current_root is None:current_root=ROOT
    def canonical(value, root):
        result=copy.deepcopy(value)
        try:
            if not isinstance(result,dict) or not isinstance(result['models'],list):raise ValueError('Invalid scene audit')
            if 'path_base' in result:
                if result.pop('path_base')!='workspace':raise ValueError('Invalid scene audit path base')
            for model in result['models']:
                if not isinstance(model['loaded_texture_slots'],list):raise ValueError('Invalid texture audit')
                for slot in model['loaded_texture_slots']:
                    slot['path']=provenance.workspace_relative(slot['path'],root)
        except (KeyError,TypeError) as exc:raise ValueError('Invalid scene audit') from exc
        return result
    if canonical(expected,old_root)!=canonical(actual,current_root):
        raise ValueError('Adapted scene audit differs from frozen reference')


def _validate_runtime(runtime,method,adapted):
    runtime=Path(runtime).resolve(strict=True)
    if not adapted:return smoke.validate_runtime(runtime,method)
    base=(gltf_runtime.DEST/'runtime').resolve(strict=True)
    if method=='baseline':
        if runtime!=base:raise ValueError('Bistro baseline requires frozen glTF runtime')
        gltf_runtime.quarantine_transients()
        receipt=gltf_runtime.verify()
        smoke.validate_runtime_inventory(runtime,receipt['runtime_files_sha256'])
        return {'kind':'verified_gltf_v3_runtime','source_receipt_sha256':run.sha(gltf_runtime.DEST/'receipt.json')}
    if method!='cgns' or runtime==base:raise ValueError('Bistro CGNS requires private glTF overlay runtime')
    verified=cgns_runtime.verify_prepared(runtime)
    if verified['source_kind']!='gltf-v3':raise ValueError('Bistro CGNS runtime must derive from frozen glTF runtime')
    return verified


def _reference_observations(key):
    if key not in KEYS:raise ValueError('Unknown reference view')
    block=_historical_reference(key)['blocks'][0]
    if _migrated():
        root=REFERENCE.resolve(strict=True)
        attempt=(root/key[0]/key[1]/'reference/seeds/extension/attempt-01').resolve(strict=True)
    else:
        root=EXTENSION.resolve(strict=True)
        attempt=(root/block['attempt']).resolve(strict=True)
    if not attempt.is_relative_to(root):raise ValueError('Reference attempt escapes directory')
    state=attempt/'scene-state.json'
    if run.sha(state)!=block['scene_state_sha256']:raise ValueError('Reference scene state hash differs')
    audit=attempt/'scene-audit.json'
    if block['scene_audit_sha256'] is not None and run.sha(audit)!=block['scene_audit_sha256']:raise ValueError('Reference audit hash differs')
    return json.loads(state.read_text(encoding='utf8')), (json.loads(audit.read_text(encoding='utf8')) if block['scene_audit_sha256'] is not None else None)


def launch(config_path,output,runtime,*,method='baseline',width=320,height=180,frames=4,timeout=1200):
    from PIL import Image
    from .reference_extension_gallery import display, RECIPES
    from . import reference_extension_batch, reference_extension_provenance
    smoke.validate_budget(width,height,frames)
    options=smoke.graph_options(method)
    config_path=Path(config_path).resolve(strict=True)
    config=load_config(config_path)
    key=(config['scene_id'],config['view_id'])
    entry=frozen_views()[key]
    adapted=entry['adapted']
    display_method, display_ev = RECIPES[key]
    if not adapted:reference_runner.validate_scene_qualification(config)
    scene=Path(config['scene_source'])
    scene=(scene if scene.is_absolute() else ROOT/scene).resolve(strict=True)
    if not scene.is_relative_to(ROOT):raise ValueError('Scene escapes workspace')
    runtime=Path(runtime).resolve(strict=True);output=Path(output).resolve()
    executable=(runtime/'Mogwai.exe').resolve(strict=True)
    shader=(runtime/'shaders/ReSTIRPathTracing/SpatialResampling.cs.slang').resolve(strict=True)
    command=[str(executable),'--device-type','d3d12','--width',str(width),'--height',str(height),'--script',str(output/'render.py'),'--headless']
    with exclusive_operation(ROOT/'build/falcor/.operation.lock'):
        check_renderer_idle()
        if __import__('os').environ.get('FALCOR_DEVMODE')=='1':raise RuntimeError('FALCOR_DEVMODE overrides isolated shaders')
        build=__import__('scripts.falcor.build',fromlist=['verify_build']).verify_build()
        reference_extension_batch.recheck_view(entry,config)
        if adapted and scene.relative_to(ROOT).as_posix() not in entry['source_sha256']:
            raise ValueError('Bistro scene missing from source inventory')
        runtime_receipt=_validate_runtime(runtime,method,adapted)
        shader_hash=run.sha(shader)
        gpu=subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version','--format=csv,noheader'],text=True).strip()
        meta={'kind':'cgns_pt_six_view_smoke','requested_method':method,'scene_config':config,'scene_config_sha256':run.sha(config_path),'reference_baseline_sha256':run.sha(baseline_path()),'reference_view':entry,'resolution':[width,height],'frames':frames,'seed_policy':'fixedSeed=frame-1; fresh process','requested_graph_options':options,'display_transform':{'method':display_method,'ev':display_ev,'encoding':'sRGB'},'adapted':adapted,'retrace_schedule':'Compact default in pinned Falcor; not exposed in serialized options','runtime':str(runtime),'runtime_verification':runtime_receipt,'runtime_spatial_shader_sha256':shader_hash,'build_commit':build['commit'],'gpu_driver':gpu}
        def prepare(out):
            (out/'render.py').write_text(render_script(scene,config['camera'],out,frames,method,adapted=adapted),encoding='utf8')
        def verify(out):
            paths=list(out.glob('capture.PathTracer.color.*.exr'))
            if len(paths)!=1:raise ValueError('Expected exactly one captured EXR')
            run.capture_frames(paths,[frames]);rgb=run.inspect_hdr(paths[0],width,height)
            camera=json.loads((out/'resolved-camera.json').read_text(encoding='utf8'))
            reference_runner.validate_camera_records(config['camera'],camera,frames)
            if 'near_plane' in config['camera'] and any(not math.isclose(float(camera[k]['nearPlane']),float(config['camera']['near_plane']),rel_tol=1e-6,abs_tol=1e-6) for k in ('initial','first_frame','last_frame')):raise ValueError('Near plane differs')
            resolved=(out/'resolved.py').read_text(encoding='utf8')
            smoke.validate_resolved_graph(resolved,options)
            smoke.validate_resolved_graph(resolved,{'samplePattern':'Center','sampleCount':1,'useAlphaTest':True,'useDOF':False},'VBufferRT')
            state=json.loads((out/'scene-state.json').read_text(encoding='utf8'))
            audit=json.loads((out/'scene-audit.json').read_text(encoding='utf8')) if adapted else None
            validate_current_scene_state(config,state,audit)
            preview=out/'preview.png';Image.fromarray(display(rgb,display_method,display_ev)).save(preview)
            if run.sha(shader)!=shader_hash or _validate_runtime(runtime,method,adapted)!=runtime_receipt:raise ValueError('Runtime changed during render')
            reference_extension_batch.recheck_view(entry,config)
            return [{'hdr':paths[0].name,'sha256':run.sha(paths[0]),'preview':preview.name,'preview_sha256':run.sha(preview),'resolved_graph_sha256':run.sha(out/'resolved.py'),'camera_sha256':run.sha(out/'resolved-camera.json'),'scene_state_sha256':run.sha(out/'scene-state.json'),'scene_audit_sha256':run.sha(out/'scene-audit.json') if adapted else None}]
        try:
            with adapted_reference_runner.isolated_python_environment():
                return run.execute(command,output,timeout,prepare=prepare,verify=verify,metadata=meta)
        finally:
            if adapted and method=='baseline':gltf_runtime.quarantine_transients()


def main():
    p=argparse.ArgumentParser(description='Run a bounded ReSTIR PT smoke test on a frozen reference view')
    p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--runtime',type=Path,required=True);p.add_argument('--method',choices=('baseline','cgns'),required=True)
    p.add_argument('--width',type=int,default=320);p.add_argument('--height',type=int,default=180);p.add_argument('--frames',type=int,default=4);p.add_argument('--timeout',type=int,default=1200)
    a=p.parse_args();print(launch(a.config,a.output,a.runtime,method=a.method,width=a.width,height=a.height,frames=a.frames,timeout=a.timeout))

if __name__=='__main__':main()
