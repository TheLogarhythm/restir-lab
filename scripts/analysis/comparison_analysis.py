"""Analyze validated saved comparison HDR. Never render or create display images."""
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts/run")]
from rtxdi_common import sha
from experiment.artifacts import save_json
from experiment.comparison import load_methods, run_inventory, validate_inventory, merge_inventory
from experiment.comparison_plan import read_artifact_plan, source_hashes
from experiment.fixed_reference import read_json, load_references as load_fixed_references
from experiment import path_reference
from experiment.geometry_io import read_geometry
from experiment.images import read_pfm
from experiment.reference import rmae
from experiment.saved_runs import SharedRegions, geometry_target
from metrics.comparison_metrics import aggregate_smape, compare_errors, validate_masks
from metrics.error_metrics import smape_map
from scripts.analysis.comparison_diagnostics import file_record, capture_evidence, timing_summary, comparison_summary

METRIC = {"name":"luminance SMAPE", "formula":"100*abs(Y-Yref)/(abs(Y)+abs(Yref)+1e-4)",
          "luminance":[0.2126,0.7152,0.0722], "factor_two":False, "domain":"unclipped scene-linear HDR"}


def comparison_source(source):
    source = Path(source).resolve()
    return source / "methods/comparison.json" if source.is_dir() else source


def load_inputs(source, *, source_archive=None):
    source = comparison_source(source)
    inventory = {str(source):sha(source)}
    record = read_json(source)
    root = source.parent.parent
    if (root / "plan.json").is_file():
        for name in ("plan.json", "config.json", "definition.json", "preview-check.json"):
            path = root / name
            inventory[str(path)] = sha(path)
    if source_archive is not None:
        path = Path(source_archive).resolve();inventory[str(path)] = sha(path)
    plan = read_artifact_plan(root, source_archive=source_archive) if (root / "plan.json").is_file() else None
    if record.get("schema_version") in (2,3) and plan is None:
        raise ValueError("Comparison requires its frozen plan")
    if plan is not None and read_json(root / "config.json") != record["spec"]:
        raise ValueError("Comparison differs from frozen configuration")
    spec, loaded, builds = load_methods(source)
    for item in loaded.values(): merge_inventory(inventory,item["input_hashes"])
    if plan is not None:
        expected_builds = ({"DI":plan["method_build"]} if plan["schema_version"] == 1 else
                           {k:v for k,v in plan["builds"].items() if k != "reference"})
        if builds != expected_builds:
            raise ValueError("Comparison builds differ from frozen plan")
        for item in loaded.values():
            if item["manifest"]["scene"] != plan["assets"][item["config"]["scene_id"]]:
                raise ValueError("Method scene assets differ from frozen plan")
    references, indices = {}, {}
    for view in spec["views"]:
        for frame in spec["acquisition"]["capture_frames"]:
            for component, settings in spec["references"].items():
                relevant = [i for (v,m,s),i in loaded.items() if v == view
                            and spec["groups"][spec["methods"][m]["algorithm"]]["reference"] == component]
                base = relevant[0]
                targets = {i["key"] for i in relevant}
                if len(targets) != 1:
                    raise ValueError("Methods/seeds disagree on reference target")
                selected = settings["source"]
                index_path = ((ROOT / selected["indices"][view]).resolve() if selected["kind"] == "indices"
                              else root / "references/reference-index.json")
                indices[str(index_path)] = sha(index_path)
                index = read_json(index_path)
                merge_inventory(inventory,{str(index_path):indices[str(index_path)]})
                merge_inventory(inventory,reference_inventory(index_path,index,base,view,frame,component,settings["policy"]))
                if settings["policy"]["kind"] == "paired_precision":
                    from scripts.analysis.di_reuse import load_references
                    rows = load_references(index_path,index_path.parent,[i["captures"][frame] for i in relevant])
                    row = rows[base["captures"][frame]["key"]]
                    references[(view,frame,component)] = {"image":(index_path.parent / row["image"]).resolve(),
                        "record":row, "index":index_path, "target":base["target"], "precision":"pending recheck",
                        "paired_records":rows, "legacy_key":base["captures"][frame]["key"]}
                elif settings["policy"]["kind"] == "fixed_budget":
                    expected_build = (record.get("reference_build") if plan is None else
                                      plan.get("reference_build", plan.get("builds", {}).get("reference")))
                    if expected_build is None:
                        raise ValueError("Fixed reference requires a frozen reference build")
                    rows = load_fixed_references(index_path, [i["captures"][frame] for i in relevant],
                        expected_policy=settings["policy"], expected_build=expected_build)
                    row = rows[base["captures"][frame]["key"]]
                    image = (index_path.parent / row["image"]).resolve()
                    references[(view,frame,component)] = {"image":image, "record":row, "index":index_path,
                        "target":base["target"], "precision":"fixed budget; precision not evaluated"}
                else:
                    version = index.get("schema_version")
                    kind = "grouped_path_references" if version == 2 else "comparison_references"
                    if version not in (2,3) or index.get("kind") != kind:
                        raise ValueError("Unsupported path-reference index schema")
                    key = view + "/" + component if version == 2 else f"{view}/frame-{frame}/{component}"
                    row = index["references"][key]
                    build = plan["builds"]["reference"]
                    if index["build"] != build or row["policy"] != settings["policy"]:
                        raise ValueError("Path reference build/budget differs from frozen plan")
                    image = path_reference.load_reference(index_path.parent, row, base["config"], component,
                                                          build, base["manifest"]["scene"])
                    references[(view,frame,component)] = {"image":image, "record":row, "index":index_path,
                        "target":row["target"], "previous":(index_path.parent / row["checkpoints"][0]["image"]).resolve(),
                        "precision":"fixed path spp; precision not evaluated"}
    validate_inventory(inventory)
    return source, plan, spec, loaded, references, inventory


