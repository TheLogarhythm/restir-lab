import ast
import unittest
from pathlib import Path
from scripts.falcor import cgns_paper_capture as paper

class PaperCaptureTests(unittest.TestCase):
    def test_paper_graph_is_equal_between_methods_and_uses_fast_preset(self):
        a=paper.graph_options('baseline'); b=paper.graph_options('cgns')
        self.assertEqual(a,b)
        self.assertEqual(a['samplesPerPixel'],1)
        self.assertEqual(a['sampleGenerator'],0)
        spatial=a['reSTIRPathTracingOptions']
        self.assertEqual((spatial['spatialNeighborCount'],spatial['spatialGatherRadius']),(1,30))
        self.assertFalse(spatial['useTemporalResampling'])
        self.assertFalse(spatial['usePairedNeighbors'])
        self.assertFalse(spatial['useAreaReservoirs'])
    def test_schedule_is_post_warmup_and_bounded(self):
        self.assertEqual(paper.capture_schedule(40,8),list(range(41,49)))
        for args in [(0,0),(-1,1),(40,0),(40,129)]:
            with self.assertRaises(ValueError):paper.capture_schedule(*args)
    def test_script_captures_each_requested_linear_frame(self):
        cam={'position':[1,2,3],'direction':[0,0,-1],'up':[0,1,0],'vertical_fov':60}
        s=paper.render_script(Path('scene.pyscene'),cam,Path('out'),40,8,'baseline',adapted=False)
        ast.parse(s)
        self.assertIn('range(1, 49)',s)
        self.assertIn('tracer.fixedSeed = frame - 1',s)
        self.assertIn('if frame in [41, 42, 43, 44, 45, 46, 47, 48]',s)
        self.assertEqual(s.count('m.frameCapture.capture()'),1)
        self.assertNotIn('AccumulatePass',s)
    def test_budget_requires_1080p_unless_explicit_scout(self):
        paper.validate_budget(1920,1080,40,8)
        paper.validate_budget(64,36,1,2,scout=True)
        for w,h in [(1920,1200),(960,540),(0,0)]:
            with self.assertRaises(ValueError):paper.validate_budget(w,h,40,8)

if __name__=='__main__':unittest.main()