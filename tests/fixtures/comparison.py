"""Saved runs, reference compatibility, independent report generation and bad inputs."""
import copy
import importlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/"scripts/run")]
from tests.fixtures.provenance import lighting_build
from tests.fixtures.references import small_policy
from tests.fixtures.legacy_artifacts import write_capture, write_plane_geometry
from experiment.comparison_config import load_spec as load_current, resolve_configs as resolve_current, DI_SPEC
from experiment.artifacts import save_json, spatial_neighbor_stats
from experiment.images import write_pfm
from experiment.reference import suite_captures, REFERENCE_SCHEMA_VERSION, CONVERGENCE_METRIC
from rtxdi_common import sha


def load_spec():
    return json.loads((ROOT / "tests/fixtures/comparison-schema1.json").read_text())


def resolve_configs(old):
    current = load_current(DI_SPEC)
    for k in ("definition_file","resolution","seeds","preview_seed","views","classification"):
        current[k] = copy.deepcopy(old[k])
    current["reuse_mode"] = old["mode"]
    current["acquisition"] = {"protocol":"static", "warmup_frames":old["warmup_frames"], "capture_frames":[old["warmup_frames"]+1]}
    current["display"] = {"delta_range_pp":old["delta_range_pp"], "exposure_ev":{v:0 for v in old["views"]}}
    current["groups"] = {"DI":{"original":old["baseline"], "cgns":old["comparison"], "reference":"direct"}}
    current["methods"] = {m:{**copy.deepcopy(row), "algorithm":"DI", "source":{"kind":"render"}} for m,row in old["methods"].items()}
    return resolve_current(current)


class LegacyComparisonFixture:
    def fixture(self, seeds=(1,), reference=True):
        spec = load_spec()
        spec["views"] = {"room":copy.deepcopy(spec["views"]["cornell-box"])}
        spec.update(reference_budget=None, warmup_frames=1, seeds=list(seeds), preview_seed=seeds[0], resolution=[4,3])
        spec["classification"]["radius"] = 1
        build = lighting_build(); build.update(cgns=True)
        build["renderer_commit"] = "a6efab966b7c3b272da0461578eb56ac61c7cbff"
        saved = []
        for job in resolve_configs(spec):
            directory = self.folder/"runs"/job["method"]/str(job["seed"]); directory.mkdir(parents=True)
            config = job["config"]
            save_json(directory/"config.json", config)
            value = .5 if job["method"] == "baseline" else 1.2
            rgb = np.full((3,4,3), value + .1*(job["seed"]-1))
            capture = write_capture(directory, 2, rgb)
            stem = directory/"frame-0002"
            capture.update(write_plane_geometry(stem, 4,3,config["scene"]["camera"]["vertical_fov"]))
            np.full((3,4),130,dtype="<u4").tofile(stem.with_suffix(".spatial-counts"))
            capture.update(spatial_neighbor_stats(stem.with_suffix(".spatial-counts"),4,3,4))
            record = {"status":"completed", "config_sha256":sha(directory/"config.json"), "build":build,
                      "scene":{"sha256":"a"*64}, "captures":[capture], "timing":"fixture GPU scope"}
            save_json(directory/"manifest.json",record)
            save_json(directory/"resolved.json", {"cgns":config["definition"]["cgns"], "pdf_similarity":False,
                      "cgns_candidates":32,"cgns_early_stopping":True,"spatial_neighbor_counts":True,
                      "estimator":"restir_di","source_format":"RGBA16_FLOAT; export decoded losslessly to float32 PFM",
                      "display_passes":"bypassed; no display output","width":4,"height":3,
                      "aa":0,"denoiser":0,"checkerboard":0,"pixel_jitter":False,"mode":3})
            (directory/"timings.csv").write_text("frame,gpu_ms,spatial_ms,neighbor_selection_ms\n1,100,4,0\n2,2,.5,0\n")
            saved.append({key:job[key] for key in ("view","method","seed")} |
                         {"path":directory.relative_to(self.folder).as_posix(), "manifest_sha256":sha(directory/"manifest.json")})
        if reference:
            captures = suite_captures(self.folder/"runs")
            folder = self.folder/"reference"; folder.mkdir()
            write_pfm(folder/"ref.pfm",np.ones((3,4,3)))
            checks = {"schema_version":REFERENCE_SCHEMA_VERSION, "convergence_metric":CONVERGENCE_METRIC,
                      "converged":True,"reference_noise_ratio":.1,
                      "checkpoints":[{"samples_per_class_per_stream":n,"regions":{"full":{
                          "stream_disagreement_rmae":0,"change_rmae":None if n==1 else 0}}} for n in (1,2,4)]}
            save_json(folder/"convergence.json",checks)
            item = {"target":captures[0]["target"], "image":"ref.pfm","image_sha256":sha(folder/"ref.pfm"),
                    "convergence":"convergence.json","convergence_sha256":sha(folder/"convergence.json"),
                    "converged":True,"samples_per_class_per_stream":4}
            save_json(folder/"reference-index.json",{"schema_version":REFERENCE_SCHEMA_VERSION,
                "convergence_metric":CONVERGENCE_METRIC,"build":build,"seeds":[1001,2001],
                "references":{captures[0]["key"]:item}})
            spec["views"]["room"]["reference_index"] = str(folder/"reference-index.json")
        record = {"schema_version":1,"status":"completed","spec":spec,"runs":saved,"build":build}
        path = self.folder/"comparison.json"; save_json(path,record)
        return path,record

