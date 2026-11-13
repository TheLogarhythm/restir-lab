import ast
import unittest
import numpy as np
from pathlib import Path
from scripts.falcor import cgns_temporal_diagnostics as d

class TemporalDiagnosticTests(unittest.TestCase):
    def test_history_statistics_detect_real_survivors(self):
        x=np.array([[0.,.025],[.05,0.]],dtype=np.float32)
        s=d.history_stats(x)
        self.assertEqual(s['positive_pixels'],2)
        self.assertEqual(s['pixels'],4)
        self.assertAlmostEqual(s['positive_fraction'],0.5)
        self.assertGreater(s['max_age_frames'],1.9)
        self.assertAlmostEqual(s['max_age_frames'],2.0,places=5)
        with self.assertRaises(ValueError):d.history_stats(np.array([[float('nan')]]))
    def test_probe_script_marks_native_age_output_only_when_requested(self):
        cam={'position':[0,0,0],'direction':[0,0,-1],'up':[0,1,0],'vertical_fov':60}
        s=d.probe_script(Path('scene'),cam,Path('out'),method='cgns',temporal=True,dup=True)
        ast.parse(s)
        self.assertIn("g.markOutput('PathTracer.dupMap')",s)
        self.assertIn('m.frameCapture.captureAllOutputs = False',s)
        self.assertNotIn('m.frameCapture.captureAllOutputs = True',s)
        self.assertIn('if frame in [1, 41]',s)
        self.assertIn("'useTemporalResampling': True",s)
        a=d.probe_script(Path('scene'),cam,Path('out'),method='baseline',temporal=False,dup=False)
        self.assertNotIn("g.markOutput('PathTracer.dupMap')",a)
        self.assertIn("'useTemporalResampling': False",a)
    def test_color_comparison_requires_identical_float32_bits(self):
        x=np.ones((2,3,3),dtype=np.float32)
        self.assertEqual(d.compare_color(x,x.copy()),0.)
        y=x.copy();y[0,0,1]+=0.001
        with self.assertRaises(ValueError):d.compare_color(x,y)

if __name__=='__main__':unittest.main()