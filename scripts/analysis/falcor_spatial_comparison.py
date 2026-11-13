"""Legacy entry point for paired Falcor ReSTIR PT comparison analysis."""
import argparse
from pathlib import Path

from scripts.analysis import falcor_comparison as _shared
from scripts.analysis.falcor_comparison import METRIC, sha

TEMPORAL_REQUIRED = False


def valid_settings(settings):
    return _shared.valid_settings(settings, TEMPORAL_REQUIRED)


def analyze(manifest_path, output):
    return _shared.analyze(manifest_path, output, temporal_required=TEMPORAL_REQUIRED)


def analyze_temporal_contrast(manifest_path, output):
    """Compare ordinary spatial reuse with temporal reuse disabled and enabled."""
    return _shared.analyze(manifest_path, output, contrast=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(analyze(args.manifest, args.output))


if __name__ == '__main__':
    main()
