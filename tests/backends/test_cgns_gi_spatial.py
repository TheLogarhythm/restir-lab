"""Execute GI's production weights, Jacobian acceptance and cached normalization."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts/run")]
from tests.fixtures.cpp import compile_cpp, compiler_environment, shader_function


class CgnsGiSpatialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.toolchain = compiler_environment()

    def test_production_gi_merge_and_normalization(self):
        self.check_production(False)

    def test_joint_mixture_nulls_keep_M_without_selecting_or_testing_donor_jacobian(self):
        self.check_production(True)

    def check_production(self, nulls):
        from rtxdi_transport import adapt_gi_spatial
        source = ROOT / "renderers/rtxdi/Libraries/Rtxdi/Include/Rtxdi/GI"
        reservoir = (source / "Reservoir.hlsli").read_text()
        original = (source / "SpatialResampling.hlsli").read_text()
        if nulls:
            from rtxdi_transport_fixes import adapt_gi_reservoir, adapt_gi_nulls
            reservoir = adapt_gi_reservoir(reservoir)
            original = adapt_gi_nulls(original, temporal=False)
        functions = [shader_function(reservoir, name) for name in (
            "RTXDI_CombineGIReservoirs", "RTXDI_FinalizeGIResampling")]
        functions += [shader_function(original, "RTXDI_GISpatialResampling", "RTXDI_GIReservoir").replace(
            "RTXDI_GISpatialResampling(", "OriginalSpatialResampling(", 1),
            shader_function(adapt_gi_spatial(original), "RTXDI_GISpatialResampling", "RTXDI_GIReservoir")]
        if nulls:
            temporal = adapt_gi_nulls((source / "TemporalResampling.hlsli").read_text(), temporal=True)
            functions += [shader_function(temporal,"RTXDI_CalculateTemporalResamplingOffset","int2"),
                          shader_function(temporal,"RTXDI_GITemporalResampling","RTXDI_GIReservoir")]
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "gi_under_test.h").write_text(("#define LAB_NULL_TEST 1\n" if nulls else "") + "\n".join(functions))
            exe = compile_cpp(ROOT / "tests/cgns_gi_spatial.cpp", directory,
                              includes=(directory,), toolchain=self.toolchain)
            result = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