def reference_inventory(index_path, index, base, view, frame, component, policy):
    """Pin the reference files that the existing validators will consume."""
    root, inventory = index_path.parent, {}
    if policy["kind"] == "paired_precision":
        row = index["references"][base["captures"][frame]["key"]]
        for field in ("image", "convergence"):
            path = (root / row[field]).resolve()
            inventory[str(path)] = row[field+"_sha256"]
    elif policy["kind"] == "fixed_budget":
        directory = root / base["captures"][frame]["key"] / f"seed-{policy['seed']}"
        for samples in policy["checkpoints"]:
            for attempt in (directory / f"checkpoint-{samples}").glob("attempt-*"):
                inventory.update(run_inventory(attempt))
    else:
        key = view + "/" + component if index.get("schema_version") == 2 else f"{view}/frame-{frame}/{component}"
        for checkpoint in index["references"][key]["checkpoints"]:
            inventory.update(run_inventory((root / checkpoint["image"]).parent))
    validate_inventory(inventory)
    return inventory


def _old_di_reference(spec, view, capture):
    """Optional historical comparison only when DI explicitly reuses a schema-1 index."""
    if "DI" not in spec["groups"]:
        return None
    original = spec["methods"][spec["groups"]["DI"]["original"]]["source"]
    if original["kind"] != "comparison":
        return None
    old = read_json(ROOT / original["index"])
    if old.get("schema_version") != 1:
        return None
    policy = old["spec"].get("reference_budget")
    if not isinstance(policy, dict) or policy.get("kind") != "fixed_budget":
        return None  # Paired-precision method reuse is valid; this auxiliary is fixed-budget-only.
    index = (ROOT / old["spec"]["views"][view]["reference_index"]).resolve()
    index_hash = sha(index)
    inventory = {str(index):index_hash, **reference_inventory(index,read_json(index),{"captures":{capture["frame"]["frame"]:capture}},
        view,capture["frame"]["frame"],"direct",policy)}
    rows = load_fixed_references(index, [capture], expected_policy=old["spec"]["reference_budget"],
                                expected_build=old["reference_build"])
    validate_inventory(inventory)
    return index, (index.parent / rows[capture["key"]]["image"]).resolve(), inventory


