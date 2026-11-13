"""Run portable regressions or explicit source/native/media/Windows checks."""
import argparse
import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_GROUPS = {
    "native": ("tests.backends.test_pdf_similarity.PdfSimilarityMathTests", "tests.backends.test_reference_surface_support.ReferenceSurfaceSupportTests",
               "tests.backends.test_cgns_math.CgnsMathTests", "tests.backends.test_cgns_spatial.CgnsSpatialTests",
               "tests.backends.test_cgns_gi_spatial.CgnsGiSpatialTests",
               "tests.backends.test_cgns_pt_spatial.CgnsPtSpatialTests",
               "tests.backends.test_transport_adapter.TransportAdapterTests",
               "tests.backends.test_transport_weights.TransportWeightTests",
               "tests.backends.test_transport_segments.TransportSegmentTests",
               "tests.backends.test_light_geometry_index.LightGeometryIndexTests",
               "tests.backends.test_falcor_cgns_single.SingleNeighborTests.test_a_chao_shared_math_and_probability"),
    "source": ("tests.test_falcor_cgns_shader_overlay.CgnsOverlayTests",
               "tests.test_gltf_factor_shader_patch.GltfFactorShaderPatchTests",
               "tests.test_gltf_specgloss_sampling.SpecGlossSamplingTests.test_only_regular_marked_specgloss_uses_safe_weight",
               "tests.test_gltf_specgloss_sampling.SpecGlossSamplingTests.test_source_mismatch_fails_closed",
               "tests.test_gltf_transmission_tint.TransmissionTintTests",
               "tests.backends.test_falcor_cgns_single.SingleNeighborTests.test_selector_wired_to_all_consumers_and_distinct_marker",
               "tests.backends.test_falcor_cgns_single_diagnostic.SingleDiagnosticTests.test_stage_capture_fault_and_production_isolation",
               "tests.backends.test_falcor_cgns_shader_parameters.CgnsShaderParameterTests.test_different_parameters_produce_different_integrated_shader",
               "tests.backends.test_falcor_portable_runtime_receipts.PortableRuntimeReceiptTests"),
    "media": ("tests.workflows.test_pdf_artifacts.PdfArtifactTests.test_video_is_1080p_30fps_and_preserves_input_order",),
    "windows": ("tests.workflows.test_pdf_supervisor.SupervisorTests",
                "tests.workflows.test_comparison_batch.ComparisonBatchWindowsTests",
                "tests.workflows.test_batch_process.RedirectedWorkerWindowsTests"),
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


def uncollected_tests(root):
    """Find module-level test functions omitted by unittest discovery."""
    errors = []
    for path in sorted((root / 'tests').rglob('test_*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_'):
                errors.append(f'{path.relative_to(root)}:{node.lineno}: {node.name} is not a unittest method')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("cpu", "all", *INTEGRATION_GROUPS), default="cpu")
    parser.add_argument("--list", action="store_true", help="List selected test IDs without executing them")
    args = parser.parse_args()
    sys.path[:0] = [str(ROOT), str(ROOT / "src")]
    loader = unittest.TestLoader()
    tests = list(flatten(loader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))))
    collection_errors = uncollected_tests(ROOT)
    if loader.errors or collection_errors:
        print("Test discovery failed; no filtered run can be reported as passing.", file=sys.stderr)
        for error in [*loader.errors, *collection_errors]:
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
