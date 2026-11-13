"""Safety contracts for the six-view paper-setting CGNS campaign."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import OpenEXR


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_artifact(path, frame):
    OpenEXR.File({}, {"RGB": np.ones((2, 3, 3), dtype=np.float32) * frame}).write(str(path))
    return {
        "frame": frame,
        "seed": frame - 1,
        "reuse_seed": max(0, frame - 2),
        "hdr": path.name,
        "sha256": digest(path),
    }


class PaperCampaignTests(unittest.TestCase):

    def test_campaign_resume_revalidates_and_never_relaunches_completed_jobs(self):
        from contextlib import ExitStack, nullcontext
        from unittest.mock import patch
        from scripts.falcor import spatial_campaign as api
        from scripts.falcor import spatial_experiment_config as experiment_config

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            output = root / "campaign"
            config = root / "cfg.json"
            config.write_text("{}")
            experiment = experiment_config.load_config()
            experiment["graph"]["reSTIRPathTracingOptions"]["spatialGatherRadius"] = 13
            experiment_path = root / "experiment.json"
            experiment_path.write_text(json.dumps(experiment), encoding="utf8")
            ref = root / "reference.exr"
            make_artifact(ref, 1)
            b = root / "baseline-runtime"
            c = root / "cgns-runtime"
            b.mkdir()
            c.mkdir()
            runtimes = {("baseline", False): {"id": "b"}, ("cgns", False): {"id": "c"}}
            entry = {
                "adapted": False,
                "config_sha256": digest(config),
                "asset_sha256": {},
                "source_sha256": {},
            }
            key = ("classroom", "view-a")
            catalog = {
                key: {
                    "entry": entry,
                    "config": {},
                    "config_path": config,
                    "reference": {"path": str(ref), "sha256": digest(ref)},
                }
            }
            calls = []

            def launch(cfg, path, runtime, *, method, **kwargs):
                self.assertEqual(
                    kwargs["experiment"]["graph"]["reSTIRPathTracingOptions"][
                        "spatialGatherRadius"
                    ],
                    13,
                )
                self.assertEqual(kwargs["experiment_path"], experiment_path.resolve())
                self.assertEqual(kwargs["experiment_sha256"], digest(experiment_path))
                calls.append(method)
                path = Path(path)
                path.mkdir(parents=True)
                for name, value in [
                    ("resolved.py", "graph"),
                    ("resolved-camera.json", "{}"),
                    ("scene-state.json", "{}"),
                ]:
                    (path / name).write_text(value)
                artifacts = [
                    make_artifact(path / f"capture.PathTracer.color.{f}.exr", f)
                    for f in range(41, 49)
                ]
                meta = {
                    "status": "completed",
                    "requested_method": method,
                    "scene_id": "classroom",
                    "view_id": "view-a",
                    "scene_config_sha256": entry["config_sha256"],
                    "reference_baseline_sha256": "b",
                    "resolution": [1920, 1080],
                    "warmup_frames": 40,
                    "capture_frames": list(range(41, 49)),
                    "spp_per_frame": 1,
                    "image_accumulation": False,
                    "requested_graph_options": {},
                    "temporal_reuse": True,
                    "clock_policy": {"paused": True, "framerate": 0, "time": 0},
                    "seed_policy": "lag-one",
                    "build_commit": "c",
                    "gpu_driver": "g",
                    "artifacts": artifacts,
                }
                (path / "manifest.json").write_text(json.dumps(meta))
                return path / "manifest.json"

            def verify(path, *args, **kwargs):
                meta = json.loads((path / "manifest.json").read_text())
                self.assertEqual(meta["status"], "completed")
                api.validate_artifacts(path, meta["artifacts"], list(range(41, 49)), 3, 2)
                return (
                    meta,
                    {
                        "files": {"manifest.json": digest(path / "manifest.json")},
                        "artifacts": meta["artifacts"],
                    },
                )

            with ExitStack() as stack:
                stack.enter_context(patch.object(api, "ROOT", root))
                stack.enter_context(
                    patch.object(api, "RUNTIME", {("baseline", False): b, ("cgns", False): c})
                )
                stack.enter_context(
                    patch.object(
                        api,
                        "_prepare_runtimes",
                        return_value={("baseline", False): b, ("cgns", False): c},
                    )
                )
                stack.enter_context(
                    patch.object(api, "exclusive_operation", return_value=nullcontext())
                )
                stack.enter_context(patch.object(api, "check_renderer_idle"))
                stack.enter_context(
                    patch.object(api.build, "verify_build", return_value={"commit": "c"})
                )
                stack.enter_context(patch.object(api, "_reference_catalog", return_value=catalog))
                stack.enter_context(patch.object(api, "_runtime_snapshots", return_value=runtimes))
                stack.enter_context(
                    patch.object(api, "_code_identity", return_value={"code": "constant"})
                )
                stack.enter_context(patch.object(api.reference_extension_batch, "recheck_view"))
                stack.enter_context(patch.object(api.capture, "launch", side_effect=launch))
                stack.enter_context(patch.object(api, "_validate_job", side_effect=verify))
                report = api.run_campaign(output, experiment_path=experiment_path)
                self.assertTrue((report / "summary.json").exists())
                self.assertEqual(calls, ["baseline", "cgns"])
                saved = json.loads((output / "campaign.json").read_text())
                self.assertEqual(saved["job_path_base"], "campaign")
                invalid = {**saved, "job_path_base": "unknown"}
                (output / "campaign.json").write_text(json.dumps(invalid))
                with self.assertRaisesRegex(ValueError, "path base"):
                    api.run_campaign(output, experiment_path=experiment_path)
                (output / "campaign.json").write_text(json.dumps(saved))
                invalid = json.loads(json.dumps(saved))
                invalid["jobs"]["classroom/view-a/baseline"]["attempt"] = "jobs/other"
                (output / "campaign.json").write_text(json.dumps(invalid))
                with self.assertRaisesRegex(ValueError, "attempt"):
                    api.run_campaign(output, experiment_path=experiment_path)
                (output / "campaign.json").write_text(json.dumps(saved))
                self.assertEqual(
                    saved["jobs"]["classroom/view-a/baseline"]["attempt"],
                    "jobs/classroom/view-a/baseline/attempt-001",
                )
                input_path = output / saved["report"]["analysis_input"]
                inputs = json.loads(input_path.read_text())
                for rec in (
                    inputs["views"][0]["reference"],
                    inputs["views"][0]["pairs"][0]["baseline"],
                    inputs["views"][0]["pairs"][0]["cgns"],
                ):
                    self.assertFalse(Path(rec["path"]).is_absolute())
                    self.assertTrue((input_path.parent / rec["path"]).is_file())
                self.assertEqual(api.run_campaign(output, experiment_path=experiment_path), report)
                self.assertEqual(calls, ["baseline", "cgns"])
                import shutil

                with tempfile.TemporaryDirectory() as moved_dir:
                    moved = Path(moved_dir) / "workspace"
                    shutil.copytree(root, moved)
                    moved_catalog = {
                        key: {
                            **catalog[key],
                            "config_path": moved / "cfg.json",
                            "reference": {
                                "path": str(moved / "reference.exr"),
                                "sha256": digest(moved / "reference.exr"),
                            },
                        }
                    }
                    moved_runtimes = {
                        ("baseline", False): moved / "baseline-runtime",
                        ("cgns", False): moved / "cgns-runtime",
                    }
                    with (
                        patch.object(api, "ROOT", moved),
                        patch.object(api, "_reference_catalog", return_value=moved_catalog),
                        patch.object(api, "_prepare_runtimes", return_value=moved_runtimes),
                    ):
                        self.assertEqual(
                            api.run_campaign(
                                moved / "campaign", experiment_path=moved / "experiment.json"
                            ),
                            moved / "campaign" / "analysis" / "attempt-001",
                        )
                    self.assertEqual(calls, ["baseline", "cgns"])
                frame = next(
                    (output / "jobs/classroom/view-a/baseline/attempt-001").glob("capture*.exr")
                )
                frame.write_bytes(b"tamper")
                with self.assertRaises(ValueError):
                    api.run_campaign(output, experiment_path=experiment_path)
                self.assertEqual(calls, ["baseline", "cgns"])


if __name__ == "__main__":
    unittest.main()
