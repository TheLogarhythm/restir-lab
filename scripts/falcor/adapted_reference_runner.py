"""Reference-run helpers for explicitly inventoried adapted Falcor scenes.

The caller supplies selected glTF/scene resources, rather than nonexistent
fallback image URIs. Existing historical runners and outputs remain unchanged.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import os

if __package__:
    from . import reference_runner, run
else:
    import reference_runner
    import run


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def inventory_resources(records, root):
    root = Path(root).resolve(strict=True)
    if not records:
        raise ValueError('Resource inventory must not be empty')
    result = {}
    for record in records:
        source = Path(record['path'])
        source = (source if source.is_absolute() else root / source).resolve(strict=True)
        if not source.is_relative_to(root) or not source.is_file():
            raise ValueError('Resource outside workspace or not a file: ' + str(source))
        expected = record.get('sha256')
        actual = file_sha256(source)
        if not isinstance(expected, str) or actual != expected:
            raise ValueError('Resource hash mismatch: ' + str(source))
        if record.get('bytes') is not None and source.stat().st_size != record['bytes']:
            raise ValueError('Resource size mismatch: ' + str(source))
        key = source.relative_to(root).as_posix()
        if key in result and result[key] != actual:
            raise ValueError('Conflicting resource records: ' + key)
        result[key] = actual
    return dict(sorted(result.items()))


def finalize_portable_audit(audit_path,root,progress_paths=()):
    """Verify original block receipts, then persist only workspace-relative texture paths."""
    audit_path=Path(audit_path);root=Path(root).resolve()
    original_hash=file_sha256(audit_path)
    audit=json.loads(audit_path.read_text(encoding='utf8'))
    if not isinstance(audit,dict) or 'path_base' in audit:raise ValueError('Invalid unmarked scene audit')
    records=[]
    for path in progress_paths:
        path=Path(path);record=json.loads(path.read_text(encoding='utf8'))
        if record.get('scene_audit_sha256')!=original_hash:raise ValueError('Block audit hash mismatch')
        records.append((path,record))
    try:
        for model in audit['models']:
            for slot in model['loaded_texture_slots']:
                slot['path']=Path(slot['path']).resolve().relative_to(root).as_posix()
    except (KeyError,TypeError,ValueError) as exc:raise ValueError('Scene audit path outside workspace or invalid') from exc
    audit['path_base']='workspace'
    run.save(audit_path,audit)
    digest=file_sha256(audit_path)
    for path,record in records:
        record['scene_audit_sha256']=digest
        run.save(path,record)
    return digest


def make_render_script(scene, camera, output, seed_index, count, *, validation=False, portable=False):
    scene = Path(scene)
    script = reference_runner.render_script(scene, camera, Path(output), seed_index, count, validation=validation, portable=portable)
    if portable:scene,output=reference_runner.portable_render_paths(scene,output)
    old_import = 'from falcor import float3'
    old_scene = 'm.loadScene(' + repr(str(scene)) + ')'
    if script.count(old_import) != 1 or script.count(old_scene) != 1:
        raise ValueError('Reference script interface changed')
    script = script.replace(old_import, 'from falcor import float3, SceneBuilderFlags')
    script = script.replace(old_scene, old_scene[:-1] + ', SceneBuilderFlags.DontOptimizeMaterials)')
    if 'near_plane' in camera:
        import math
        near=float(camera['near_plane'])
        if not math.isfinite(near) or near<=0: raise ValueError('Invalid camera near plane')
        anchor='camera.apertureRadius = 0'
        if script.count(anchor)!=1: raise ValueError('Camera setup interface changed')
        script=script.replace(anchor, anchor+'\ncamera.nearPlane = '+repr(near))
    first_frame = '    if sample == 0:\n'
    if script.count(first_frame) != 1: raise ValueError('Reference sample loop changed')
    state_path = str(Path(output) / 'scene-state.json')
    audit = """    if sample == 0:
        settings = m.scene.renderSettings
        states = [{'name': light.name, 'active': light.active,
                   'intensity': [light.intensity.x, light.intensity.y, light.intensity.z]} for light in m.scene.lights]
        state = {'lights': states, 'environment_present': m.scene.envMap is not None,
                 'useAnalyticLights': settings.useAnalyticLights,
                 'useEnvLight': settings.useEnvLight, 'useEmissiveLights': settings.useEmissiveLights,
                 'stats': m.scene.stats}
        Path(STATE_PATH).write_text(json.dumps(state, indent=2), encoding='utf-8')
