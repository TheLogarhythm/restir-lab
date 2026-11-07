"""One detached lifecycle for all configured comparison algorithm groups."""
import copy
import csv
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
import traceback
import uuid

from rtxdi_common import ROOT, sha
from . import batch_process, comparison, path_reference
from .artifacts import save_json
from .comparison_config import load_spec, resolve_configs, validate_approved_budget
from .comparison_plan import source_hashes, validate_gate, validate_plan
from .fixed_reference import read_json
from .reference import target
from .runner import preflight, query, relative_path
from .scenes import load_scene, validate_assets


def now():
    return datetime.now(timezone.utc).isoformat()


def renderer_idle():
    if query("powershell", "-NoProfile", "-Command",
             "Get-Process FullSample* -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id").strip():
        raise RuntimeError("A FullSample process still exists; diagnose ownership before starting")


def prepare(spec_path, root, preview_check, conformance):
    root = Path(root).resolve()
    if root.exists():
        raise FileExistsError(f"Comparison already exists: {root}")
    spec = load_spec(spec_path)
    validate_approved_budget(spec)
    jobs = resolve_configs(spec)
    assets = {s:validate_assets(load_scene(s)) for s in {j["config"]["scene_id"] for j in jobs}}
    reused, origins = comparison.reused_runs(spec,jobs,assets)
    builds = {}
    for algorithm in spec["groups"]:
        for job in (j for j in jobs if j["algorithm"] == algorithm):
            key = job["view"],job["method"],job["seed"]
            build = (reused[key]["manifest"]["build"] if key in reused else
                     preflight(dict(job["config"]["definition"],cgns=algorithm == "DI"),comparison.EXECUTABLES[algorithm]))
            if algorithm in builds and builds[algorithm] != build:
                raise ValueError("Original/CGNS pair must use the same exact build")
            builds[algorithm] = build
    reference_build, reference_inputs = comparison.validate_reference_sources(spec,jobs,assets)
    if any(r["source"]["kind"] == "render" for r in spec["references"].values()):
        base = jobs[0]["config"]
        component = next(iter(spec["references"]))
        ref = path_reference.make_config(base,base["frames"][-1],component,4096)
        actual_build = preflight(ref["definition"],path_reference.EXE)
        if reference_build is not None and reference_build != actual_build:
            raise ValueError("Rendered and reused references must match the frozen reference build")
        reference_build = actual_build
    builds["reference"] = reference_build
    code = source_hashes()
    validate_gate(conformance,builds,code)
    receipt = copy.deepcopy(read_json(preview_check))
    if receipt.get("status") != "verified" or set(receipt.get("views", {})) != set(spec["views"]):
        raise ValueError("Require visual preview verification for every fixed view")
    for view, checked in receipt["views"].items():
        config = next(j["config"] for j in jobs if j["view"] == view)
        expected = target(config,config["frames"][-1],assets[config["scene_id"]]["sha256"])
        actual = checked["target"]
        image = (Path(preview_check).resolve().parent / checked["preview"]).resolve()
        if (checked.get("visual_checked") is not True or checked.get("nonblack") is not True
                or {k:v for k,v in expected.items() if k != "resolution"} != {k:v for k,v in actual.items() if k != "resolution"}
                or actual["resolution"][0]*expected["resolution"][1] != actual["resolution"][1]*expected["resolution"][0]
                or sha(image) != checked["preview_sha256"]):
            raise ValueError(f"Unverified/mismatched preview: {view}")
        checked["preview"] = str(image)
        spec["views"][view]["camera"] = config["scene"]["camera"]
    external = {"conformance":{"path":str(Path(conformance).resolve()), "sha256":sha(Path(conformance))},
                **{f"reuse-index/{n}":entry for n,entry in enumerate(origins.values())}}
    for key, item in reused.items():
        # Freeze all durable run inputs; converted HDR/geometry are bound by their manifest too.
        for path in item["directory"].iterdir():
            if path.is_file():
                external["/".join(map(str,key)) + "/" + path.name] = {"path":str(path), "sha256":sha(path)}
    external.update(reference_inputs)
    root.mkdir(parents=True)
    shutil.copyfile(ROOT / spec["definition_file"],root / "definition.json")
    spec["definition_file"] = relative_path(root / "definition.json",ROOT)
    save_json(root / "config.json",spec)
    save_json(root / "preview-check.json",receipt)
    plan = {"schema_version":3, "batch_id":str(uuid.uuid4()), "created_utc":now(),
            "config_sha256":sha(root / "config.json"), "definition_sha256":sha(root / "definition.json"),
            "preview_check_sha256":sha(root / "preview-check.json"), "assets":assets,
            "builds":builds, "code_sha256":code, "external_inputs":external,
            "project_commit":query("git","rev-parse","HEAD"),
            "project_status":query("git","status","--porcelain","--ignore-submodules=all")}
    save_json(root / "plan.json",plan)
    save_json(root / "state.json",{"schema_version":3, "batch_id":plan["batch_id"], "status":"prepared",
                                    "phase":"methods", "updated_utc":now(), "history":[]})
    return plan


