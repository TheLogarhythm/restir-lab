"""Small, explicit GPU conformance fixtures; never a formal experiment launcher.

All generated assets and run attempts are immutable under the chosen new root.
Uses the normal controlled renderer, capture validation and build provenance.
"""
import argparse
import base64
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts/run")]
import numpy as np
from experiment.artifacts import save_json
from experiment.config import make_config
from experiment.comparison_config import load_spec, resolve_configs, DI_SPEC
from experiment.scenes import asset_files, bundle_digest, validate_assets
from experiment.transport import method_config
from experiment.path_reference import make_config as reference_config, EXE as REFERENCE
from experiment.comparison import EXECUTABLES
TRANSPORT = EXECUTABLES["GI"]
from experiment.runner import run_one, preflight
from experiment.images import read_pfm
from rtxdi_common import sha


def plane_scene(folder, name, *, metal=0, roughness=1, color=(0,0,0), emission=(0,0,0), environment=None, background=False, glass=False,
                secondary_glass=False, secondary_mirror=False):
    folder.mkdir(parents=True,exist_ok=False)
    data=bytearray(); views=[]; accessors=[]
    def attribute(array, kind, component=5126):
        array=np.asarray(array,dtype="<f4" if component==5126 else "<u4")
        index=len(accessors); offset=len(data); data.extend(array.tobytes())
        views.append({"buffer":0,"byteOffset":offset,"byteLength":array.nbytes})
        a={"bufferView":index,"componentType":component,"count":len(array),"type":kind}
        if kind=="VEC3": a.update(min=array.min(axis=0).tolist(),max=array.max(axis=0).tolist())
        accessors.append(a); return index
    x=100 if background else 0
    positions=attribute([[x-10,-10,2],[x-10,10,2],[x+10,10,2],[x+10,-10,2]],"VEC3")
    normals=attribute([[0,0,-1]]*4,"VEC3")
    uv=attribute([[0,0],[0,1],[1,1],[1,0]],"VEC2")
    indices=attribute([0,1,2,0,2,3],"SCALAR",5125)
    material={"name":"receiver","pbrMetallicRoughness":{"baseColorFactor":[*color,1],"metallicFactor":metal,"roughnessFactor":roughness},"emissiveFactor":list(emission)}
    materials=[material]; nodes=[{"mesh":0}]
    primitive={"attributes":{"POSITION":positions,"NORMAL":normals,"TEXCOORD_0":uv},"indices":indices,"material":0}
    meshes=[{"primitives":[primitive]}]
    if glass or secondary_glass:
        materials.append({"name":"glass","pbrMetallicRoughness":{"baseColorFactor":[.3,.6,.9,1],"metallicFactor":0,"roughnessFactor":0},
                          "extensions":{"KHR_materials_transmission":{"transmissionFactor":1}}})
        meshes.append({"primitives":[dict(primitive,material=1)]})
        nodes.append({"mesh":1,**({"rotation":[0,1,0,0],"translation":[0,0,1]} if secondary_glass else {"translation":[0,0,-.5]})})
    if secondary_glass or secondary_mirror:
        materials.append({"name":"secondary-endpoint","pbrMetallicRoughness":{
            "baseColorFactor":[1,1,1,1] if secondary_mirror else [0,0,0,1],
            "metallicFactor":1 if secondary_mirror else 0,"roughnessFactor":0 if secondary_mirror else 1},
            "emissiveFactor":[0,0,0] if secondary_mirror else [.25,.5,1]})
        meshes.append({"primitives":[dict(primitive,material=len(materials)-1)]})
        nodes.append({"mesh":len(meshes)-1,"rotation":[0,1,0,0]})
    gltf={"asset":{"version":"2.0","generator":"restir-lab transport conformance"},"scene":0,"scenes":[{"nodes":list(range(len(nodes)))}],
          "nodes":nodes,"meshes":meshes,"materials":materials,"accessors":accessors,"bufferViews":views,
          "buffers":[{"byteLength":len(data),"uri":"data:application/octet-stream;base64,"+base64.b64encode(data).decode()}]}
    if glass or secondary_glass: gltf["extensionsUsed"]=["KHR_materials_transmission"]
    save_json(folder/"fixture.gltf",gltf)
    wrapper={"models":["fixture.gltf"],"graph":[{"name":"fixture","model":0}]}
    if environment is not None:
        import OpenEXR
        values=np.ascontiguousarray(environment,dtype=np.float32)
        # Channel views have an interleaved stride; the EXR binding needs a
        # contiguous packed RGB array to preserve isolated/nonuniform texels.
        with OpenEXR.File({}, {"RGB":values}) as exr:
            exr.write(str(folder/"environment.exr"))
        wrapper["environmentMaps"]=["environment.exr"]
    save_json(folder/"fixture.scene.json",wrapper)
    scene={"schema_version":2,"scene_id":name,"source":{"kind":"file","root":folder.relative_to(ROOT).as_posix(),"entry":"fixture.scene.json",
            "path":(folder/"fixture.scene.json").relative_to(ROOT).as_posix()},
           "camera":{"position":[0,0,0],"direction":[0,0,1],"up":[0,1,0],"vertical_fov":10},"motion":{"end_position":[0,0,0]},
           "lighting":{"environment":"file" if environment is not None else "none","environment_intensity_ev":0,"environment_rotation_degrees":0,"emissive_scale":1},
           "preview":{"exposure_ev":0}}
    if environment is not None: scene["lighting"]["environment_map"]="environment.exr"
    files=asset_files(folder/"fixture.scene.json",folder)
    scene["registry"]={"id":name,"role":"validation-only generated fixture","runtime_assets":{"sha256":bundle_digest(files),"file_count":len(files)}}
    save_json(folder/"scene-config.json",scene)
    scene["config_sha256"]=sha(folder/"scene-config.json")
    return scene


