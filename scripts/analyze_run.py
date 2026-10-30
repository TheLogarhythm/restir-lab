"""Inspect one saved RTXDI/Falcor run, optionally against an explicit HDR reference."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analysis.saved_runs import write_analysis


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="New directory outside the input run"
    )
    parser.add_argument(
        "--reference-image",
        type=Path,
        help="Explicit linear HDR; target/convergence are not certified",
    )
    args = parser.parse_args()
    print(write_analysis(args.run, args.output, args.reference_image))


if __name__ == "__main__":
    main()
