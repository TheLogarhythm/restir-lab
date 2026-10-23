"""Run portable regressions or explicit native/media/Windows integration groups."""
import argparse
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_GROUPS = {
    "native": ("test_pdf_similarity.PdfSimilarityMathTests", "test_reference_surface_support.ReferenceSurfaceSupportTests"),
    "media": ("test_pdf_artifacts.PdfArtifactTests.test_video_is_1080p_30fps_and_preserves_input_order",),
    "windows": ("test_pdf_supervisor.SupervisorTests",),
}


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def group_for(test):
    identifier = test.id()
    for group, prefixes in INTEGRATION_GROUPS.items():
        if any(identifier == prefix or identifier.startswith(prefix + ".") for prefix in prefixes):
            return group
    return "cpu"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("cpu", "all", *INTEGRATION_GROUPS), default="cpu")
    parser.add_argument("--list", action="store_true", help="List selected test IDs without executing them")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    loader = unittest.TestLoader()
    tests = list(flatten(loader.discover(str(ROOT / "tests"))))
    if loader.errors:
        print("Test discovery failed; no filtered run can be reported as passing.", file=sys.stderr)
        for error in loader.errors:
            print(error, file=sys.stderr)
        return 1
    selected = [test for test in tests if args.suite == "all" or group_for(test) == args.suite]
    if not selected:
        parser.error(f"No tests selected for {args.suite}")
    if args.list:
        print("\n".join(test.id() for test in selected))
        return 0
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
    if args.suite in INTEGRATION_GROUPS and result.skipped:
        print("Explicit integration group was not fully exercised; see skipped dependencies above.", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
