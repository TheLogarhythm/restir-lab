"""PDF provenance paths remain meaningful after moving a project checkout."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.analysis import pdf_paths


class PdfPortablePathTests(unittest.TestCase):
    def test_repo_relative_record_rebinds_to_another_workspace(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            a=root/'first';b=root/'second'
            for workspace in (a,b):
                (workspace/'runs/reference').mkdir(parents=True)
                (workspace/'runs/reference/frame.pfm').write_bytes(b'equal')
            record=pdf_paths.record_path(a/'runs/reference/frame.pfm',workspace=a)
            self.assertEqual(record,{'path':'runs/reference/frame.pfm','path_base':'repository_root'})
            self.assertEqual(pdf_paths.resolve_record(record,workspace=b),(b/'runs/reference/frame.pfm').resolve())

    def test_rejects_repo_path_traversal_absolute_and_symlink_escape(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary);workspace=root/'project';workspace.mkdir()
            outside=root/'secret';outside.write_text('external',encoding='utf8')
            for bad in ('../secret','a/../../secret',str(outside),r'C:\\elsewhere\\input'):
                with self.subTest(path=bad),self.assertRaises(ValueError):
                    pdf_paths.resolve_record({'path':bad,'path_base':'repository_root'},workspace=workspace)
            link=workspace/'link'
            try:link.symlink_to(outside)
            except (OSError,NotImplementedError):return
            with self.assertRaises(ValueError):
                pdf_paths.resolve_record({'path':'link','path_base':'repository_root'},workspace=workspace)

    def test_external_and_legacy_inputs_remain_explicit(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary);workspace=root/'project';workspace.mkdir()
            outside=root/'external.pfm';outside.write_bytes(b'outside')
            record=pdf_paths.record_path(outside,workspace=workspace)
            self.assertEqual(record,{'path':str(outside.resolve()),'path_base':'external_absolute'})
            self.assertEqual(pdf_paths.resolve_record(record,workspace=workspace),outside.resolve())
            self.assertEqual(pdf_paths.resolve_record(str(outside),workspace=workspace),outside.resolve())
            self.assertEqual(pdf_paths.resolve_record('external.pfm',workspace=workspace,legacy_base=root),outside.resolve())
            with self.assertRaises(ValueError):
                pdf_paths.resolve_record({'path':'external.pfm','path_base':'external_absolute'},workspace=workspace)

    def test_generated_artifact_summary_visual_and_equal_time_records_use_same_base(self):
        from scripts.analysis import pdf_artifacts, pdf_summary, pdf_visuals, pdf_equal_time
        from tests.workflows.test_pdf_artifacts import PdfArtifactTests, PdfSummaryTests
        from tests.fixtures.equal_time import equal_time_fixture
        with TemporaryDirectory() as temporary:
            workspace=Path(temporary);inputs=workspace/'inputs';inputs.mkdir()
            off,on,refs=PdfArtifactTests().fixture(inputs,frames=(128,))
            for directory,enabled in ((off,False),(on,True)):
                (directory/'config.json').write_text(json.dumps({'seed':1,'definition':{'pdf_similarity':enabled}}),encoding='utf8')
            with patch.object(pdf_paths,'ROOT',workspace):
                artifacts=pdf_artifacts.export_condition(workspace/'artifacts',off,on,refs,references_accepted=True,
                                                           expected_resolution=(8,4),write_videos=False)
                record=artifacts['inputs']['reference']['128']
                self.assertEqual(record['path_base'],'repository_root')
                self.assertEqual(record['path'],'inputs/refs/frame-0128.pfm.gz')
                visuals=pdf_visuals.export_raw_condition(workspace/'visuals',off,on,write_videos=False,
                                                          expected_resolution=(8,4))
                self.assertEqual(visuals['inputs']['pdf-off']['128']['path_base'],'repository_root')
                summary_inputs=workspace/'summary-inputs';summary_inputs.mkdir()
                condition=PdfSummaryTests().condition(summary_inputs)
                summary=pdf_summary.summarize_suite(workspace/'summary',[condition],references_accepted=True)
                self.assertEqual(summary['conditions'][0]['inputs']['references']['128']['path_base'],'repository_root')
                self.assertEqual(summary['conditions'][0]['inputs']['runs'][0]['path_base'],'repository_root')
                equal_input=workspace/'equal-input';equal_time_fixture(equal_input)
                equal=pdf_equal_time.analyze_equal_time(equal_input,workspace/'equal-output')
                self.assertEqual(equal['source']['directory'],'equal-input')
                self.assertEqual(equal['source']['path_base'],'repository_root')


if __name__=='__main__':unittest.main()
