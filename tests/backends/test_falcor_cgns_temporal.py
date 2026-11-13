import ast
import unittest
from pathlib import Path
from scripts.falcor import cgns_temporal_capture as capture
from scripts.analysis import falcor_temporal_comparison as analysis

class TemporalCaptureTests(unittest.TestCase):
    def test_temporal_graph_keeps_spatial_pair_and_history(self):
        a=capture.graph_options('baseline'); b=capture.graph_options('cgns')
        self.assertEqual(a,b)
        opts=a['reSTIRPathTracingOptions']
        self.assertTrue(opts['useTemporalResampling'])
        self.assertEqual((opts['spatialNeighborCount'],opts['spatialGatherRadius']),(1,30))
        self.assertEqual(opts['maxHistoryLength'],20)
        self.assertFalse(opts['useAreaReservoirs']);self.assertFalse(opts['usePairedNeighbors'])
        self.assertEqual(a['sampleGenerator'],0)
    def test_temporal_render_keeps_current_path_seed_schedule(self):
        cam={'position':[1,2,3],'direction':[0,0,-1],'up':[0,1,0],'vertical_fov':60}
        source=capture.render_script(Path('scene.pyscene'),cam,Path('out'),40,8,'baseline',adapted=False)
        ast.parse(source)
        self.assertIn('tracer.useFixedSeed = True',source)
        self.assertIn('tracer.fixedSeed = frame - 1',source)
        self.assertIn('range(1, 49)',source)
        self.assertIn('if frame in [41, 42, 43, 44, 45, 46, 47, 48]',source)
        self.assertIn('m.clock.framerate = 0',source)
        self.assertIn('Static clock drift',source)
        self.assertNotIn('AccumulatePass',source)
        self.assertIn("'useTemporalResampling': True",source)
    def test_metadata_names_path_and_reuse_seed_offset(self):
        self.assertEqual(capture.seed_record(41),{'frame':41,'seed':40,'reuse_seed':39})
        self.assertEqual(capture.seed_record(1),{'frame':1,'seed':0,'reuse_seed':0})
        with self.assertRaises(ValueError):capture.seed_record(0)
    def test_temporal_analysis_requires_temporal_mode(self):
        self.assertTrue(analysis.TEMPORAL_REQUIRED)
        self.assertTrue(analysis.valid_settings({'temporal_reuse':True,'spp_per_frame':1}))
        self.assertFalse(analysis.valid_settings({'temporal_reuse':False,'spp_per_frame':1}))
        self.assertFalse(analysis.valid_settings({'temporal_reuse':True,'spp_per_frame':2}))

if __name__=='__main__':unittest.main()