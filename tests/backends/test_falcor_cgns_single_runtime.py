import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
class SingleRuntimeTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.falcor.cgns_single_runtime'),'single runtime must exist')
        from scripts.falcor import cgns_single_runtime
        return cgns_single_runtime
    def test_reject_wrong_source_existing_and_frozen_destinations(self):
        mod=self.module()
        for source,out in [('bad',ROOT/'build/cgns-single-test'),('reference',ROOT/'build'),('reference',ROOT/'docs/cgns-test'),('reference',ROOT/'build/falcor-reference-runtime/new'),('reference',ROOT/'build/falcor-cgns-pt-reference/new')]:
            with self.assertRaises(ValueError):mod.validate_request(source,out)
    def test_existing_four_neighbor_receipt_not_accepted(self):
        mod=self.module(); old=ROOT/'build/falcor-cgns-pt-reference/runtime'
        if old.exists():
            with self.assertRaises(ValueError):mod.verify_prepared(old)
if __name__=='__main__':unittest.main()
