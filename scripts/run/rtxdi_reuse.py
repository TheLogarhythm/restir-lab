"""Run four controlled DI reuse modes on registered RTXDI scenes."""
import argparse
from pathlib import Path

from experiment.config import DEFAULT_CONFIG, MODES, SCENARIOS, load_definition, make_config
from experiment.scenes import ACTIVE_SCENES, load_scene, validate_assets
from experiment.runner import output_directory, preflight, run_one
from rtxdi_common import RENDERER


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", required=True, nargs="+", help="Registered scene IDs, or all active scenes")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Experiment definition JSON")
    parser.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="static")
    parser.add_argument("--mode", choices=[*MODES, "all"], default="all")
    parser.add_argument("--seed", type=int, help="Override the experiment definition's seed")
    parser.add_argument("--resolution", type=int, nargs=2, metavar=("WIDTH", "HEIGHT"))
    parser.add_argument("--diagnostics", action="store_true", help="Export captured-frame M statistics")
    parser.add_argument("--pdf-similarity", action="store_true", help="Enable PDF similarity (spatial/combined only)")
    parser.add_argument("--pdf-build", action="store_true", help="Use the PDF executable, including with the extension off")
    parser.add_argument("--output-name", help="Suite directory under runs/; defaults to a UTC timestamp; never overwritten")
    parser.add_argument("--windowed", action="store_true", help="Show the viewer instead of default headless rendering")
    parser.add_argument("--timeout", type=float, default=600, help="Seconds per renderer process")
    parser.add_argument("--check", action="store_true", help="Validate settings/assets without launching or writing files")
    args = parser.parse_args()
    try:
        suite = output_directory(args.output_name)
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    if not 0 < args.timeout < float("inf"):
        parser.error("--timeout must be positive and finite")
    names = list(ACTIVE_SCENES) if args.scene == ["all"] else args.scene
    if len(set(names)) != len(names):
        parser.error("Duplicate scene IDs")
    definition = load_definition(args.config)
    if args.pdf_similarity:
        definition["pdf_similarity"] = True
    pdf_enabled = definition.get("pdf_similarity", False)
    executable = RENDERER / "build/bin/FullSamplePdf.exe" if pdf_enabled or args.pdf_build else None
    scenarios = SCENARIOS if args.scenario == "all" else [args.scenario]
    modes = MODES if args.mode == "all" else [args.mode]
    if pdf_enabled and args.mode == "all":
        modes = ["spatial", "combined"]
    # Resolve all inputs before creating output directories or launching a renderer.
    jobs = []
    for name in names:
        scene = load_scene(name)
        configs = [make_config(scene, definition, mode, scenario, args.seed, args.resolution, args.diagnostics,
                               headless=not args.windowed)
                   for scenario in scenarios for mode in modes]
        assets = validate_assets(scene)
        jobs.append((name, configs, assets))
        print(f"Validated {name}: {len(assets['file_sha256'])} resources, {len(configs)} runs", flush=True)
    if args.check:
        return
    build = preflight(definition, executable=executable)
    suite.mkdir(parents=True, exist_ok=False)
    for name, configs, assets in jobs:
        for config in configs:
            output = suite / name / config["scenario"] / config["mode"] / f"seed-{config['seed']}"
            run_one(config, output, build, assets, timeout=args.timeout, executable=executable)
    print(f"Completed: {suite}")


if __name__ == "__main__":
    main()
