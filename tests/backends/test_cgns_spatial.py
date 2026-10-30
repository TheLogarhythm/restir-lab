"""Execute the adapted DI merge and normalization loops on controlled reservoirs."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.fixtures.cpp import compile_cpp, compiler_environment, shader_function
sys.path.insert(0, str(ROOT / "scripts/run"))


class CgnsSpatialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.toolchain = compiler_environment()

    def test_selected_neighbors_and_visibility_control_normalization(self):
        import rtxdi_cgns

        source = ROOT / "renderers/rtxdi/Libraries/Rtxdi/Include/Rtxdi/DI"
        reservoir = (source / "Reservoir.hlsli").read_text()
        original = (source / "SpatialResampling.hlsli").read_text()
        functions = [shader_function(reservoir, name) for name in (
            "RTXDI_InternalSimpleResample", "RTXDI_CombineDIReservoirs", "RTXDI_FinalizeResampling")]
        functions.append(shader_function(original, "RTXDI_DISpatialResampling").replace(
            "RTXDI_DISpatialResampling(", "OriginalSpatialResampling(", 1))
        functions.append(shader_function(rtxdi_cgns.adapt_spatial(original), "RTXDI_DISpatialResampling"))
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "spatial_under_test.h").write_text("\n".join(functions))
            executable = compile_cpp(ROOT / "tests/cgns_spatial_resampling.cpp", directory,
                                     includes=(directory,), toolchain=self.toolchain)
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
