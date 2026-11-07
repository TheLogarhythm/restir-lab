"""Evaluate production BSDF measure and triangle MIS coordinate fixes numerically."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts/run")]
from tests.fixtures.cpp import compiler_environment, compile_cpp, shader_function


class TransportWeightTests(unittest.TestCase):
    def test_shifted_endpoint_mis_partition(self):
        from rtxdi_transport_fixes import adapt_mis
        source = adapt_mis((ROOT / "renderers/rtxdi/Samples/FullSample/Shaders/LightingPasses/RtxdiApplicationBridge/PathTracer/RAB_MISCallbacks.hlsli").read_text())
        helper = (ROOT / "scripts/run/rtxdi_experiments/TransportMath.hlsli").read_text()
        functions = [shader_function(helper, "LabTriangleRandomFromBarycentrics", "float2")]
        functions += [shader_function(source, name, "float") for name in (
            "RAB_GetMISWeightForNEE", "GetMISWeightForEmissiveSurface", "GetMISWeightForEnvironmentMap")]
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "mis_under_test.h").write_text("\n".join(functions))
            executable = compile_cpp(ROOT / "tests/transport_mis.cpp", folder, includes=(folder,))
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_delta_mixed_measure_and_actual_hit_triangle_pdf(self):
        from rtxdi_transport_fixes import adapt_surface, adapt_trace_context, adapt_reconnection, adapt_hybrid, adapt_brdf_trace, adapt_gi_final_nulls
        toolchain = compiler_environment()
        shaders = ROOT / "renderers/rtxdi/Samples/FullSample/Shaders"
        source = adapt_surface((shaders / "LightingPasses/RtxdiApplicationBridge/RAB_Surface.hlsli").read_text())
        brdf = (ROOT / "renderers/rtxdi/External/donut/include/donut/shaders/brdf.hlsli").read_text()
        helper = (ROOT / "scripts/run/rtxdi_experiments/TransportMath.hlsli").read_text()
        functions = [shader_function(brdf, name, kind) for name, kind in (
            ("Lambert", "float"), ("Schlick_Fresnel", "float3"), ("G_Smith_over_NdotV", "float"),
            ("GGX_times_NdotL", "float3"), ("SampleTriangle", "float3"),
            ("ImportanceSampleGGX_VNDF", "float3"), ("ImportanceSampleGGX_VNDF_PDF", "float"))]
        functions.append(shader_function(helper, "LabGgxVndfPdf", "float"))
        functions += [shader_function(source, name, kind) for name, kind in (
            ("RAB_SurfaceEvaluateBsdfTimesNoL", "float3"), ("RAB_SurfaceEvaluateBsdfPdf", "float"), ("LabContinuousBsdfPdf", "float"))]
        functions.append(shader_function(helper, "LabTriangleRandomFromBarycentrics", "float2"))
        terminal = (ROOT / "scripts/run/rtxdi_experiments/TerminalDelta.hlsli").read_text()
        functions.append(shader_function(terminal,"LabSecondaryDeltaEndpoint","float3"))
        final = adapt_gi_final_nulls((shaders / "LightingPasses/GI/FinalShading.hlsl").read_text())
        begin=final.index("    LabObserveFinite(reservoir.radiance);")
        end=final.index("\n    StoreShadingOutput(",begin)
        functions.append("void FinalGiFixture(RAB_Surface primarySurface, RTXDI_GIReservoir reservoir, float3& diffuse, float3& specular) { int reservoirPosition=0;\n" + final[begin:end] + "\n}")
        sdk = ROOT / "renderers/rtxdi/Libraries/Rtxdi/Include/Rtxdi/PT"
        hybrid = adapt_hybrid((sdk / "HybridShift.hlsli").read_text())
        functions.append(shader_function(hybrid, "ValidateInvertibilityCondition", "void"))
        gi = adapt_brdf_trace((shaders / "LightingPasses/BrdfRayTracing.hlsl").read_text())
        start = gi.index("specular_PDF =")
        functions.append("float GiSpecularProbability(RAB_Surface surface) { float specular_PDF; " +
                         gi[start:gi.index(";",start)+1] + " return specular_PDF; }")
        for name, initial in (("InitialSamplingPathTracerContext", True), ("HybridShiftPathTracerContext", False)):
            source = adapt_trace_context((sdk / (name + ".hlsli")).read_text(), initial=initial)
            functions.append("struct " + name + " { FixtureState ptState;\n" +
                             shader_function(source, "SetTraceResult", "void") + "\n};")
        for name, temporal in (("SpatialResampling", False), ("TemporalResampling", True)):
            source = adapt_reconnection((sdk / (name + ".hlsli")).read_text(), temporal=temporal)
            function = shader_function(source, "EvaluateReconnection", "void")
            functions.append(function.replace("EvaluateReconnection(", name + "EvaluateReconnection("))
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "transport_under_test.h").write_text("\n".join(functions))
            executable = compile_cpp(ROOT / "tests/transport_weights.cpp", folder, includes=(folder,), toolchain=toolchain)
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
