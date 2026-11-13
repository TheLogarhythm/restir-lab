import tempfile
import unittest
from pathlib import Path
import numpy as np

class CaptureCheckTests(unittest.TestCase):
    def test_exact_rgb_comparison_detects_channel_and_shape_errors(self):
        from scripts.falcor import cgns_capture_validation as check
        a=np.zeros((2,3,3),dtype=np.float32)
        self.assertEqual(check.compare_pixels(a,a.copy()),0.)
        b=a.copy();b[1,2,0]=np.nextafter(np.float32(0),np.float32(1))
        with self.assertRaisesRegex(ValueError,'not bitwise equal'):check.compare_pixels(a,b)
        with self.assertRaisesRegex(ValueError,'shape'):check.compare_pixels(a,a[:1])
        c=a.copy();c[0,0,0]=np.nan
        with self.assertRaisesRegex(ValueError,'nonfinite'):check.compare_pixels(c,c)

    def test_frame_mapping_uses_actual_per_artifact_frame_not_filesystem_order(self):
        from scripts.falcor import cgns_capture_validation as check
        values=[{'frame':4,'hdr':'frame4.exr','sha256':'d'}, {'frame':1,'hdr':'frame1.exr','sha256':'a'}]
        self.assertEqual(check.artifact_for_frame(values,4)['hdr'],'frame4.exr')
        with self.assertRaises(ValueError):check.artifact_for_frame(values,2)
        with self.assertRaises(ValueError):check.artifact_for_frame(values+[values[0]],4)
        with self.assertRaises(ValueError):check.artifact_for_frame([{'frame':4,'hdr':'../oops.exr','sha256':'d'}],4)

    def test_artifacts_must_cover_each_frame_and_matching_seed(self):
        from scripts.falcor import cgns_capture_validation as check
        good=[{'frame':1,'seed':0,'hdr':'capture.PathTracer.color.1.exr','sha256':'a'}, {'frame':2,'seed':1,'hdr':'capture.PathTracer.color.2.exr','sha256':'b'}]
        check.validate_artifact_set(good,[1,2])
        with self.assertRaises(ValueError):check.validate_artifact_set(good,[1,2,3])
        bad=[dict(x) for x in good];bad[1]['seed']=0
        with self.assertRaises(ValueError):check.validate_artifact_set(bad,[1,2])
        bad=[dict(x) for x in good];bad[1]['hdr']='capture.PathTracer.color.1.exr'
        with self.assertRaises(ValueError):check.validate_artifact_set(bad,[1,2])

    def test_paper_resource_preflight_is_limited_to_two_frames(self):
        from scripts.falcor import cgns_paper_resource_preflight as check
        check.validate_count(1);check.validate_count(2)
        for count in (0,3,True,-1):
            with self.subTest(count=count), self.assertRaises(ValueError):check.validate_count(count)

    def test_diagnostic_expected_outcomes_include_positive_control(self):
        from scripts.falcor import cgns_single_diagnostic_run as check
        check.validate_counts([0,0,0,0],fault=False)
        check.validate_counts([0,1,0,0],fault=True)
        with self.assertRaises(ValueError):check.validate_counts([0,0,1,0],fault=False)
        with self.assertRaises(ValueError):check.validate_counts([0,0,0,0],fault=True)
        with self.assertRaises(ValueError):check.validate_counts([],fault=False)

if __name__=='__main__':unittest.main()