def capture(config, directory, executable, assets):
    build=preflight(config["definition"],executable)
    def guard():
        if preflight(config["definition"],executable)!=build: raise ValueError("Validation build changed")
        scene=copy.deepcopy(config["scene"]); scene["registry"]=assets["registry"]
        if validate_assets(scene)!=assets: raise ValueError("Validation assets changed")
    run_one(config,directory,build,assets,timeout=600,executable=executable,input_guard=guard)
    frame=config["frames"][-1]["frame"]
    return directory/f"frame-{frame:04d}.pfm.gz"


def fixture_checks(root,selected=None):
    unit=np.ones((16,32,3),np.float32); black=np.zeros_like(unit)
    # The receiver faces -Z: the bright texel must be in its visible hemisphere.
    sparse=black.copy(); sparse[8,16]=16
    options={"emission":{"emission":(.25,.5,1)},"mirror":{"metal":1,"roughness":0,"color":(1,1,1),"environment":unit},
             "background":{"background":True,"environment":unit},"black":{"environment":black},
             "sparse":{"color":(.5,.5,.5),"environment":sparse},
             "mixed-mirror":{"roughness":0,"color":(.5,.5,.5),"environment":unit},
             "glass":{"emission":(.25,.5,1),"glass":True},
             "secondary-glass":{"metal":1,"roughness":0,"color":(1,1,1),"secondary_glass":True},
             "secondary-mirror":{"color":(.5,.5,.5),"emission":(.25,.5,1),"secondary_mirror":True}}
    if selected:
        if not set(selected)<=set(options): raise ValueError("Unknown validation fixture")
        options={k:options[k] for k in selected}
    base=resolve_configs(load_spec(DI_SPEC))[0]["config"]
    definition=copy.deepcopy(base["definition"])
    definition.update(frames=3,resolution=[32,32],reset_frame=2,motion={"start_frame":1,"end_frame":3},
                      captures={k:[3] for k in ("static","motion","reset")},cgns=False)
    result={"kind":"small GPU transport edge fixtures","resolution":[32,32],"reference_spp":128,"method_frames":3,"fixtures":{}}
    save_json(root/"checks.json",dict(result,status="running"))
    for name,kwargs in options.items():
        scene=plane_scene(root/"assets"/name,"transport-"+name,**kwargs)
        assets=validate_assets(scene)
        config=make_config(scene,definition,"combined","static",seed=1,diagnostics=True)
        captures={}
        for component in ("direct","full"):
            current=reference_config(config,config["frames"][-1],component,128)
            captures[component]=capture(current,root/name/component,REFERENCE,assets)
        for algorithm in ("GI","PT"):
            for cgns in (False,True):
                label=algorithm.lower()+("-cgns" if cgns else "-original")
                captures[label]=capture(method_config(config,algorithm,cgns),root/name/label,TRANSPORT,assets)
        values={k:read_pfm(v) for k,v in captures.items()}
        row={"images":{k:{"path":str(v.relative_to(root)),"sha256":sha(v)} for k,v in captures.items()},
             "mean_rgb":{k:float(v.mean()) for k,v in values.items()},"finite":all(np.isfinite(v).all() for v in values.values())}
        expected={"emission":np.array([.25,.5,1]),"background":1,"black":0}.get(name)
        if expected is not None:
            row["expected_max_abs_error"]={k:float(np.max(np.abs(v-expected))) for k,v in values.items()}
            if max(row["expected_max_abs_error"].values())>0.006: raise ValueError(f"{name}: emission/background/black expectation differs: {row}")
        if name=="mirror":
            errors={k:float(np.max(np.abs(v-(0 if k=="direct" else 1)))) for k,v in values.items()}
            row["expected_max_abs_error"]=errors
            if max(errors.values())>0.006: raise ValueError(f"Mirror delta support differs: {row}")
        if name=="sparse":
            if min(row["mean_rgb"].values()) <= 1e-4:
                raise ValueError(f"Sparse environment must illuminate the receiver: {row}")
        if name=="glass":
            row["shared_glass_max_abs_error"]={k:float(np.max(np.abs(v-values["direct"]))) for k,v in values.items()}
            if max(row["shared_glass_max_abs_error"].values())>.006: raise ValueError(f"Glass composition target differs: {row}")
        if name=="secondary-glass":
            row["indirect_transmission_max_abs_error"]={k:float(np.max(np.abs(v-values["full"]))) for k,v in values.items() if k!="direct"}
            if max(row["indirect_transmission_max_abs_error"].values())>.006 or values["direct"].max()!=0:
                raise ValueError(f"Secondary colored transmittance target differs: {row}")
        if name=="secondary-mirror":
            row["indirect_mean_gain"]={k:float((v-values["direct"]).mean()) for k,v in values.items() if k!="direct"}
            if min(row["indirect_mean_gain"].values())<.05: raise ValueError(f"Missing second-scatter mirror endpoint: {row}")
        result["fixtures"][name]=row
        save_json(root/"checks.json",dict(result,status="running"))
    save_json(root/"checks.json",dict(result,status="passed"))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("--fixtures",nargs="+")
    args=parser.parse_args(); root=args.root.resolve()
    if not root.is_relative_to(ROOT/"runs/validation"): raise ValueError("Validation output must be under runs/validation")
    root.mkdir(parents=True,exist_ok=False)
    fixture_checks(root,args.fixtures)


if __name__=="__main__": main()
