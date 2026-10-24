"""Retired campaigns must not be silently recreated by the renderer runner."""
import importlib.util
from pathlib import Path
import json, sys, tempfile, unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/run'))
spec=importlib.util.spec_from_file_location('archive_guard_worker',ROOT/'scripts/run/rtxdi_pdf_controlled.py')
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
class ArchiveGuardTests(unittest.TestCase):
    def test_retired_campaign_is_rejected_before_source_is_recreated(self):
        with tempfile.TemporaryDirectory() as td,patch.object(worker,'ROOT',Path(td)):
            archive=Path(td)/'runs/pdf-similarity-archive';archive.mkdir(parents=True)
            (archive/'artifact-availability.json').write_text(json.dumps({'historical_root':'runs/pdf-controlled-20261018'}))
            with self.assertRaisesRegex(ValueError,'archived'):
                worker.suite_path('pdf-controlled-20261018')
            self.assertFalse((Path(td)/'runs/pdf-controlled-20261018').exists())
    def test_new_campaign_name_remains_available(self):
        with tempfile.TemporaryDirectory() as td,patch.object(worker,'ROOT',Path(td)):
            archive=Path(td)/'runs/pdf-similarity-archive';archive.mkdir(parents=True)
            (archive/'artifact-availability.json').write_text(json.dumps({'historical_root':'runs/pdf-controlled-20261018'}))
            self.assertEqual(worker.suite_path('pdf-controlled-new'),Path(td)/'runs/pdf-controlled-new')
    def test_no_archive_preserves_existing_path_behavior(self):
        with tempfile.TemporaryDirectory() as td,patch.object(worker,'ROOT',Path(td)):
            self.assertEqual(worker.suite_path('pdf-controlled-20261018'),Path(td)/'runs/pdf-controlled-20261018')
if __name__=='__main__':unittest.main()
