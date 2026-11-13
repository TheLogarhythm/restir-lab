import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.falcor import cgns_paper_capture as capture, spatial_campaign as campaign

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "experiments/configs/falcor-pt-spatial-comparison/restir-pt-spatial-comparison.json"


def experiment():
    return json.loads(CONFIG.read_text(encoding="utf8"))


class PaperConfigIntegrationTests(unittest.TestCase):
    def test_graph_and_generated_script_follow_supplied_experiment(self):
        cfg = experiment()
        cfg["graph"]["reSTIRPathTracingOptions"]["spatialGatherRadius"] = 17
        opts = capture.graph_options("baseline", experiment=cfg)
        self.assertEqual(opts["reSTIRPathTracingOptions"]["spatialGatherRadius"], 17)
        self.assertFalse(opts["reSTIRPathTracingOptions"]["useTemporalResampling"])
        cam = {"position": [1, 2, 3], "direction": [0, 0, -1], "up": [0, 1, 0], "vertical_fov": 60}
        script = capture.render_script(
            Path("scene.pyscene"),
            cam,
            Path("out"),
            40,
            8,
            "baseline",
            adapted=False,
            experiment=cfg,
        )
        self.assertIn(repr(opts), script)

    def test_cgns_runtime_verification_binds_shader_parameters(self):
        shader = experiment()["methods"]["cgns"]["shader"]
        with patch(
            "scripts.falcor.cgns_single_runtime.verify_prepared",
            return_value={"source_kind": "reference"},
        ) as verify:
            capture.validate_runtime(Path("runtime"), "cgns", False, shader_parameters=shader)
            verify.assert_called_once_with(Path("runtime"), expected_parameters=shader)

    def test_campaign_identity_binds_config_and_budget(self):
        cfg = experiment()
        cfg["render"]["warmup_frames"] = 12
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            base = root / "baseline"
            old = root / "extension"
            base.write_text("base")
            old.write_text("old")
            with (
                patch.object(campaign.six, "baseline_path", return_value=base),
                patch.object(campaign.six, "extension_manifest_path", return_value=old),
                patch.object(campaign, "_code_identity", return_value={}),
            ):
                result = campaign._identity(
                    {}, {}, "commit", experiment=cfg, experiment_sha256="a" * 64
                )
        self.assertEqual(result["warmup_frames"], 12)
        self.assertEqual(result["capture_frames"], list(range(13, 21)))
        self.assertEqual(result["experiment_config"]["sha256"], "a" * 64)

    def test_campaign_refuses_config_changed_before_work(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = root / "experiment.json"
            raw = CONFIG.read_bytes()
            path.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            value = experiment()
            path.write_text(json.dumps(value) + "\n", encoding="utf8")
            self.assertNotEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            with self.assertRaisesRegex(ValueError, "configuration changed before campaign"):
                campaign._run_campaign(
                    root / "output",
                    experiment=value,
                    experiment_path=path,
                    experiment_sha256=digest,
                    runtime_paths={},
                )
            self.assertFalse((root / "output").exists())

    def test_bad_config_rejected_before_runtime_preparation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = root / "experiment.json"
            cfg = experiment()
            cfg["methods"]["cgns"]["shader"]["candidate_count"] = 0
            path.write_text(json.dumps(cfg), encoding="utf8")
            with patch.object(campaign, "_prepare_runtimes") as prepare:
                with self.assertRaises(ValueError):
                    campaign.run_campaign(root / "out", experiment_path=path)
                prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
