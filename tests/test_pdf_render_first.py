"""Keep method captures available when deferred references exhaust their budget."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment.images import preview_rgb, write_pfm
from experiment.controlled_budget import BudgetExceeded, ExperimentBudget


from fixtures.modules import worker_module as load_worker


class RenderFirstTests(unittest.TestCase):
    def instance(self, module, root):
        instance = module.ControlledExperiment.__new__(module.ControlledExperiment)
        instance.root, instance.state, instance.state_path = root, {}, root / "state.json"
        instance.matrix = {item["id"]: item for item in module.conditions()}
        instance.build, instance.reference_build, instance.matrix_hash = {"pdf": "original"}, {"reference": "original"}, "frozen"
        instance.budget = ExperimentBudget(root)
        return instance

    def test_all_method_captures_and_visual_comparisons_precede_references_and_survive_failure(self):
        module = load_worker()
        with tempfile.TemporaryDirectory() as folder:
            root, events = Path(folder), []
            instance = self.instance(module, root)
            def technical():
                return {"technical_passed": True, "validation_version": 1, "kind": "technical_only",
                    "build": instance.build, "matrix_sha256": "frozen", "references_accepted": False, "runs": {}}
            instance.technical_pilot = technical
            def render(condition, seed, enabled, *, area="formal", mode="combined", neighbors=4, **kwargs):
                path = root / area / condition["id"] / mode / str(neighbors) / str(seed) / str(enabled)
                if not path.exists():
                    path.mkdir(parents=True)
                    (path / "capture.done").write_text("immutable raw capture")
                    events.append(("render", path))
                return path
            instance.render = render
            instance.export_raw = lambda condition, report, destination: events.append(("visual", condition["id"]))
            class References:
                def ensure(self, captures, rois=(), **kwargs):
                    events.append(("reference", None))
                    raise RuntimeError("Reference precision not reached")
            instance.references = References()
            # GPU execution and HDR capture decoding are the external boundaries.
            instance.captures = lambda paths: [{"image": path, "key": "pose"} for path in paths]
            def reference_pilot(receipt):
                instance.references.ensure([], [])
            instance.reference_pilot = reference_pilot
            with self.assertRaisesRegex(RuntimeError, "Reference precision"):
                instance.execute()
            first_reference = next(i for i, event in enumerate(events) if event[0] == "reference")
            renders = [value for kind, value in events if kind == "render"]
            self.assertEqual(len(renders), 78)
            self.assertTrue(all(kind != "render" for kind, _ in events[first_reference:]))
            self.assertEqual(len([kind for kind, _ in events[:first_reference] if kind == "visual"]), 9)
            self.assertEqual(instance.state["completed_method_runs"], 78)
            self.assertTrue(instance.state["raw_renders_completed"])
            self.assertNotIn("pilot_passed", instance.state)
            before = {path: (path / "capture.done").read_bytes() for path in renders}
            with self.assertRaisesRegex(RuntimeError, "Reference precision"):
                instance.execute()
            self.assertEqual(len([kind for kind, _ in events if kind == "render"]), 78)
            self.assertEqual(before, {path: (path / "capture.done").read_bytes() for path in renders})

    def test_technical_pilot_never_claims_reference_acceptance(self):
        module = load_worker()
        with tempfile.TemporaryDirectory() as folder:
            instance = self.instance(module, Path(folder))
            def render(condition, seed, enabled, *, tag=None, **kwargs):
                path = instance.root / (tag or condition["id"]) / str(enabled)
                path.mkdir(parents=True, exist_ok=True)
                if tag == "cornell-reset":
                    (path / "resolved-frames.jsonl").write_text('\n'.join(json.dumps({"frame": frame, "history_reset": True}) for frame in (1, 65)))
                return path
            instance.render = render
            instance.references = object()  # Any accidental reference call must fail.
            with patch.object(module, "read_pfm", return_value=np.ones((2, 2, 3))):
                receipt = instance.technical_pilot()
            module.validate_technical_gate(receipt, instance.build, instance.matrix_hash)
            self.assertTrue(receipt["technical_passed"])
            self.assertIs(receipt["references_accepted"], False)
            self.assertTrue(instance.state["technical_pilot_passed"])
            self.assertNotIn("pilot_passed", instance.state)
            with self.assertRaises(ValueError):
                module.validate_pilot_gate(receipt, instance.build, instance.matrix_hash, instance.reference_build)
            for field, value in (("build", {}), ("matrix_sha256", "changed"), ("technical_passed", False)):
                changed = {**receipt, field: value}
                with self.subTest(field=field), self.assertRaises(ValueError):
                    module.validate_technical_gate(changed, instance.build, instance.matrix_hash)

    def test_raw_export_retains_display_pixels_and_does_not_generate_error_metrics(self):
        module = load_worker()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sources = []
            for method, enabled, value in (("off", False, 1.), ("on", True, 2.)):
                directory = root / method
                directory.mkdir()
                (directory / "config.json").write_text(json.dumps({"seed": 1, "definition": {"pdf_similarity": enabled}}))
                for frame in (1, 128):
                    write_pfm(directory / f"frame-{frame:04d}.pfm.gz", np.full((4, 8, 3), value))
                sources.append(directory)
            output = root / "raw-comparison"
            receipt = module.export_raw_condition(output, *sources, exposure_ev=0., write_videos=False,
                                                   expected_resolution=(8, 4), expected_frames=(1, 128))
            self.assertIs(receipt["references_accepted"], False)
            self.assertEqual(receipt["kind"], "method_visual_comparison")
            self.assertEqual(receipt["frames"], [1, 128])
            self.assertEqual(receipt["fps"], 30)
            self.assertFalse((output / "maps").exists())
            self.assertFalse((output / "frame-metrics.csv").exists())
            with Image.open(output / "frames/pdf-on/frame-0128.png") as image:
                np.testing.assert_array_equal(np.asarray(image), preview_rgb(np.full((4, 8, 3), 2.)))
            def exhausted():
                raise BudgetExceeded("export deadline reached")
            with self.assertRaises(BudgetExceeded):
                module.export_raw_condition(root / "expired", *sources, write_videos=False,
                    expected_resolution=(8, 4), check_budget=exhausted)
            self.assertFalse((root / "expired").exists())
            write_pfm(sources[1] / "frame-0128.pfm.gz", np.ones((4, 7, 3)))
            invalid = root / "invalid"
            with self.assertRaisesRegex(ValueError, "resolution"):
                module.export_raw_condition(invalid, *sources, write_videos=False, expected_resolution=(8, 4))
            self.assertFalse(invalid.exists())

    def test_resume_reuses_immutable_capture_after_budget_but_rejects_different_build(self):
        module = load_worker()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            instance = self.instance(module, root)
            condition = instance.matrix["cornell-static"]
            instance.assets = {condition["scene"]["scene_id"]: {"sha256": "asset"}}
            config = {"frames": [{"frame": 1, "capture": True, "sampling_frame": 1}]}
            attempt = root / "formal/cornell-static/combined/neighbors-4/seed-1/off/attempt-0"
            attempt.mkdir(parents=True)
            (attempt / "config.json").write_text(json.dumps(config))
            image = attempt / "frame-0001.pfm.gz"
            write_pfm(image, np.ones((1, 2, 3)))
            captures = [{"frame": 1, "image_sha256": module.sha(image)}]
            (attempt / "captures.json").write_text(json.dumps(captures))
            record = {"status": "completed", "config_sha256": module.sha(attempt / "config.json"),
                "build": instance.build, "scene": {"sha256": "asset"}, "captures": captures}
            (attempt / "manifest.json").write_text(json.dumps(record))
            class Expired:
                def check(self):
                    raise BudgetExceeded("expired")
                def timeout(self, value):
                    raise BudgetExceeded("expired")
            instance.budget = Expired()
            original = image.read_bytes()
            with patch.object(module, "build_config", return_value=config):
                self.assertEqual(instance.render(condition, 1, False), attempt)
                self.assertEqual(image.read_bytes(), original)
                record["build"] = {"pdf": "changed"}
                (attempt / "manifest.json").write_text(json.dumps(record))
                with self.assertRaisesRegex(ValueError, "different build"):
                    instance.render(condition, 1, False)
                with self.assertRaises(BudgetExceeded):
                    instance.render(condition, 2, False)
            self.assertFalse((root / "formal/cornell-static/combined/neighbors-4/seed-2/off").exists())


if __name__ == "__main__":
    unittest.main()