def status(root):
    """Read-only for current and historical batches; does not validate or start rendering."""
    root = Path(root).resolve()
    state = read_json(root / "state.json")
    process = read_json(root / "process.json") if (root / "process.json").exists() else {}
    state["worker_alive"] = batch_process.alive(process.get("identity"))
    if state["status"] in ("running","launching") and not state["worker_alive"]:
        state["attention"] = "Worker exited; inspect worker.log and FullSample processes before explicit resume"
    p = state.get("progress", {})
    if state.get("phase") == "references" and p.get("status") == "rendering" and "directory" in p:
        timing = Path(p["directory"]) / "timings.csv"
        if timing.is_file():
            with timing.open(newline="") as stream:
                rows = [row for row in csv.DictReader(stream) if row.get("frame") and row.get("gpu_ms")]
            if rows:
                try:
                    completed = int(rows[-1]["frame"])
                    mean = sum(float(row["gpu_ms"]) for row in rows) / len(rows) / 1000
                    state["live_progress"] = {"component":p["component"], "view":p["view"], "completed_spp":completed,
                        "checkpoint_spp":p["spp_target"], "final_spp":8192,
                        "estimated_remaining_view_gpu_seconds":max(0,8192-completed)*mean}
                except (ValueError,TypeError,KeyError):
                    pass  # A final CSV row may still be mid-write; checkpoints remain authoritative.
    return state


def start(root, *, resume_reason=None):
    root = Path(root).resolve()
    with batch_process.exclusive(root / ".launch.lock"):
        state = read_json(root / "state.json")
        if state["status"] in ("awaiting_ui","completed"):
            return state
        process = read_json(root / "process.json") if (root / "process.json").exists() else {}
        if batch_process.alive(process.get("identity")):
            return state
        if state["status"] != "prepared" and not (resume_reason and resume_reason.strip()):
            raise RuntimeError("Interrupted/failed batch requires diagnosis and an explicit resume reason")
        renderer_idle()
        validate_plan(root)
        token = str(uuid.uuid4())
        if resume_reason:
            state["history"].append({"utc":now(), "action":"resume_after_diagnosis", "reason":resume_reason,
                "previous_error":state.pop("error",None), "previous_traceback":state.pop("traceback",None)})
        state.update(status="launching",launch_token=token,updated_utc=now())
        save_json(root / "state.json",state)
        command = [sys.executable,"-B",str(ROOT / "scripts/run/rtxdi_comparison.py"),"work","--root",str(root),"--token",token]
        try:
            identity = batch_process.launch(command,ROOT,root / "worker.log")
            save_json(root / "process.json",{"identity":identity, "token":token, "command":command, "started_utc":now()})
        except BaseException as exc:
            state.update(status="failed",error=str(exc),updated_utc=now())
            save_json(root / "state.json",state)
            raise
    return state


