"""References must share material/light interpretation with every baseline run."""
import copy
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))
sys.path.insert(0, str(ROOT))
from build_fixtures import lighting_build
from experiment.artifacts import save_json
from experiment.config import make_config, load_definition
from experiment.reference import CONVERGENCE_METRIC, REFERENCE_SCHEMA_VERSION, target
from experiment.scenes import load_scene
from rtxdi_common import sha


class ReferenceCompatibilityTests(unittest.TestCase):
    def test_analysis_rejects_different_or_missing_lighting_provenance(self):
        report = importlib.import_module("scripts.analysis.di_reuse")
        for change in ("emission", "importer", "donut", "builder", "missing", "none"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                baseline, reference = lighting_build(), lighting_build()
                # Executables and reference-only shaders legitimately differ.
                reference.update(executable_sha256="reference-exe", shader_sha256={"shader": "reference"})
                reference["integration_sha256"]["scripts/run/rtxdi_experiments/ReferenceSamples.hlsl"] = "reference"
                if change in ("emission", "builder"):
                    name = "rtxdi_emission.py" if change == "emission" else "build_rtxdi_experiments.py"
                    reference["integration_sha256"]["scripts/run/" + name] = "changed"
                elif change == "importer":
                    reference["donut"]["source_sha256"]["src/engine/GltfImporter.cpp"] = "changed"
                elif change == "donut":
                    reference["donut"]["commit"] = "changed"
                elif change == "missing":
                    baseline.pop("donut")
                image, checks = root / "image.pfm.gz", root / "convergence.json"
                image.write_bytes(b"checked independently; decoding is not needed for compatibility")
                save_json(checks, {"schema_version": REFERENCE_SCHEMA_VERSION,
                    "convergence_metric": CONVERGENCE_METRIC, "converged": True})
                item = {"target": {"scene": "unchanged"}, "image": image.name, "image_sha256": sha(image),
                        "convergence": checks.name, "convergence_sha256": sha(checks), "converged": True}
                index = root / "reference-index.json"
                save_json(index, {"schema_version": REFERENCE_SCHEMA_VERSION, "convergence_metric": CONVERGENCE_METRIC,
                                  "build": reference, "references": {"pose": item}})
                captures = [{"key": "pose", "target": item["target"], "manifest": {"build": baseline}}]
                if change == "none":
                    self.assertEqual(set(report.load_references(index, root, captures)), {"pose"})
                else:
                    with self.assertRaisesRegex(ValueError, "lighting"):
                        report.load_references(index, root, captures)

    def test_generation_checks_every_baseline_before_creating_output(self):
        import rtxdi_reference as cli
        config = make_config(load_scene("cornell-box"), load_definition(), "initial", "static", resolution=[2, 2])
        baseline = lighting_build()
        baseline["renderer_commit"] = config["definition"]["renderer_commit"]
        reference = copy.deepcopy(baseline)
        reference["integration_sha256"]["scripts/run/rtxdi_emission.py"] = "changed"
        value = target(config, config["frames"][0], "assets")
        good = {"key": "pose", "target": value, "config": config, "frame": config["frames"][0],
                "manifest": {"scene": {"registry": {}}, "build": reference}}
        incompatible = {**good, "manifest": {"scene": {"registry": {}}, "build": baseline}}
        with tempfile.TemporaryDirectory() as folder:
            root, output = Path(folder), Path(folder) / "reference"
            with patch.object(sys, "argv", ["reference", "--baseline", str(root)]), \
                 patch.object(cli, "suite_captures", return_value=[good, incompatible]), \
                 patch.object(cli, "validate_assets", return_value={"sha256": "assets"}), \
                 patch.object(cli, "output_directory", return_value=output), \
                 patch.object(cli, "preflight", return_value=reference), \
                 patch.object(cli, "run_pose", side_effect=AssertionError("Incompatible baseline reached rendering")):
                with self.assertRaisesRegex(ValueError, "lighting"):
                    cli.main()
            self.assertFalse(output.exists())