""".replace('STATE_PATH', repr(state_path))
    script = script.replace(first_frame, audit + first_frame)
    return script


@contextmanager
def isolated_python_environment():
    previous=os.environ.get('PYTHONDONTWRITEBYTECODE')
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    try: yield
    finally:
        if previous is None: os.environ.pop('PYTHONDONTWRITEBYTECODE',None)
        else: os.environ['PYTHONDONTWRITEBYTECODE']=previous


def launch(
    config_path, output, seed_index, count, width, height, timeout, *, scout=False
):
    """Render a single adapted scene with a separately verified marked runtime."""
    import json
    import os
    import subprocess
    from . import run, build, prepare_gltf_composite_runtime_v3 as runtime
    from .process_utils import check_renderer_idle, exclusive_operation

    if os.environ.get("FALCOR_DEVMODE") == "1":
        raise RuntimeError("FALCOR_DEVMODE overrides isolated shaders")
    root = reference_runner.ROOT
    config_path = Path(config_path).resolve(strict=True)
    from .scene_inputs import load_view, verify_profile_inventory

    composed = (
        json.loads(config_path.read_text(encoding="utf-8-sig")).get("schema_version")
        == 2
    )
    config, config_inputs = load_view(config_path, root, expected_adapted=True)
    reference_runner.validate_scene_qualification(config, scout=scout)
    reference_runner.validate_render_budget(count, width, height, scout=scout)
    seeds = reference_runner.sample_seeds(seed_index, count)
    reference_runner.camera_target(config["camera"])
    if timeout <= 0:
        raise ValueError("Timeout must be positive")
    scene = (root / config["scene_source"]).resolve(strict=True)
    if not scene.is_relative_to(root):
        raise ValueError("Scene is outside workspace")
    if composed:
        verify_profile_inventory(config, root, adapted=True)
    graph = Path(__file__).with_name("reference_graph.py")
    output = Path(output).resolve()
    with exclusive_operation(root / "build/falcor/.operation.lock"):
        check_renderer_idle()
        built = build.verify_build()
        runtime.quarantine_transients()
        receipt = runtime.verify()
        receipt_path = runtime.DEST / "receipt.json"
        if file_sha256(receipt_path) != config["runtime_receipt_sha256"]:
            raise ValueError("Runtime receipt differs from configuration")
        if load_view(config_path, root, expected_adapted=True) != (
            config,
            config_inputs,
        ):
            raise ValueError("Scene profile changed before rendering")
        assets = inventory_resources(config["resources"], root)
        sources = inventory_resources(config["sources"], root)
        if scene.relative_to(root).as_posix() not in sources:
            raise ValueError("Scene script is missing from source inventory")
        executable = runtime.DEST / "runtime" / Path(built["executable"]).name
        script = make_render_script(
            scene, config["camera"], output, seed_index, count, portable=True
        )
        gpu = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            text=True,
        ).strip()
        metadata = {
            "kind": "reference_scout" if scout else "reference_seed",
            "scene_config": config,
            "config_sha256": file_sha256(config_path),
            "config_input_sha256": config_inputs,
            "seed_index": seed_index,
            "samples_per_pixel": count,
            "sample_seed_first": seeds.start,
            "sample_seed_last": seeds.stop - 1,
            "rng": "Falcor Uniform 128-bit; distinct per-frame sample numbers",
            "resolution": [width, height],
            "asset_sha256": assets,
            "source_sha256": sources,
            "graph_sha256": file_sha256(graph),
            "runner_sha256": file_sha256(Path(__file__)),
            "runtime_receipt_sha256": file_sha256(receipt_path),
            "runtime_kind": receipt["kind"],
            "build_commit": built["commit"],
            "gpu_driver": gpu,
        }
        command = [
            str(executable),
            "--device-type",
            "d3d12",
            "--width",
            str(width),
            "--height",
            str(height),
            "--script",
            str(output / "render.py"),
            "--headless",
        ]
        metadata.update(reference_runner.portable_command(command))

        def prepare(out):
            (out / "reference_graph.py").write_bytes(graph.read_bytes())
            (out / "render.py").write_text(script, encoding="utf-8")
            run.save(out / "config.json", config)

        def verify(out):
            records = json.loads(
                (out / "resolved-camera.json").read_text(encoding="utf-8")
            )
            reference_runner.validate_camera_records(config["camera"], records, count)
            if "near_plane" in config["camera"]:
                import math

                if any(
                    not math.isclose(
                        float(records[k]["nearPlane"]),
                        float(config["camera"]["near_plane"]),
                        rel_tol=1e-6,
                        abs_tol=1e-6,
                    )
                    for k in ("initial", "first_frame", "last_frame")
                ):
                    raise ValueError("Camera near plane does not match source")
            state_path = out / "scene-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if len(state["lights"]) != config["expected_light_count"] or any(
                not light["active"] for light in state["lights"]
            ):
                raise ValueError("Actual active light count differs from scene plan")
            if state["environment_present"] != config[
                "expected_environment_present"
            ] or not all(
                state[k]
                for k in ("useAnalyticLights", "useEnvLight", "useEmissiveLights")
            ):
                raise ValueError(
                    "Actual environment or light settings differ from scene plan"
                )
            audit_path = out / "scene-audit.json"
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            counts = [a["material_count"] for a in audit["models"]]
            slots = [len(a["loaded_texture_slots"]) for a in audit["models"]]
            if (
                counts != config["expected_material_counts"]
                or slots != config["expected_texture_slots"]
            ):
                raise ValueError(
                    "Material or texture audit count differs from scene plan"
                )
            paths = list(out.glob("capture.AccumulatePass.output.*.exr"))
            if len(paths) != 1:
                raise ValueError("Expected exactly one accumulated EXR")
            rgb = run.inspect_hdr(paths[0], width, height)
            if load_view(config_path, root, expected_adapted=True) != (
                config,
                config_inputs,
            ):
                raise ValueError("Scene profile changed during rendering")
            if (
                inventory_resources(config["resources"], root) != assets
                or inventory_resources(config["sources"], root) != sources
            ):
                raise ValueError("Inputs changed during rendering")
            finalize_portable_audit(audit_path, root)
            runtime.quarantine_transients()
            runtime.verify()
            return [
                {
                    "file": paths[0].name,
                    "sha256": file_sha256(paths[0]),
                    "min": float(rgb.min()),
                    "max": float(rgb.max()),
                },
                {"file": audit_path.name, "sha256": file_sha256(audit_path)},
                {"file": state_path.name, "sha256": file_sha256(state_path)},
            ]

        with isolated_python_environment():
            return run.execute(
                command,
                output,
                timeout,
                prepare=prepare,
                verify=verify,
                metadata=metadata,
            )


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',required=True);p.add_argument('--output',required=True)
    p.add_argument('--seed',type=int,required=True);p.add_argument('--samples',type=int,default=1024)
    p.add_argument('--width',type=int,default=1920);p.add_argument('--height',type=int,default=1080)
    p.add_argument('--timeout',type=float,default=7200);p.add_argument('--scout',action='store_true')
    a=p.parse_args();print(launch(a.config,a.output,a.seed,a.samples,a.width,a.height,a.timeout,scout=a.scout))

if __name__=='__main__':main()







