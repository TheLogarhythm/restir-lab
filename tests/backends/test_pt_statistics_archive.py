"""Statistics-only archives must preserve coverage and fail closed on data loss."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from scripts.analysis.pt_statistics_archive import coverage, inspect, inventory
from scripts.analysis.pt_stage_archive import VIEWS, METHODS, SEEDS

class StatisticsArchiveTests(unittest.TestCase):
    def test_changed_extra_and_escaping_files_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/"data.csv";p.write_bytes(b"frozen")
            (root/"manifest.json").write_text("{}")
            m={"files":[{"path":"data.csv","bytes":6,"sha256":hashlib.sha256(b"frozen").hexdigest()}]}
            inventory(root,m)
            p.write_bytes(b"edited")
            with self.assertRaisesRegex(ValueError,"File changed"):inventory(root,m)
            p.write_bytes(b"frozen");(root/"extra").write_text("unexpected")
            with self.assertRaisesRegex(ValueError,"unindexed"):inventory(root,m)
            m["files"][0]["path"]="../outside"
            with self.assertRaisesRegex(ValueError,"contained relative"):inventory(root,m)

    def test_missing_frame_and_duplicate_seed_rejected(self):
        summary=[];seeds=[];frames=[]
        for v in VIEWS:
            for m in METHODS:
                summary.append(dict(view=v,method=m,smape_percent=12,smape_seed_sd=0))
                for s in SEEDS:
                    seeds.append(dict(view=v,method=m,seed=s,smape_percent=12))
                    frames.extend(dict(view=v,method=m,seed=s,frame=f,smape_percent=12) for f in range(41,57))
        coverage(summary,seeds,frames)
        with self.assertRaisesRegex(ValueError,"Frame coverage"):coverage(summary,seeds,frames[:-1])
        seeds[-1]=seeds[0]
        with self.assertRaisesRegex(ValueError,"Seed coverage"):coverage(summary,seeds,frames)

    def test_statistics_archive_cannot_claim_raw_hdr(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"manifest.json").write_text(json.dumps({"kind":"falcor_pt_statistics_archive","capabilities":{"raw_quality_hdr":True}}))
            with self.assertRaisesRegex(ValueError,"Misleading archive capabilities"):inspect(root)

    def test_missing_and_duplicate_inventory_files_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text("{}")
            record = {"path": "missing.csv", "bytes": 0,
                      "sha256": hashlib.sha256(b"").hexdigest()}
            with self.assertRaisesRegex(ValueError, "Missing.*missing.csv"):
                inventory(root, {"files": [record]})
            (root / "missing.csv").write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "Duplicate.*missing.csv"):
                inventory(root, {"files": [record, record]})

    def test_statistics_archive_rejects_retained_hdr(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text("{}")
            (root / "quality.exr").write_bytes(b"retained")
            record = {"path": "quality.exr", "bytes": 8,
                      "sha256": hashlib.sha256(b"retained").hexdigest()}
            with self.assertRaisesRegex(ValueError, "Unexpected HDR"):
                inventory(root, {"files": [record]})

    def test_inventory_requires_its_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "Missing.*manifest.json"):
                inventory(root, {"files": []})
