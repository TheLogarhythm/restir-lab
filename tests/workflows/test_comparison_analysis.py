"""Unified analysis/report contracts, including schema-1 historical inputs."""
import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image

from tests.fixtures.comparison import LegacyComparisonFixture, ROOT, save_json, sha, write_pfm
from scripts.analysis import comparison_analysis as api
from scripts.analysis.comparison_report import generate, delta_rgb, delta_metadata, error_rgb
from scripts.analysis.comparison_verify import verify, verify_report
from experiment.legacy_comparison import load_di_inputs
from tests.fixtures.references import small_policy


class ComparisonAnalysisTests(LegacyComparisonFixture, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def analyzed(self, *, seeds=(1,)):
        source, record = self.fixture(seeds=seeds)
        result = api.analyze(source,self.folder / "analysis")
        return source, record, result

    def capture(self, result):
        return result["views"]["room"]["captures"]["2"]

    def report(self):
        return generate(self.folder / "analysis/analysis.json",self.folder / "report")

    def verify(self, source, *, report=True):
        return verify(source,self.folder / "analysis/analysis.json",self.folder / "report/report.json" if report else None)

    def frozen_fixture(self):
        source, record = self.fixture()
        index = Path(record["spec"]["views"]["room"]["reference_index"])
        record["reference_inputs"] = {"room":{"path":str(index), "sha256":sha(index)}}
        save_json(source,record)
        return source,record,index

    def test_frozen_reference_damage_fails_before_output_creation(self):
        source,_,index = self.frozen_fixture()
        index.write_text(index.read_text()+"\n")
        with self.assertRaisesRegex(ValueError,"[Rr]eference"):
            api.analyze(source,self.folder / "analysis")
        self.assertFalse((self.folder / "analysis").exists())

    def test_frozen_reference_cannot_be_substituted(self):
        source,record,index = self.frozen_fixture()
        alternate = index.with_name("alternate.json")
        alternate.write_bytes(index.read_bytes())
        record["spec"]["views"]["room"]["reference_index"] = str(alternate)
        save_json(source,record)
        with self.assertRaisesRegex(ValueError,"[Rr]eference"):
            api.analyze(source,self.folder / "analysis")

    def test_input_mutation_during_analysis_is_failed(self):
        source,_,index = self.frozen_fixture()
        original = api.aggregate_smape
        def mutate(*args,**kwargs):
            result = original(*args,**kwargs)
            index.write_text(index.read_text()+"\n")
            return result
        with patch.object(api,"aggregate_smape",side_effect=mutate), self.assertRaises(ValueError):
            api.analyze(source,self.folder / "analysis")
        self.assertEqual(api.read_json(self.folder / "analysis/analysis.json")["status"],"failed")

    def test_validated_hdr_cannot_be_rebound_after_validation(self):
        source,_ = self.fixture()
        original = api.load_inputs
        def mutate(*args,**kwargs):
            inputs = original(*args,**kwargs)
            image = next(iter(inputs[3].values()))["image"]
            write_pfm(image,np.full((3,4,3),7.))
            return inputs
        with patch.object(api,"load_inputs",side_effect=mutate),self.assertRaisesRegex(ValueError,"HDR input changed"):
            api.analyze(source,self.folder / "analysis")
        self.assertEqual(api.read_json(self.folder / "analysis/analysis.json")["status"],"failed")

    def test_cached_timings_cannot_be_rebound_after_validation(self):
        source,_ = self.fixture()
        original = api.load_inputs
        def mutate(*args,**kwargs):
            inputs = original(*args,**kwargs)
            path = next(iter(inputs[3].values()))["directory"] / "timings.csv"
            path.write_text(path.read_text().replace("2,2,.5,0","2,999,.5,0"))
            return inputs
        with patch.object(api,"load_inputs",side_effect=mutate),self.assertRaisesRegex(ValueError,"Validated input changed"):
            api.analyze(source,self.folder / "analysis")

    def test_report_rejects_hdr_mutation_during_read(self):
        from scripts.analysis import comparison_report
        self.analyzed()
        original = comparison_report.read_pfm
        def mutate(path):
            image = original(path)
            write_pfm(path,np.full_like(image,7))
            return image
        with patch.object(comparison_report,"read_pfm",side_effect=mutate),self.assertRaisesRegex(ValueError,"source/artifact changed"):
            self.report()
        self.assertFalse((self.folder / "report/report.json").exists())

    def test_report_pins_analysis_before_parsing(self):
        from scripts.analysis import comparison_report
        self.analyzed()
        original = comparison_report.read_json
        def mutate(path):
            data = original(path)
            Path(path).write_text(Path(path).read_text()+"\n")
            return data
        with patch.object(comparison_report,"read_json",side_effect=mutate),self.assertRaisesRegex(ValueError,"source/artifact changed"):
            self.report()
        self.assertFalse((self.folder / "report").exists())

    def test_paired_reference_method_reuse_has_no_fixed_budget_auxiliary(self):
        source,_ = self.fixture()
        spec,loaded,_ = api.load_methods(source)
        spec["methods"]["baseline"]["source"] = {"kind":"comparison","index":str(source),"method":"baseline"}
        self.assertIsNone(api._old_di_reference(spec,"room",loaded[("room","baseline",1)]["captures"][2]))

    def test_group_spatial_time_is_not_the_shared_di_time(self):
        from scripts.analysis.comparison_diagnostics import timing_summary
        item = {"timings":{1:{"frame":1,"gpu_ms":10,"spatial_ms":1,"gi_spatial_ms":2,"pt_spatial_ms":3}}}
        for algorithm,expected in (("DI",1),("GI",2),("PT",3)):
            self.assertEqual(timing_summary(item,1,algorithm)["spatial_ms_capture"],expected)
        template = (ROOT / "scripts/analysis/comparison_report.html").read_text()
        self.assertIn("fmt(item.timing.spatial_ms_capture)",template)
        self.assertIn("fmt(item.timing.gpu_ms_mean_run)",template)

    def test_report_rejects_unvalidated_output_names_before_writing(self):
        _,_,result = self.analyzed()
        result["views"]["../outside"] = result["views"].pop("room")
        save_json(self.folder / "analysis/analysis.json",result)
        with self.assertRaisesRegex(ValueError,"view coverage"): self.report()
        self.assertFalse((self.folder / "report").exists())

    def test_multiple_seeds_frame_axis_and_capture_timing(self):
        source,_,result = self.analyzed(seeds=(1,3))
        row = self.capture(result)
        self.assertEqual(set(result["views"]["room"]["captures"]),{"2"})
        self.assertEqual(row["regions"],{"all":12,"hard":1})
        self.assertEqual(row["references"]["direct"]["precision"],"passed")
        group = row["groups"]["DI"]
        per_seed = group["methods"]["baseline"]["per_seed"]
        self.assertEqual(set(per_seed),{"1","3"})
        self.assertEqual(per_seed["1"]["timing_ms"]["gpu_ms"],2)
        self.assertEqual(per_seed["1"]["timing"]["gpu_ms_mean_run"],51)
        self.assertGreater(group["comparison"]["all"]["improvement_pp"],0)
        with np.load(self.folder / "analysis" / group["maps"]["path"]) as maps:
            self.assertEqual(maps["improvement"].shape,(3,4))
            np.testing.assert_array_equal(maps["improvement"],maps["original"]-maps["cgns"])
        for name in ("src/metrics/comparison_metrics.py","src/image_io/images.py"):
            self.assertEqual(result["provenance"]["code_sha256"][name],sha(ROOT / name))
        with self.assertRaises(FileExistsError): api.analyze(source,self.folder / "analysis")

    def test_report_roundtrip_and_exposure_does_not_change_metrics(self):
        source,_,result = self.analyzed()
        analysis = self.folder / "analysis/analysis.json"
        digest = sha(analysis)
        html = self.report()
        self.assertEqual(self.verify(source)["status"],"verified")
        display = copy.deepcopy(result["spec"]["display"])
        display["exposure_ev"]["room"] = 5
        display["delta_range_pp"] = 5
        second = self.folder / "bright"
        with patch.object(api,"aggregate_smape",side_effect=AssertionError("Report must not compute metrics")):
            generate(analysis,second,display=display)
            verify_report(analysis,second / "report.json")
        self.assertEqual(sha(analysis),digest)
        a,b = api.read_json(self.folder / "report/report.json"),api.read_json(second / "report.json")
        for key,row in a["artifacts"].items():
            other = b["artifacts"][key]
            if row["transform"]["kind"] == "radiance":
                self.assertEqual(other["transform"]["exposure_ev"],5)
                self.assertNotEqual(row["image"]["sha256"],other["image"]["sha256"])
            else:
                self.assertEqual(row["image"]["sha256"],other["image"]["sha256"])
        self.assertIn("data:image/png;base64",html.read_text())
        self.assertNotIn("__ANALYSIS_JSON__",html.read_text())
        with self.assertRaises(FileExistsError): self.report()

    def test_analysis_group_method_seed_frame_and_target_coverage(self):
        source,_,result = self.analyzed(seeds=(1,3))
        def capture(r): return self.capture(r)
        mutations = [lambda r:capture(r)["groups"].clear(),
                     lambda r:capture(r)["groups"]["DI"].update(reference="full"),
                     lambda r:capture(r)["groups"]["DI"]["methods"].pop("cgns"),
                     lambda r:capture(r)["groups"]["DI"]["methods"]["baseline"]["per_seed"].pop("3"),
                     lambda r:r["views"]["room"]["captures"].update({"3":copy.deepcopy(capture(r))})]
        for mutate in mutations:
            changed = copy.deepcopy(result);mutate(changed)
            save_json(self.folder / "analysis/analysis.json",changed)
            with self.assertRaises(ValueError): self.verify(source,report=False)

    def test_verifier_binds_summary_capture_timing_and_neighbors(self):
        source,_,result = self.analyzed()
        def method(r): return self.capture(r)["groups"]["DI"]["methods"]["baseline"]
        mutations = [lambda r:method(r)["summary"].update(all=999),
                     lambda r:method(r)["per_seed"]["1"].update(frame=1,sampling_frame=7),
                     lambda r:method(r)["per_seed"]["1"]["timing_ms"].update(gpu_ms=999),
                     lambda r:method(r)["per_seed"]["1"]["neighbors"]["mean_surface"].update(all=999),
                     lambda r:self.capture(r)["groups"]["DI"]["comparison"]["all"].update(improvement_pp=-999)]
        for mutate in mutations:
            changed = copy.deepcopy(result);mutate(changed)
            save_json(self.folder / "analysis/analysis.json",changed)
            with self.assertRaisesRegex(ValueError,"recomputed"): self.verify(source,report=False)

    def test_verifier_recomputes_maps_even_if_hash_is_updated(self):
        source,_,result = self.analyzed()
        record = self.capture(result)["groups"]["DI"]["maps"]
        path = self.folder / "analysis" / record["path"]
        with np.load(path) as archive: maps = {k:archive[k] for k in archive.files}
        maps["original"] += 1
        np.savez_compressed(path,**maps)
        record["sha256"] = sha(path)
        save_json(self.folder / "analysis/analysis.json",result)
        with self.assertRaisesRegex(ValueError,"recomputed"): self.verify(source,report=False)

    def test_verifier_rebuilds_mask_and_geometry_provenance(self):
        source,_,result = self.analyzed()
        record = self.capture(result)["geometry"]["mask"]
        path = self.folder / "analysis" / record["path"]
        with np.load(path) as archive: masks = {k:archive[k] for k in archive.files}
        masks["hard"] = np.roll(masks["hard"],1,axis=1)
        np.savez_compressed(path,**masks);record["sha256"] = sha(path)
        self.capture(result)["geometry"]["source_sha256"] = "0"*64
        save_json(self.folder / "analysis/analysis.json",result)
        with self.assertRaisesRegex(ValueError,"recomputed"): self.verify(source,report=False)

    def test_whole_image_only_keeps_no_geometry_dependency(self):
        source,record = self.fixture()
        record["spec"]["classification"]["regions"] = ["all"]
        for entry in record["runs"]:
            directory = source.parent / entry["path"]
            manifest = api.read_json(directory / "manifest.json")
            for capture in manifest["captures"]:
                capture.pop("geometry");capture.pop("geometry_sha256")
            save_json(directory / "manifest.json",manifest)
            entry["manifest_sha256"] = sha(directory / "manifest.json")
        save_json(source,record)
        result = api.analyze(source,self.folder / "analysis")
        self.assertEqual(self.capture(result)["geometry"],{})
        self.assertEqual(self.verify(source,report=False)["status"],"verified")

    def test_missing_reference_fails_explicitly(self):
        source,_ = self.fixture(reference=False)
        with self.assertRaisesRegex(ValueError,"[Rr]eference"):
            api.analyze(source,self.folder / "analysis")
        self.assertFalse((self.folder / "analysis").exists())

    def test_duplicate_missing_seed_and_modified_manifest_rejected(self):
        source,record = self.fixture(seeds=(1,3))
        for entries in (record["runs"]+[record["runs"][0]],record["runs"][:-1],
                        [dict(record["runs"][0],seed=True),*record["runs"][1:]],
                        [dict(record["runs"][0],manifest_sha256="0"*64),*record["runs"][1:]]):
            bad = dict(record,runs=entries)
            with self.assertRaises(ValueError): load_di_inputs(source,bad)

    def test_reference_target_and_build_mismatch_fail(self):
        source,record = self.fixture()
        index = Path(record["spec"]["views"]["room"]["reference_index"])
        original = api.read_json(index)
        for field in ("target","build"):
            changed = copy.deepcopy(original)
            if field == "target": next(iter(changed["references"].values()))["target"]["resolution"] = [2,2]
            else: changed["build"]["renderer_commit"] = "bad"
            save_json(index,changed)
            with self.assertRaises(ValueError): api.analyze(source,self.folder / (field+"-analysis"))

    def test_fixed_policy_rejects_paired_substitution(self):
        source,record = self.fixture()
        record["spec"]["reference_budget"] = small_policy()
        record["reference_build"] = record["build"]
        save_json(source,record)
        with self.assertRaisesRegex(ValueError,"fixed-budget"):
            api.analyze(source,self.folder / "analysis")

    def test_wrong_hdr_shape_and_nonfinite_rejected(self):
        source,record = self.fixture()
        directory = source.parent / record["runs"][0]["path"]
        manifest = api.read_json(directory / "manifest.json")
        image = directory / "frame-0002.pfm.gz"
        for i,rgb in enumerate((np.zeros((2,2,3)),np.full((3,4,3),np.nan))):
            if np.isfinite(rgb).all():
                write_pfm(image,rgb)
            else:
                with gzip.open(image,"wb") as stream:
                    stream.write(b"PF\n4 3\n-1.0\n" + np.asarray(rgb,dtype="<f4").tobytes())
            manifest["captures"][0]["image_sha256"] = sha(image)
            save_json(directory / "manifest.json",manifest)
            record["runs"][0]["manifest_sha256"] = sha(directory / "manifest.json")
            save_json(source,record)
            with self.assertRaises(ValueError): api.analyze(source,self.folder / f"malformed-{i}")

    def test_runtime_processing_and_camera_mismatch_rejected(self):
        source,record = self.fixture()
        directory = source.parent / record["runs"][0]["path"]
        resolved = api.read_json(directory / "resolved.json")
        for key,value in (("aa",1),("pixel_jitter",True),("denoiser",1),("checkerboard",1),("mode",0),("width",9)):
            save_json(directory / "resolved.json",dict(resolved,**{key:value}))
            with self.assertRaises(ValueError): load_di_inputs(source,record)
        save_json(directory / "resolved.json",resolved)
        record["spec"]["views"]["room"]["camera"] = {"position":[99,99,99]}
        with self.assertRaisesRegex(ValueError,"camera"): load_di_inputs(source,record)

    def test_empty_hard_region_and_modified_geometry_rejected(self):
        source,record = self.fixture()
        record["spec"]["classification"]["hard_percent"] = 0
        save_json(source,record)
        with self.assertRaisesRegex(ValueError,"empty mask"): api.analyze(source,self.folder / "empty")
        record["spec"]["classification"]["hard_percent"] = 10;save_json(source,record)
        directory = source.parent / record["runs"][1]["path"]
        geometry = next(directory.glob("*.geometry.npz"))
        geometry.write_bytes(b"changed")
        with self.assertRaises(ValueError): api.analyze(source,self.folder / "damaged")

    def test_paired_precision_is_rechecked(self):
        source,record = self.fixture()
        index = Path(record["spec"]["views"]["room"]["reference_index"])
        content = api.read_json(index);entry = next(iter(content["references"].values()))
        checks_path = index.parent / entry["convergence"]
        checks = api.read_json(checks_path)
        checks["checkpoints"][-1]["regions"]["full"]["stream_disagreement_rmae"] = 10
        save_json(checks_path,checks);entry["convergence_sha256"] = sha(checks_path);save_json(index,content)
        result = api.analyze(source,self.folder / "analysis")
        self.assertEqual(self.capture(result)["references"]["direct"]["precision"],"insufficient")
        self.assertTrue(self.capture(result)["groups"]["DI"]["maps"])

    def test_fixed_reference_roundtrip_and_frozen_build_requirement(self):
        from experiment import fixed_reference as fixed
        from experiment.reference import suite_captures
        from experiment.runner import relative_path
        source,record = self.fixture(reference=False)
        policy = small_policy();record["spec"]["reference_budget"] = policy
        sample = suite_captures(self.folder / "runs")[0]
        root = self.folder / "fixed";previous = None
        for samples in policy["checkpoints"]:
            folder = root / sample["key"] / f"seed-1001/checkpoint-{samples}/attempt-1"
            folder.mkdir(parents=True)
            config = fixed.make_config(sample,policy,samples,previous)
            if previous: config["reference"]["resume_image"] = relative_path(previous,folder)
            save_json(folder / "config.json",config)
            image = folder / f"frame-{samples//64:04d}.pfm.gz";write_pfm(image,np.ones((3,4,3)))
            save_json(folder / "manifest.json",{"status":"completed", "config_sha256":sha(folder / "config.json"),
                "scene":sample["manifest"]["scene"], "build":record["build"], "wall_seconds_including_startup_and_export":2,
                "captures":[{"frame":samples//64,"image_sha256":sha(image)}]})
            previous = image
        with patch("experiment.artifacts.validate_run_outputs"):
            row = fixed.reference_record(root,sample,policy,image,record["build"])
            index = root / "reference-index.json"
            save_json(index,{"schema_version":1,"kind":"fixed_budget_references","policy":policy,
                "build":record["build"],"references":{sample["key"]:row}})
            record["reference_build"] = record["build"]
            record["spec"]["views"]["room"]["reference_index"] = str(index);save_json(source,record)
            result = api.analyze(source,self.folder / "analysis")
            self.assertIn("precision not evaluated",self.capture(result)["references"]["direct"]["precision"])
            self.report();self.assertEqual(self.verify(source)["status"],"verified")
            record.pop("reference_build");save_json(source,record)
            with self.assertRaisesRegex(ValueError,"frozen reference build"):
                api.analyze(source,self.folder / "missing-build")

    def test_report_rejects_tampered_html_pixels_and_bindings(self):
        source,_,_ = self.analyzed();html = self.report()
        original = html.read_text();html.write_text(original+"stale")
        with self.assertRaises(ValueError): self.verify(source)
        html.write_text(original)
        report = api.read_json(self.folder / "report/report.json")
        artifact = next(iter(report["artifacts"].values()))
        path = self.folder / "report" / artifact["image"]["path"]
        Image.fromarray(np.zeros((3,4,3),np.uint8)).save(path)
        artifact["image"]["sha256"] = sha(path)
        save_json(self.folder / "report/report.json",report)
        with self.assertRaisesRegex(ValueError,"pixels"):
            verify_report(self.folder / "analysis/analysis.json",self.folder / "report/report.json")

    def test_delta_sign_zero_quantization_and_exact_clipping(self):
        delta = np.array([[-100,-5,0,5,100]],dtype=np.float64)
        rgb = delta_rgb(delta)
        decoded = (rgb[:,:,0].astype(int)*256+rgb[:,:,1].astype(int)-32768)/327.67
        np.testing.assert_allclose(decoded,delta,atol=.5/327.67,rtol=0)
        self.assertEqual(decoded[0,2],0)
        meta = delta_metadata(delta)
        self.assertEqual(meta["clipped_pixels_by_tenth_pp"][49],2)
        self.assertEqual(meta["clipped_pixels_by_tenth_pp"][999],0)
        self.assertEqual(error_rgb(np.array([[0.,100.]])).shape,(1,2,3))
