"""Plan, run, inspect, analyze and report configured ReSTIR comparisons."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts/run")]
from experiment.comparison_config import DEFAULT_SPEC, load_spec, resolve_configs
from experiment import comparison_batch as batch
from experiment.artifacts import save_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan","prepare","start","status","resume","work","analyze","report","verify","confirm-ui"))
    parser.add_argument("--config", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--root", type=Path, help="Batch directory (or saved batch to analyze)")
    parser.add_argument("--source", type=Path, help="Saved comparison.json; defaults to ROOT/methods/comparison.json")
    parser.add_argument("--output", type=Path, help="New analysis/report directory; never overwrites an existing directory")
    parser.add_argument("--analysis", type=Path, help="Saved schema-3 analysis.json")
    parser.add_argument("--report", type=Path, help="Saved report.json to verify")
    parser.add_argument("--display", type=Path, help="Display-only JSON: exposure_ev per view and delta_range_pp")
    parser.add_argument("--source-archive", type=Path, help="Historical exact-source ZIP used only for artifact/evidence validation")
    parser.add_argument("--preview-check", type=Path)
    parser.add_argument("--conformance", type=Path)
    parser.add_argument("--reason")
    parser.add_argument("--token")
    parser.add_argument("--save-status", action="store_true", help="Explicitly save status to ROOT/monitor.json")
    args = parser.parse_args(argv)
    def require(*names):
        for name in names:
            if getattr(args,name) is None:
                parser.error(f"{args.action} requires --{name.replace('_','-')}")
    if args.source_archive and args.action not in ("analyze","verify"):
        parser.error("--source-archive is for read-only historical analysis/verification, never rendering")
    if args.action == "plan":
        spec = load_spec(args.config)
        jobs = resolve_configs(spec)
        result = {"protocol":spec["acquisition"], "groups":spec["groups"], "method_runs":len(jobs),
                  "render_runs":sum(spec["methods"][j["method"]]["source"]["kind"] == "render" for j in jobs),
                  "references":spec["references"], "jobs":[{k:v for k,v in j.items() if k != "config"} for j in jobs]}
    elif args.action == "prepare":
        require("root","preview_check","conformance")
        value = batch.prepare(args.config,args.root,args.preview_check,args.conformance)
        result = {k:value[k] for k in ("batch_id","created_utc")}
    elif args.action in ("start","resume"):
        require("root")
        if args.action == "resume": require("reason")
        result = batch.start(args.root,resume_reason=args.reason if args.action == "resume" else None)
    elif args.action == "work":
        require("root","token")
        result = batch.work(args.root,args.token)
    elif args.action == "status":
        require("root")
        result = batch.status(args.root)
        if args.save_status: save_json(args.root / "monitor.json",result)
    elif args.action == "confirm-ui":
        require("root","reason")
        result = batch.confirm_ui(args.root,args.reason)
    elif args.action == "report":
        require("analysis","output")
        from scripts.analysis.comparison_report import generate
        from experiment.fixed_reference import read_json
        path = generate(args.analysis,args.output,display=read_json(args.display) if args.display else None)
        result = {"report":str(path)}
    else:
        source = args.source or args.root
        if source is None: parser.error(f"{args.action} requires --source or --root")
        if args.action == "analyze":
            require("output")
            from scripts.analysis.comparison_analysis import analyze
            value = analyze(source,args.output,source_archive=args.source_archive)
            result = {"status":value["status"], "analysis":str(args.output / "analysis.json")}
        else:
            require("analysis")
            from scripts.analysis.comparison_verify import verify
            result = verify(source,args.analysis,args.report,source_archive=args.source_archive)
    print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))
    return result


if __name__ == "__main__":
    main()
