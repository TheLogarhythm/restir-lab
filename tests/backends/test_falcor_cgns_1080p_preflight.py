import unittest
from unittest.mock import patch
from pathlib import Path

class PreflightTest(unittest.TestCase):
    def test_enforces_only_native_resolution_and_small_frame_budget(self):
        from scripts.falcor import cgns_1080p_preflight as p
        for n in (1, 2): p.validate_preflight(1920,1080,n)
        for case in ((1919,1080,1),(1920,1080,0),(1920,1080,3),(1920,1080,True)):
            with self.subTest(case=case), self.assertRaises(ValueError): p.validate_preflight(*case)

    def test_budget_override_restores_existing_validator_on_success_and_error(self):
        from scripts.falcor import cgns_1080p_preflight as p
        old=p.smoke.validate_budget
        with p.fullhd_budget_override():
            self.assertIsNot(p.smoke.validate_budget,old)
            p.smoke.validate_budget(1920,1080,2)
            with self.assertRaises(ValueError): p.smoke.validate_budget(640,360,1)
        self.assertIs(p.smoke.validate_budget,old)
        with self.assertRaisesRegex(RuntimeError,'fixture'):
            with p.fullhd_budget_override(): raise RuntimeError('fixture')
        self.assertIs(p.smoke.validate_budget,old)

    def test_gpu_csv_parser_rejects_invalid_or_multiple_devices(self):
        from scripts.falcor import cgns_1080p_preflight as p
        self.assertEqual(p.parse_gpu_stats('0, 8123, 4096, 98\n'),{'index':0,'total_mib':8123,'used_mib':4096,'util_percent':98})
        for text in ('','0, 1, 2','0, 8, 9, 100','0, 8, 4, 101','0, 8, 4, 1\n1, 8, 4, 1'):
            with self.subTest(text=text), self.assertRaises(ValueError): p.parse_gpu_stats(text)

if __name__=='__main__': unittest.main()
