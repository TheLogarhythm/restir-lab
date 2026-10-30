"""Execute the production reference sample integrand on CPU surface fixtures."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.fixtures.cpp import compiler_environment, compile_cpp, shader_function as extract_shader_function
SHADERS = ROOT / "renderers/rtxdi/Samples/FullSample/Shaders"


def shader_function(path, return_type, name):
    return extract_shader_function(path.read_text(encoding="utf-8"), name, return_type)


class ReferenceSurfaceSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        toolchain = compiler_environment()
        cls.folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.folder.cleanup)
        directory = Path(cls.folder.name)
        brdf = ROOT / "renderers/rtxdi/External/donut/include/donut/shaders/brdf.hlsli"
        functions = [shader_function(brdf, return_type, name) for return_type, name in (
            ("float", "Lambert"), ("float3", "Schlick_Fresnel"),
            ("float", "G_Smith_over_NdotV"), ("float3", "GGX_times_NdotL"))]
        functions.append(shader_function(SHADERS / "LightingPasses/ShadingHelpers.hlsli",
                                         "SplitBrdf", "EvaluateBrdf"))
        functions.append(shader_function(ROOT / "scripts/run/rtxdi_experiments/ReferenceSamples.hlsl",
                                         "void", "AddSample"))
        (directory / "reference_under_test.h").write_text("\n\n".join(functions), encoding="utf-8")
        cls.executable = compile_cpp(ROOT / "tests/reference_surface_support.cpp", directory,
                                     includes=(directory,), toolchain=toolchain)


    def check_fixture(self, fixture):
        result = subprocess.run([str(self.executable), fixture], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_tilted_shading_normal_cannot_admit_below_geometry_sample(self):
        self.check_fixture("below")

    def test_geometric_tangent_sample_is_rejected(self):
        self.check_fixture("tangent")

    def test_front_near_field_keeps_diffuse_specular_and_weighting(self):
        self.check_fixture("front")


if __name__ == "__main__":
    unittest.main()
