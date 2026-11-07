"""Production PT merge/inverse-normalization with controlled hybrid-shift callbacks."""
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"scripts/run")]
from tests.fixtures.cpp import shader_function,compile_cpp


class CgnsPtSpatialTests(unittest.TestCase):
    def test_cached_neighbors_rejection_jacobians_and_normalization(self):
        from rtxdi_transport import adapt_pt_spatial
        sdk=ROOT/"renderers/rtxdi/Libraries/Rtxdi/Include/Rtxdi/PT"
        reservoir=(sdk/"Reservoir.hlsli").read_text()
        original=(sdk/"SpatialResampling.hlsli").read_text()
        adapted=adapt_pt_spatial(original)
        functions=[shader_function(reservoir,n,t).replace("in float ","float ") for n,t in (
            ("RTXDI_InternalSimplePTResample","bool"),("RTXDI_CombinePTReservoirs","bool"),("RTXDI_FinalizePTResampling","void"))]
        functions += [shader_function(adapted,n,t) for n,t in (
            ("CalculateNeighborSurfacePixelPosition","uint2"),("IsValidNeighborSurface","bool"),
            ("ResampleNeighbors","bool"),("BiasCorrection","void"),("FinalizeResampling","void"),
            ("RTXDI_PTSpatialResampling","RTXDI_PTReservoir"))]
        functions.append(shader_function(original,"RTXDI_PTSpatialResampling","RTXDI_PTReservoir").replace("RTXDI_PTSpatialResampling(","OriginalSpatialResampling("))
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); (folder/"pt_under_test.h").write_text("\n".join(functions))
            executable=compile_cpp(ROOT/"tests/cgns_pt_spatial.cpp",folder,includes=(folder,))
            result=subprocess.run([str(executable)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=="__main__": unittest.main()
