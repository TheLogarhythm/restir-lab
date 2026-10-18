"""Execute the production reference sample integrand on CPU surface fixtures."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHADERS = ROOT / "renderers/rtxdi/Samples/FullSample/Shaders"


def shader_function(path, return_type, name):
    source = path.read_text(encoding="utf-8")
    matches = list(re.finditer(r"\b" + return_type + r"\s+" + name + r"\s*\(", source))
    if len(matches) != 1:
        raise AssertionError(f"Expected one production {name} function in {path}")
    start = matches[0].start()
    opening = source.index("{", matches[0].end())
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return re.sub(r"\binout\s+(\w+)\s+(\w+)", r"\1& \2", source[start:end])


class ReferenceSurfaceSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cl")
        if compiler is None:
            raise unittest.SkipTest("MSVC is required for the production shader integrand check")
        environment = os.environ.copy()
        if not environment.get("INCLUDE"):
            vcvars = Path(compiler).parents[6] / "Auxiliary/Build/vcvars64.bat"
            settings = subprocess.check_output(f'cmd /d /s /c ""{vcvars}" >nul && set"', text=True)
            environment.update(line.split("=", 1) for line in settings.splitlines()
                               if "=" in line and not line.startswith("="))
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
        cls.executable = directory / "reference_math.exe"
        result = subprocess.run([compiler, "/nologo", "/EHsc", "/std:c++17",
            str(ROOT / "tests/reference_surface_support.cpp"), "/I" + str(directory),
            "/Fe:" + str(cls.executable), "/Fo:" + str(directory / "reference_math.obj")],
            cwd=directory, capture_output=True, text=True, env=environment)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

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