def analyze(source, output, *, source_archive=None):
    source, plan, spec, loaded, references, inventory = load_inputs(source, source_archive=source_archive)
    def read_bound_image(path):
        path = Path(path).resolve()
        expected = inventory[str(path)]
        if sha(path) != expected: raise ValueError("Validated HDR input changed before metric calculation")
        image = read_pfm(path)
        if sha(path) != expected: raise ValueError("Validated HDR input changed during metric calculation")
        return image
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = {"schema_version":3, "status":"running", "metric":METRIC, "spec":spec,
              "source":file_record(source, output), "provenance":{"purpose":"new-code reanalysis of saved HDR",
                  "code_sha256":source_hashes()}, "views":{},
              "limitations":["Per-seed errors are averaged within each capture frame; frames are never pooled.",
                "Fixed views and parameters; no equal-time or cross-run repeatability claim.",
                "Merged-neighbor counts include zero-weight streams and duplicate coordinates; not independent effective samples.",
                "4096-to-8192 change uses correlated checkpoints, not a confidence interval.",
                "GI secondary-radiance and packed-material approximations, PT cached-suffix/quantized-light approximations, and legacy DI glass remain estimator limitations.",
                "CGNS paper confirms luminance, scale 100 and epsilon 1e-4; exact author evaluator parity remains unverified. GI uses MSE; GRIS/PT uses HDR MAPE with another stabilizer."]}
    if plan is not None:
        result["provenance"]["plan"] = file_record(source.parent.parent / "plan.json", output)
        result["builds"] = {"DI":plan["method_build"]} if plan["schema_version"] == 1 else plan["builds"]
    if source_archive is not None:
        result["provenance"]["historical_source_archive"] = file_record(Path(source_archive).resolve(), output)
    try:
        for view, settings in spec["views"].items():
            view_row = {"label":settings["label"], "camera_status":settings["camera_status"], "captures":{}}
            for frame in spec["acquisition"]["capture_frames"]:
                folder = output / view / f"frame-{frame}"
                folder.mkdir(parents=True)
                original = next(iter(spec["groups"].values()))["original"]
                geometry_source = loaded[(view,original,spec["preview_seed"])]
                capture = geometry_source["captures"][frame]
                shape = geometry_source["config"]["height"],geometry_source["config"]["width"]
                shared, geometry_record = {}, {}
                if any(r != "all" for r in spec["classification"]["regions"]):
                    provider = SharedRegions({"data":geometry_source, "static_frame":frame},
                        {frame:geometry_target(capture["target"])}, folder,
                        spec["classification"]["radius"], spec["classification"]["hard_percent"])
                    shared = provider(frame)
                    geometry = read_geometry(geometry_source["directory"] / geometry_source["records"][frame]["geometry"])
                    for (v,m,s), item in loaded.items():
                        if v == view:
                            record = item["records"][frame]
                            path = item["directory"] / record["geometry"]
                            if sha(path) != record["geometry_sha256"]:
                                raise ValueError("Modified shared geometry input")
                            candidate = read_geometry(path)
                            if any(not np.array_equal(candidate[k],geometry[k]) for k in geometry):
                                raise ValueError("Methods/seeds/groups have different primary geometry")
                    geometry_record = dict(provider.records[str(frame)])
                    geometry_record["mask"] = file_record(folder / geometry_record["mask"], output)
                masks = validate_masks({"all":np.ones(shape,bool), **{r:shared[r] for r in spec["classification"]["regions"] if r != "all"}}, shape)
                row = {"frame":frame, "seeds":spec["seeds"], "preview_seed":spec["preview_seed"],
                       "resolution":spec["resolution"], "regions":{r:int(m.sum()) for r,m in masks.items()},
                       "geometry":geometry_record, "groups":{}, "references":{}}
                images = {}
                for component in spec["references"]:
                    ref = references[(view,frame,component)]
                    image = images[component] = read_bound_image(ref["image"])
                    if image.shape != (*shape,3):
                        raise ValueError("Reference image dimensions differ")
                    value = {"image":file_record(ref["image"],output), "index":file_record(ref["index"],output),
                             "target":ref["target"], "policy":spec["references"][component]["policy"], "precision":ref["precision"]}
                    if "previous" in ref:
                        before = read_bound_image(ref["previous"])
                        error = smape_map(before,image)
                        value.update(checkpoint4096=file_record(ref["previous"],output),
                                     change_4096_to_8192={"rmae":rmae(before,image), "smape":{r:float(error[m].mean()) for r,m in masks.items()}})
                    row["references"][component] = value
                precision_rows = {c:[] for c in spec["references"]}
                for algorithm, group in spec["groups"].items():
                    methods, errors = {}, {}
                    for method in (group["original"],group["cgns"]):
                        paths = {seed:loaded[(view,method,seed)]["captures"][frame]["image"] for seed in spec["seeds"]}
                        metrics = aggregate_smape(paths,images[group["reference"]],masks,load_image=read_bound_image)
                        ref = references[(view,frame,group["reference"])]
                        if "paired_records" in ref:
                            precision_rows[group["reference"]].extend({"reference_key":ref["legacy_key"], "region":"full",
                                "rmae":rmae(read_bound_image(path),images[group["reference"]])} for path in paths.values())
                        errors[method] = metrics["error"]
                        per_seed = {}
                        for seed in spec["seeds"]:
                            item = loaded[(view,method,seed)]
                            evidence = capture_evidence(item,frame,masks,output)
                            evidence.update(smape_percent=metrics["per_seed"][seed], timing=timing_summary(item,frame,algorithm))
                            per_seed[str(seed)] = evidence
                        methods[method] = {"label":spec["methods"][method]["label"], "summary":metrics["summary"], "per_seed":per_seed}
                    comparison = compare_errors(errors[group["original"]],errors[group["cgns"]],masks)
                    maps = folder / (algorithm.lower()+"-errors.npz")
                    np.savez_compressed(maps, original=errors[group["original"]], cgns=errors[group["cgns"]], improvement=comparison["delta"])
                    row["groups"][algorithm] = {**group, "methods":methods, "maps":file_record(maps,output),
                        "comparison":comparison_summary(methods[group["original"]]["summary"],methods[group["cgns"]]["summary"])}
                for component, rows in precision_rows.items():
                    if rows:
                        from scripts.analysis.di_reuse import recheck_references
                        ref = references[(view,frame,component)]
                        recheck_references(rows,ref["paired_records"],ref["index"].parent)
                        row["references"][component]["precision"] = "passed" if ref["paired_records"][ref["legacy_key"]]["converged"] else "insufficient"
                old = _old_di_reference(spec,view,capture)
                if old is not None:
                    index, path, old_inventory = old
                    merge_inventory(inventory,old_inventory)
                    old_rgb = read_bound_image(path)
                    row["old_di_reference"] = {"image":file_record(path,output), "index":file_record(index,output), "rmae_vs_new":rmae(old_rgb,images["direct"])}
                    row["old_di_evaluation"] = {}
                    for method in (spec["groups"]["DI"]["original"], spec["groups"]["DI"]["cgns"]):
                        previous = aggregate_smape({s:loaded[(view,method,s)]["image"] for s in spec["seeds"]},old_rgb,masks,load_image=read_bound_image)["summary"]
                        current = row["groups"]["DI"]["methods"][method]["summary"]
                        row["old_di_evaluation"][method] = {"old_reference":previous, "new_reference":current, "new_minus_old_pp":{r:current[r]-previous[r] for r in masks}}
                view_row["captures"][str(frame)] = row
            result["views"][view] = view_row
        # Reject input mutation during a long analysis, including frozen indices.
        from .comparison_diagnostics import check_records
        check_records(result,output)
        validate_inventory(inventory)
        if plan is not None and read_artifact_plan(source.parent.parent,source_archive=source_archive) != plan:
            raise ValueError("Frozen plan changed during analysis")
        if source_hashes() != result["provenance"]["code_sha256"]:
            raise ValueError("Analysis code changed during processing")
        result["input_inventory"] = [{"path":str(Path(name).resolve()), "sha256":digest} for name,digest in sorted(inventory.items())]
        if read_json(source).get("schema_version") == 1:
            from experiment.legacy_comparison import validate_frozen_references
            validate_frozen_references(read_json(source))
        result["status"] = "completed"
    except BaseException:
        result["status"] = "failed"
        raise
    finally:
        save_json(output / "analysis.json", result)
    return result
