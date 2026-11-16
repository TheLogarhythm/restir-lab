"""Run the bounded, temporal-on PDF PT verification captures at the frozen fixed views."""
import argparse
from pathlib import Path

from . import pdf_pt_runtime, spatial_capture, spatial_experiment_config

ROOT = spatial_capture.ROOT
VIEWS = ROOT / "experiments/views/falcor-pt-spatial-comparison"
SEEDS = (0, 64, 128, 192)


def cases():
    for profile in ("observe", "one", "native", "zero", "center", "baseline", "normal"):
        yield "classroom", profile, 0
    yield "bistro-interior", "normal", 0
    for seed in SEEDS[1:]:
        for profile in ("baseline", "normal"):
            yield "classroom", profile, seed


def capture(output, scene, profile, seed):
    kind = "gltf-v3" if scene == "bistro-interior" else "reference"
    params = spatial_experiment_config.load_config()["methods"]["pdf-similarity"]["shader"]
    if profile == "baseline":
        runtime = pdf_pt_runtime.SOURCES[kind].DEST / "runtime"
        method, pdf_profile = "baseline", "normal"
    else:
        runtime = pdf_pt_runtime.variant_destination(kind, params, profile) / "runtime"
        if not runtime.exists():
            runtime = pdf_pt_runtime.ensure_variant(kind, params, profile)
        # launch() verifies any existing variant under its lock, before and after rendering.
        method, pdf_profile = "pdf-similarity", profile
    name = f"{scene}-{profile}-{seed}"
    return spatial_capture.launch(
        VIEWS / f"{scene}.json", output / "cases" / name, runtime, method=method,
        temporal_reuse=True, scout=True, width=96, height=64, warmup=0,
        count=3 if kind == "gltf-v3" else 12, seed_offset=seed,
        pdf_profile=pdf_profile, timeout=300,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--case", action="append", help="Select one case by scene-profile-seed")
    args = parser.parse_args()
    selected = {f"{s}-{p}-{n}": (s, p, n) for s, p, n in cases()}
    for name in args.case or selected:
        if name not in selected:
            parser.error(f"Unknown scout {name}")
    for name in args.case or selected:
        print("Starting", name, flush=True)
        print(capture(args.output.resolve(), *selected[name]), flush=True)


if __name__ == "__main__":
    main()
