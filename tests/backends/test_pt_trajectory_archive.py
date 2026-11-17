"""Archive guards reject timing misalignment and silent file loss."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from scripts.analysis.pt_trajectory_archive import CAPABILITIES, check_inventory, check_timing

class TrajectoryArchiveTests(unittest.TestCase):
    def timing(self):
        rows=[];raw=[];marks=[]
        for i in range(300):
            ms=10.+i%20;mean=sum(10.+k%20 for k in range(max(0,i-14),i+1))/min(i+1,15)
            rows.append({'frame':i+41,'video_frame':i,'video_time_seconds':i/30,'gpu_ms_raw':ms,
                'gpu_ms_mean15':mean,'gpu_fps_mean15':1000/mean,'smoothing_frames':min(i+1,15),
                'gpu_events_ms':{'/onFrameRender/gpu_time':ms,'/stage/gpu_time':ms/2}})
            raw.append({'gpu_measured_frame':i+41,'events_previous_frame':{'/onFrameRender/gpu_time':{'value':ms},'/stage/gpu_time':{'value':ms/2}}})
            marks.append({'video_frame':i,'label':f'CGNS | GPU {mean:.2f} ms | {1000/mean:.2f} GPU FPS | Playback 30 FPS'})
        return rows,raw,marks

    def test_valid_partial_and_full_smoothing_windows(self):
        check_timing(*self.timing())

    def test_missing_or_shifted_frame_rejected(self):
        rows,raw,marks=self.timing()
        with self.assertRaisesRegex(ValueError,'coverage'):check_timing(rows[:-1],raw,marks)
        rows[41]['frame']+=1
        with self.assertRaisesRegex(ValueError,'alignment'):check_timing(rows,raw,marks)

    def test_stage_and_fps_corruption_rejected(self):
        rows,raw,marks=self.timing();bad=copy.deepcopy(rows);bad[50]['gpu_events_ms']['/stage/gpu_time']+=1
        with self.assertRaisesRegex(ValueError,'Stage timing'):check_timing(bad,raw,marks)
        rows[50]['gpu_fps_mean15']+=1
        with self.assertRaisesRegex(ValueError,'GPU FPS'):check_timing(rows,raw,marks)

    def test_inventory_rejects_changes_and_escaping_paths(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/'archive-manifest.json').write_text('{}');p=root/'timing.json';p.write_bytes(b'[]')
            m={'capabilities':CAPABILITIES,'files':[{'path':'timing.json','bytes':2,'sha256':hashlib.sha256(b'[]').hexdigest()}]}
            check_inventory(root,m)
            p.write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError,'Changed file'):check_inventory(root,m)
            m['files'][0]['path']='../outside'
            with self.assertRaisesRegex(ValueError,'contained relative'):check_inventory(root,m)

    def test_inventory_rejects_missing_extra_and_duplicate_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "archive-manifest.json").write_text("{}")
            record = {"path": "timing.json", "bytes": 2,
                      "sha256": hashlib.sha256(b"[]").hexdigest()}
            manifest = {"capabilities": CAPABILITIES, "files": [record]}
            with self.assertRaisesRegex(ValueError, "Missing.*timing.json"):
                check_inventory(root, manifest)
            (root / "timing.json").write_bytes(b"[]")
            (root / "extra").write_bytes(b"unexpected")
            with self.assertRaisesRegex(ValueError, "unindexed.*extra"):
                check_inventory(root, manifest)
            (root / "extra").unlink()
            manifest["files"].append(record)
            with self.assertRaisesRegex(ValueError, "Duplicate.*timing.json"):
                check_inventory(root, manifest)

    def test_inventory_rejects_production_hdr_and_capability_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "archive-manifest.json").write_text("{}")
            (root / "quality.exr").write_bytes(b"retained")
            manifest = {"capabilities": CAPABILITIES, "files": [
                {"path": "quality.exr", "bytes": 8,
                 "sha256": hashlib.sha256(b"retained").hexdigest()}]}
            with self.assertRaisesRegex(ValueError, "Unexpected production HDR"):
                check_inventory(root, manifest)
            manifest["capabilities"] = dict(CAPABILITIES, raw_production_hdr=True)
            with self.assertRaisesRegex(ValueError, "Incorrect retained capabilities"):
                check_inventory(root, manifest)

    def test_inventory_requires_its_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "Missing.*archive-manifest.json"):
                check_inventory(root, {"capabilities": CAPABILITIES, "files": []})
