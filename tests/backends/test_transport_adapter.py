"""Pinned source transformations must fail closed and retain native math."""
import importlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts/run")]
SHADERS = ROOT / "renderers/rtxdi/Samples/FullSample/Shaders"


class TransportAdapterTests(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module("rtxdi_transport")

    def test_gi_final_shading_consumes_final_reservoir(self):
        original = (SHADERS / "LightingPasses/GI/FinalShading.hlsl").read_text()
        actual = self.api.adapt_gi_final(original)
        self.assertIn("g_Const.restirGI.bufferIndices.finalShadingInputBufferIndex", actual)
        self.assertEqual(original.replace("secondarySurfaceReSTIRDIOutputBufferIndex",
                                          "finalShadingInputBufferIndex"), actual)
        with self.assertRaises(RuntimeError):
            self.api.adapt_gi_final(actual)

    def test_gi_delta_output_and_clamp_common_to_both_methods(self):
        original = (SHADERS / "LightingPasses/ShadeSecondarySurfaces.hlsl").read_text()
        actual = self.api.adapt_gi_secondary(original)
        self.assertIn("if (!isDeltaSurface || isSpecularRay)", actual)
        self.assertNotIn("radiance *= c_MaxIndirectRadiance / indirectLuminance;", actual)
        self.assertIn("radiance, secondaryGBufferData.pdf", actual)
        with self.assertRaises(RuntimeError):
            self.api.adapt_gi_secondary(actual)

    def test_pt_only_adds_diagnostics_preserving_both_native_shift_rounds(self):
        path = ROOT / "renderers/rtxdi/Libraries/Rtxdi/Include/Rtxdi/PT/SpatialResampling.hlsli"
        original = path.read_text()
        actual = self.api.adapt_pt_spatial(original)
        self.assertEqual(actual.replace(
            "    LabRecordSpatialNeighbors(srrParams.pixelPosition, countbits(cachedResult));\n", ""), original)
        self.assertEqual(actual.count("RTXDI_ComputeHybridShift("), original.count("RTXDI_ComputeHybridShift("))

    def test_all_indirect_cli_controls_exist_in_pinned_parser(self):
        import re
        from experiment.comparison_config import load_spec, resolve_configs, DI_SPEC
        from experiment.transport import method_config
        source = ROOT / "renderers/rtxdi/Samples/FullSample/Source/App/CommandLineArgs.cpp"
        arguments = set(re.findall(r'\("([A-Za-z][A-Za-z0-9_.]*)",', source.read_text()))
        base = resolve_configs(load_spec(DI_SPEC))[0]["config"]
        for algorithm in ("GI", "PT"):
            config = method_config(base, algorithm, True)
            for name in config["arguments"]:
                if name.startswith(("restirGI.", "restirPT.", "pt.")):
                    with self.subTest(algorithm=algorithm, name=name):
                        self.assertIn(name, arguments)


if __name__ == "__main__":
    unittest.main()
