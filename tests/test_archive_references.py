"""Current index references are optional locally but must be valid when installed."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
from scripts.check_archive_references import check, ARCHIVES

NAME = 'pt-6-views-spatial-compare'
FIELDS = ['run_id', 'experiment_id', 'config_path', 'summary_path', 'artifact_uri']

def save_index(root, rows):
    (root/'results').mkdir(exist_ok=True)
    with (root/'results/index.csv').open('w', newline='', encoding='utf8') as stream:
        writer=csv.DictWriter(stream, fieldnames=FIELDS);writer.writeheader();writer.writerows(rows)

def fixture(root):
    archive=root/'runs'/NAME
    (archive/'data/room').mkdir(parents=True)
    (archive/'data/room/metrics.json').write_text('{}')
    (archive/'analysis-report.md').write_text('Frozen statistics')
    (root/'config.json').write_text('{}')
    (archive/'manifest.json').write_text(json.dumps({'kind':ARCHIVES[NAME][1], 'views':['room'],
        'files':[{'path':'data/room/metrics.json'}, {'path':'analysis-report.md'}]}))
    rows=[{'run_id':NAME+'/room','experiment_id':NAME,'config_path':'config.json',
           'summary_path':'runs/'+NAME+'/analysis-report.md','artifact_uri':'runs/'+NAME+'/data/room'},
          {'run_id':'old','experiment_id':'historical-retired','config_path':'missing.json',
           'summary_path':'missing.md','artifact_uri':'runs/retired'}]
    save_index(root, rows)
    return archive,rows

class ArchiveReferenceTests(unittest.TestCase):
    def test_fresh_checkout_skips_both_absent_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);save_index(root,[]);result=check(root)
            self.assertEqual(result['checked_result_rows'], {})
            self.assertEqual(set(result['skipped_absent_archives']),set(ARCHIVES))

    def test_current_paths_checked_and_unrelated_history_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root)
            self.assertEqual(check(root)['checked_result_rows'],{NAME:1})

    def test_stale_artifact_path_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,rows=fixture(root);rows[0]['artifact_uri']='runs/'+NAME+'/room';save_index(root,rows)
            with self.assertRaisesRegex(ValueError,'Missing current index target'):check(root)

    def test_empty_surviving_directory_cannot_mask_missing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,rows=fixture(root);(archive/'data/room/metrics.json').unlink()
            with self.assertRaisesRegex(ValueError,'Missing indexed artifact'):check(root)

    def test_missing_and_duplicate_rows_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,rows=fixture(root)
            for selected in (rows[1:], rows+[rows[0]]):
                save_index(root,selected)
                with self.assertRaisesRegex(ValueError,'coverage mismatch'):check(root)

    def test_escape_and_wrong_archive_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,rows=fixture(root)
            for target in ('../outside','config.json'):
                rows[0]['artifact_uri']=target;save_index(root,rows)
                with self.assertRaisesRegex(ValueError,'contained relative|outside its archive'):check(root)