def collect_references(root, spec, plan, *, input_guard, progress):
    """One reference per physical view/frame/component, shared by matching groups/seeds."""
    jobs = resolve_configs(spec)
    comparison.validate_reference_sources(spec,jobs,plan["assets"],plan["builds"]["reference"])
    if all(r["source"]["kind"] == "indices" for r in spec["references"].values()):
        input_guard()
        return
    refroot = root / "references"
    refroot.mkdir(exist_ok=True)
    index_path = refroot / "reference-index.json"
    initial = {"schema_version":3, "kind":"comparison_references", "build":plan["builds"]["reference"]}
    index = read_json(index_path) if index_path.exists() else dict(initial,references={})
    if any(index.get(k) != v for k,v in initial.items()):
        raise ValueError("Frozen reference index differs")
    expected_keys = set()
    for view in spec["views"]:
        base = next(j["config"] for j in jobs if j["view"] == view)
        assets = plan["assets"][base["scene_id"]]
        for frame in spec["acquisition"]["capture_frames"]:
            for component, settings in spec["references"].items():
                if settings["source"]["kind"] == "indices":
                    continue  # Fully validated against every method during analysis; no replacement rendering.
                key = f"{view}/frame-{frame}/{component}"
                expected_keys.add(key)
                input_guard()
                if key not in index["references"]:
                    index["references"][key] = path_reference.ensure_reference(refroot,base,component,
                        index["build"],assets,input_guard=input_guard,progress=lambda p:progress(dict(p,view=view,frame=frame)))
                    save_json(index_path,index)
                path_reference.load_reference(refroot,index["references"][key],base,component,index["build"],assets)
    if set(index["references"]) != expected_keys:
        raise ValueError("Unexpected reference coverage")
    input_guard()


def work(root, token):
    root = Path(root).resolve()
    # Keep the historical lock path so old archived workers cannot overlap new ones.
    with batch_process.exclusive(ROOT / "runs/.static-comparison-gpu.lock"):
        state = batch_process.claim_worker(root,token)
        def update(phase,progress=None):
            state.update(phase=phase,progress=progress or {},updated_utc=now())
            save_json(root / "state.json",state)
        try:
            plan = validate_plan(root)
            spec = load_spec(root / "config.json")
            for scene, asset in plan["assets"].items():
                if validate_assets(load_scene(scene)) != asset:
                    raise ValueError("Frozen scene assets changed")
            guard = lambda:validate_plan(root)
            comparison.validate_reference_sources(spec,resolve_configs(spec),plan["assets"],plan["builds"]["reference"])
            update("methods")
            comparison.collect(spec,root / "methods",{k:v for k,v in plan["builds"].items() if k != "reference"},
                plan["assets"],input_guard=guard,progress=lambda p:update("methods",p))
            update("references")
            collect_references(root,spec,plan,input_guard=guard,progress=lambda p:update("references",p))
            from scripts.analysis.comparison_analysis import analyze
            from scripts.analysis.comparison_report import generate
            from scripts.analysis.comparison_verify import verify
            analysis = root / "analysis/analysis.json"
            update("analysis")
            if not analysis.exists():
                analyze(root,analysis.parent)
            elif read_json(analysis).get("status") != "completed":
                raise ValueError("Incomplete analysis needs explicit diagnosis; completed rendering remains reusable")
            update("report")
            report = root / "report/report.json"
            if not report.exists():
                generate(analysis,report.parent)
            update("verification")
            verification = verify(root,analysis,report)
            save_json(root / "verification.json",verification)
            state.update(status="awaiting_ui",phase="offline_ui_check",updated_utc=now(),progress={},
                         report=str(report.parent / "comparison.html"),machine_verified_utc=now())
        except BaseException as exc:
            state.update(status="failed",error=str(exc),traceback=traceback.format_exc(),updated_utc=now())
            traceback.print_exc()
            raise
        finally:
            save_json(root / "state.json",state)
    return state


def confirm_ui(root, note):
    root = Path(root).resolve()
    with batch_process.exclusive(root / ".launch.lock"):
        state = read_json(root / "state.json")
        if state.get("schema_version") != 3 or state["status"] != "awaiting_ui" or not note.strip():
            raise ValueError("UI confirmation requires a current machine-verified report and actual inspection")
        verification = read_json(root / "verification.json")
        if sha(Path(state["report"])) != verification["html_sha256"]:
            raise ValueError("Report changed since machine verification")
        state.update(status="completed",phase="completed",completed_utc=now(),
                     ui_check={"utc":now(), "note":note, "html_sha256":verification["html_sha256"]})
        verification.update(ui_verified=True,ui_check=state["ui_check"])
        save_json(root / "verification.json",verification)
        save_json(root / "state.json",state)
        return state
