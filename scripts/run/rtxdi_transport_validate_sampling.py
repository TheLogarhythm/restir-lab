"""Cornell reference continuation/convergence and native CGNS-off controls."""
import argparse
import copy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts/run")]
import numpy as np
from rtxdi_transport_validate import capture
from experiment.artifacts import save_json
from experiment.comparison_config import load_spec,resolve_configs,DI_SPEC
from experiment.scenes import load_scene,validate_assets
from experiment.transport import method_config
from experiment.path_reference import make_config,EXE as REFERENCE
from experiment.comparison import EXECUTABLES
TRANSPORT = EXECUTABLES["GI"]
from experiment.images import read_pfm
from experiment.reference import rmae
from rtxdi_common import sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase",choices=("reference","standard","native","compare"))
    parser.add_argument("root",type=Path)
    args=parser.parse_args(); root=args.root.resolve()
    if not root.is_relative_to(ROOT/"runs/validation"): raise ValueError("Validation must be under runs/validation")
    spec=load_spec(DI_SPEC); spec.update(resolution=[64,64],acquisition={"protocol":"static","warmup_frames":2,"capture_frames":[3]})
    base=next(j["config"] for j in resolve_configs(spec) if j["view"]=="cornell-box" and j["method"]=="di-original")
    assets=validate_assets(load_scene(base["scene_id"]))
    if args.phase=="reference":
        folder=root/"reference"; folder.mkdir(parents=True,exist_ok=False)
        images={}
        for name,component,spp,parent in (("direct128","direct",128,None),("full64","full",64,None),
                                         ("full128","full",128,None),("full128-resume","full",128,"full64"),
                                         ("full512","full",512,None)):
            config=make_config(base,base["frames"][-1],component,spp,
                               completed_spp=64 if parent else 0,previous=images[parent] if parent else None)
            images[name]=capture(config,folder/name,REFERENCE,assets)
        rgb={k:read_pfm(v) for k,v in images.items()}
        checks={"continuous_resume_bit_equal":bool(np.array_equal(rgb["full128"],rgb["full128-resume"])),
                "resume_max_difference":float(np.max(np.abs(rgb["full128"]-rgb["full128-resume"]))),
                "rmae64_to_512":rmae(rgb["full64"],rgb["full512"]),"rmae128_to_512":rmae(rgb["full128"],rgb["full512"]),
                "mean_rgb":{k:float(v.mean()) for k,v in rgb.items()},
                "images":{k:{"path":v.relative_to(root).as_posix(),"sha256":sha(v)} for k,v in images.items()}}
        checks["passed"]=(checks["continuous_resume_bit_equal"] and checks["rmae128_to_512"]<checks["rmae64_to_512"]
                          and checks["mean_rgb"]["full512"]>checks["mean_rgb"]["direct128"]*1.05)
        save_json(folder/"checks.json",checks)
        if not checks["passed"]: raise ValueError("Cornell reference resume/separation/convergence check failed")
    elif args.phase in ("standard","native"):
        folder=root/args.phase; folder.mkdir(parents=True,exist_ok=False)
        executable=TRANSPORT if args.phase=="standard" else TRANSPORT.with_name("FullSampleTransportNative.exe")
        for algorithm in ("GI","PT"):
            capture(method_config(base,algorithm,False),folder/algorithm,executable,assets)
    else:
        checks={}
        for algorithm in ("GI","PT"):
            a=root/"standard"/algorithm/"frame-0003.pfm.gz"; b=root/"native"/algorithm/"frame-0003.pfm.gz"
            left,right=read_pfm(a),read_pfm(b)
            checks[algorithm]={"bit_equal":bool(np.array_equal(left,right)),"max_abs_difference":float(np.max(np.abs(left-right))),
                               "standard_sha256":sha(a),"native_sha256":sha(b)}
        save_json(root/"off-equivalence.json",dict(checks,passed=all(c["bit_equal"] for c in checks.values())))
        if not all(c["bit_equal"] for c in checks.values()): raise ValueError("CGNS-off differs from native spatial control")


if __name__=="__main__": main()
