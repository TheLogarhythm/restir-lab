"""Algorithm-neutral analysis axes and auxiliary evidence (validated-input seam)."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

from tests.fixtures.comparison import LegacyComparisonFixture, save_json, write_pfm, sha
from experiment.comparison import load_methods
from experiment.comparison_config import load_spec
from scripts.analysis import comparison_analysis as analysis
from scripts.analysis.comparison_report import generate
from scripts.analysis.comparison_verify import verify


class ComparisonGroupsTests(LegacyComparisonFixture,unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def inputs(self):
        source,_ = self.fixture(seeds=(1,3))
        old_spec,old,_ = load_methods(source)
        spec = load_spec()
        for key in ("views","resolution","seeds","preview_seed","acquisition","classification","display"):
            spec[key] = copy.deepcopy(old_spec[key])
        for method in spec["methods"].values(): method["source"] = {"kind":"render"}
        loaded = {}
        for i,(method,row) in enumerate(spec["methods"].items()):
            for seed in spec["seeds"]:
                item = copy.deepcopy(old[("room","cgns" if row["settings"]["cgns"] else "baseline",seed)])
                image = self.folder / f"{method}-{seed}.pfm.gz"
                write_pfm(image,np.full((3,4,3),.3+i*.15+seed*.02))
                item["image"] = item["captures"][2]["image"] = image
                loaded[("room",method,seed)] = item
        references = {}
        index = self.folder / "mock-reference-index.json";save_json(index,{})
        for component,value in (("direct",1.),("full",2.)):
            image,previous = self.folder / f"{component}.pfm.gz",self.folder / f"{component}-4096.pfm.gz"
            write_pfm(image,np.full((3,4,3),value));write_pfm(previous,np.full((3,4,3),value*.95))
            references[("room",2,component)] = {"image":image,"previous":previous,"record":{},"index":index,
                "target":{"resolution":[4,3],"component":component},"precision":"fixed path spp; precision not evaluated"}
        source = self.folder / "mock-comparison.json";save_json(source,{"schema_version":3})
        inventory = {str(p.resolve()):sha(p) for p in self.folder.rglob("*") if p.is_file()}
        return source,None,spec,loaded,references,inventory

    def test_all_groups_roundtrip_references_seeds_and_auxiliary_tampering(self):
        inputs = self.inputs();source = inputs[0]
        with patch.object(analysis,"load_inputs",return_value=inputs):
            result = analysis.analyze(source,self.folder / "analysis")
            generate(self.folder / "analysis/analysis.json",self.folder / "report")
            self.assertEqual(verify(source,self.folder / "analysis/analysis.json",self.folder / "report/report.json")["groups"],["DI","GI","PT"])
            row = result["views"]["room"]["captures"]["2"]
            self.assertEqual({g:v["reference"] for g,v in row["groups"].items()},{"DI":"direct","GI":"full","PT":"full"})
            for group in row["groups"].values():
                for method in group["methods"].values(): self.assertEqual(set(method["per_seed"]),{"1","3"})
            for component in ("direct","full"):
                changed = copy.deepcopy(result)
                changed["views"]["room"]["captures"]["2"]["references"][component]["change_4096_to_8192"]["rmae"] = 999
                save_json(self.folder / "analysis/analysis.json",changed)
                with self.assertRaisesRegex(ValueError,"recomputed"):
                    verify(source,self.folder / "analysis/analysis.json")

    def test_single_indirect_group_report_and_no_di_dependency(self):
        inputs = list(self.inputs())
        for selected in ("GI","PT"):
            spec = copy.deepcopy(inputs[2])
            spec["groups"] = {selected:spec["groups"][selected]}
            spec["methods"] = {m:r for m,r in spec["methods"].items() if r["algorithm"] == selected}
            spec["references"].pop("direct")
            loaded = {k:v for k,v in inputs[3].items() if k[1] in spec["methods"]}
            refs = {k:v for k,v in inputs[4].items() if k[2] == "full"}
            with patch.object(analysis,"load_inputs",return_value=(inputs[0],None,spec,loaded,refs,inputs[5])):
                output = self.folder / selected
                result = analysis.analyze(inputs[0],output)
                generate(output / "analysis.json",self.folder / (selected+"-report"))
                self.assertEqual(verify(inputs[0],output / "analysis.json")["groups"],[selected])
                self.assertEqual(set(result["views"]["room"]["captures"]["2"]["references"]),{"full"})
