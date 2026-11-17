"""All compact PT verifiers reject ambiguous saved JSON and unsafe paths."""
import json
import subprocess
from pathlib import Path
import tempfile
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from scripts.analysis import pt_stage_archive, pt_trajectory_archive
from scripts.check_archive_references import check, contained
from records.validation import read_json


class ArchiveIOTests(unittest.TestCase):
    def test_legacy_read_helpers_keep_array_and_bom_support(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timings.json"
            path.write_text(json.dumps([{"gpu_measured_frame": 41}]), encoding="utf-8-sig")
            for reader in (pt_stage_archive.read, pt_trajectory_archive.read):
                with self.subTest(reader=reader.__module__):
                    self.assertEqual(reader(path), [{"gpu_measured_frame": 41}])
            # Run-format records still require objects, even though archive timing uses arrays.
            with self.assertRaisesRegex(ValueError, "Expected a JSON object"):
                read_json(path)

    def test_legacy_read_helpers_reject_ambiguous_or_nonfinite_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            for reader in (pt_stage_archive.read, pt_trajectory_archive.read):
                for payload, message in (
                    ('{"kind":"original","kind":"changed"}', "Duplicate JSON key"),
                    ('[{"gpu_ms":NaN}]', "Nonfinite JSON"),
                    ('{"gpu_ms":Infinity}', "Nonfinite JSON"),
                    ('{"gpu_ms":', "Expecting value"),
                ):
                    with self.subTest(reader=reader.__module__, payload=payload):
                        path.write_text(payload, encoding="utf-8")
                        with self.assertRaisesRegex(ValueError, message):
                            reader(path)

    def test_legacy_path_helpers_reject_portable_escaping_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "kept").mkdir()
            for helper in (pt_stage_archive.child, pt_trajectory_archive.child, contained):
                self.assertEqual(helper(root, "kept"), root / "kept")
                for relative in ("../outside", "..\\outside", "C:outside", "C:/outside", "/outside", "\\outside", ""):
                    with self.subTest(helper=helper.__module__, relative=relative):
                        with self.assertRaisesRegex(ValueError, "contained relative path"):
                            helper(root, relative)

    def test_current_reference_manifest_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "results").mkdir()
            (root / "results/index.csv").write_text("experiment_id,run_id\n")
            archive = root / "runs/pt-6-views-spatial-compare"
            archive.mkdir(parents=True)
            (archive / "manifest.json").write_text(
                '{"kind":"falcor_pt_statistics_archive","kind":"falcor_pt_statistics_archive"}'
            )
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key: kind"):
                check(root)

    def test_metadata_clis_work_without_optional_analysis_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "results").mkdir()
            (root / "results/index.csv").write_text("experiment_id,run_id\n")
            commands = (
                [str(ROOT / "scripts/check_archive_references.py"), "--workspace", str(root)],
                [str(ROOT / "scripts/analysis/pt_stage_archive.py"), "--help"],
                [str(ROOT / "scripts/analysis/pt_trajectory_archive.py"), "--help"],
            )
            for command in commands:
                with self.subTest(command=command[0]):
                    result = subprocess.run(
                        [sys.executable, "-B", "-S", *command],
                        capture_output=True, text=True, check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
