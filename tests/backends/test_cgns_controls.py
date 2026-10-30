"""CGNS configuration and runtime confirmation must agree before accepting captures."""
import csv
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment.config import load_definition, make_config
from experiment.scenes import load_scene
from experiment.artifacts import validate_run_outputs
from experiment import runner
import rtxdi_reuse as cli
from tests.fixtures.cgns import cgns_runtime_record


class CgnsConfigTests(unittest.TestCase):
    def config(self, mode="combined", **settings):
        definition = load_definition()
        definition.update(cgns=True, **settings)
        return make_config(load_scene("cornell-box"), definition, mode, "reset")

    def test_defaults_and_explicit_settings_preserve_reset_sequence(self):
        for mode in ("spatial", "combined"):
            config = self.config(mode)
            self.assertEqual(config["definition"]["cgns_candidates"], 32)
            self.assertIs(config["definition"]["cgns_early_stopping"], True)
            self.assertEqual([f["frame"] for f in config["frames"] if f["reset"]], [1, 65])
        config = self.config(cgns_candidates=8, cgns_early_stopping=False)
        self.assertEqual(config["definition"]["cgns_candidates"], 8)
        self.assertIs(config["definition"]["cgns_early_stopping"], False)

    def test_invalid_parameter_types_and_limits_are_rejected(self):
        invalid = {
            "cgns": (1, "true", None),
            "cgns_candidates": (True, 0, 33, 4.0, "8"),
            "cgns_early_stopping": (0, "false", None),
        }
        for name, values in invalid.items():
            for value in values:
                definition = load_definition()
                definition.update(cgns=True)
                definition[name] = value
                with self.subTest(name=name, value=value), self.assertRaisesRegex(ValueError, name):
                    make_config(load_scene("cornell-box"), definition, "combined", "static")

    def test_requires_supported_neighbor_count_and_enough_candidates(self):
        for settings in ({"spatial_neighbors": 5}, {"cgns_candidates": 3}):
            with self.subTest(settings=settings), self.assertRaisesRegex(ValueError, "CGNS|cgns"):
                self.config(**settings)
        for neighbors in (1, 4):
            self.config(spatial_neighbors=neighbors, cgns_candidates=neighbors)

    def test_rejects_nonspatial_modes_and_combined_extensions(self):
        for mode in ("initial", "temporal"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "spatial"):
                self.config(mode)
        with self.assertRaisesRegex(ValueError, "PDF|pdf_similarity"):
            self.config(pdf_similarity=True)


class CgnsRuntimeTests(unittest.TestCase):
    def fixture(self, enabled=True):
        return cgns_runtime_record(enabled)

    def validate(self, config, resolved, row):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            with (output / "timings.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=row)
                writer.writeheader()
                writer.writerow(row)
            (output / "resolved.json").write_text(json.dumps(resolved))
            validate_run_outputs(output, config)

    def test_on_off_and_legacy_baseline_outputs_are_accepted(self):
        self.validate(*self.fixture())
        self.validate(*self.fixture(False))
        config, resolved, row = self.fixture(False)
        for key in ("cgns", "cgns_candidates", "cgns_early_stopping"):
            config["definition"].pop(key)
            resolved.pop(key)
        row.pop("neighbor_selection_ms")
        self.validate(config, resolved, row)

    def test_missing_malformed_or_mismatched_runtime_confirmation_is_rejected(self):
        for key, values in {
            "cgns": (None, False, 1, "true"),
            "cgns_candidates": (None, 7, 8.0, True),
            "cgns_early_stopping": (None, True, 0, "false"),
        }.items():
            for value in values:
                config, resolved, row = self.fixture()
                if value is None:
                    resolved.pop(key)
                else:
                    resolved[key] = value
                with self.subTest(key=key, value=value), self.assertRaisesRegex(RuntimeError, "CGNS"):
                    self.validate(config, resolved, row)

    def test_neighbor_pass_must_match_switch_and_fit_frame_timer(self):
        for enabled, value in ((True, None), (True, 0), (True, 5), (False, .25)):
            config, resolved, row = self.fixture(enabled)
            if value is None:
                row.pop("neighbor_selection_ms")
            else:
                row["neighbor_selection_ms"] = value
            with self.subTest(enabled=enabled, value=value), self.assertRaisesRegex(RuntimeError, "CGNS"):
                self.validate(config, resolved, row)

    def test_incompatible_build_is_rejected_before_renderer_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / "old.exe"
            exe.write_bytes(b"test executable")
            exe.with_suffix(".build.json").write_text("{}")
            with mock.patch.object(runner, "query", return_value=""):
                with self.assertRaisesRegex(RuntimeError, "CGNS"):
                    runner.preflight({"cgns": True}, exe)


class CgnsCliTests(unittest.TestCase):
    def test_cgns_routes_variant_and_limits_default_modes(self):
        for flags, enabled, modes in ((["--cgns"], True, ["spatial", "combined"]),
                                      (["--cgns-build"], False, ["initial", "temporal", "spatial", "combined"])):
            observed = []
            with tempfile.TemporaryDirectory() as folder:
                suite = Path(folder) / "suite"
                with mock.patch.object(sys, "argv", ["rtxdi_reuse", "--scene", "cornell-box", *flags]), \
                     mock.patch.object(cli, "output_directory", return_value=suite), \
                     mock.patch.object(cli, "validate_assets", return_value={"file_sha256": {}}), \
                     mock.patch.object(cli, "preflight", return_value={}), \
                     mock.patch.object(cli, "run_one", side_effect=lambda config, *a, **kw: observed.append((config, kw))), \
                     redirect_stdout(io.StringIO()):
                    cli.main()
            self.assertEqual([config["mode"] for config, _ in observed], modes)
            for config, kwargs in observed:
                self.assertEqual(config["definition"].get("cgns", False), enabled)
                self.assertEqual(kwargs["executable"].name, "FullSampleCgns.exe")

    def test_conflicting_variant_flags_fail_before_creating_output(self):
        for flags in (("--cgns", "--pdf-build"), ("--cgns-build", "--pdf-similarity"),
                      ("--cgns-build", "--pdf-build")):
            with tempfile.TemporaryDirectory() as folder:
                suite = Path(folder) / "suite"
                with mock.patch.object(sys, "argv", ["rtxdi_reuse", "--scene", "cornell-box", *flags]), \
                     mock.patch.object(cli, "output_directory", return_value=suite), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        cli.main()
                self.assertFalse(suite.exists())


if __name__ == "__main__":
    unittest.main()
