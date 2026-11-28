"""Presentation maintenance keeps editable prose and package boundaries intact."""
import csv
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / 'writing/final/tools'


def module(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / (name + '.py'))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class PresentationBuildTests(unittest.TestCase):
    def test_importing_build_helpers_does_not_write_or_parse_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            script = "import importlib.util,sys\nsys.argv=['helper','--unexpected-import-argument']\n"
            for name in ('build_appendix', 'package_handoff'):
                script += (f"s=importlib.util.spec_from_file_location('{name}',{str(TOOLS / (name+'.py'))!r})\n"
                           "m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n")
            result = subprocess.run([sys.executable, '-B', '-c', script], cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_table_refresh_preserves_handwritten_appendix_and_is_idempotent(self):
        update = module('build_appendix')
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            root = repo / 'writing/final'
            (root / 'source').mkdir(parents=True)
            summary_dir = repo / 'results/summaries/falcor-pt-spatial-reuse'
            summary_dir.mkdir(parents=True)
            with (summary_dir / 'summary.csv').open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['view','method','smape_percent','smape_seed_sd'])
                writer.writeheader()
                for view in ('bistro-interior','bistro-exterior','classroom','emerald-square','veach-ajar','zero-day-measure-seven'):
                    for method in ('temporal-on','pdf','cgns'):
                        writer.writerow(dict(view=view, method=method, smape_percent=12.5, smape_seed_sd=.2))
            path = root / 'source/appendix.md'
            path.write_text('Preserve this introduction.\n<table><tr><td>Old data</td></tr></table>\nPreserve this conclusion.')
            self.assertTrue(update.refresh_table(root))
            text = path.read_text()
            self.assertTrue(text.startswith('Preserve this introduction.\n'))
            self.assertTrue(text.endswith('\nPreserve this conclusion.'))
            self.assertIn('Bistro Interior', text)
            self.assertFalse(update.refresh_table(root))
            path.write_text('An appendix without a table.')
            with self.assertRaisesRegex(ValueError, 'one appendix'):
                update.refresh_table(root)
            self.assertEqual(path.read_text(), 'An appendix without a table.')

    def test_packaged_verifier_accepts_exact_zip_and_rejects_tampering(self):
        packing = module('package_handoff')
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / 'sample';base.mkdir()
            (base / 'payload.txt').write_text('Frozen result')
            (base / 'tools').mkdir()
            shutil.copyfile(REPO / 'writing/final/templates/handoff/verify_handoff.py', base / 'tools/verify_handoff.py')
            packing.write_checksums(base)
            target = Path(directory) / 'sample.zip'
            packing.zip_bundle(base, target)
            with self.assertRaises(FileExistsError):packing.zip_bundle(base, target)
            extracted = Path(directory) / 'extracted'
            with zipfile.ZipFile(target) as archive:archive.extractall(extracted)
            command = [sys.executable, '-B', str(extracted / 'sample/tools/verify_handoff.py')]
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            (extracted / 'sample/payload.txt').write_text('Changed result')
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)

    def test_complete_handoff_keeps_current_media_dependencies_and_shared_builder(self):
        packing = module('package_handoff')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'repo'
            final = root / 'writing/final'
            def put(relative, content=b'fixture'):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                return path
            for name in ('final', 'appendix'):
                put(f'writing/final/source/{name}.md', b'<video src="../assets/videos/current.mp4" poster="../assets/videos/current.png"></video>')
                put(f'writing/final/{name}.html')
            for ext in ('mp4', 'png', 'ass'):
                put('writing/final/assets/videos/current.' + ext)
            put('writing/final/assets/videos/obsolete.mp4')
            put('writing/final/build/media-receipts/current.json', b'{}')
            put('writing/final/data/current-media.json', json.dumps({'entries': [{
                'receipt': {'path': 'build/media-receipts/current.json'},
                'overlays': {'path': 'assets/videos/current.ass'},
            }]}).encode())
            put('writing/final/README.md')
            for name in ('final.pdf', 'appendix.pdf', 'final-notes.txt', 'rehearsal-script.md', 'final-with-videos.pptx'):
                put('writing/final/build/' + name)
            put('writing/final/tools/build.ps1', (TOOLS / 'build.ps1').read_bytes())
            shutil.copytree(REPO / 'writing/final/templates', final / 'templates')
            put('runs/pt-6-views-spatial-compare/manifest.json', b'{}')
            put('runs/pt-6-views-spatial-compare/records/record.json', b'{}')
            for index in range(12):
                put(f'runs/pt-4-trajectories-spatial-compare/video-{index}.mp4')
            for name in ('2020-spatiotemporal-reservoir-resampling-for-direct-lighting.pdf',
                         '2022-generalized-resampled-importance-sampling.pdf',
                         '2023-efficient-spatial-resampling-using-pdf-similarity.pdf',
                         '2026-compatibility-guided-neighbor-selection-for-restir.pdf'):
                put('assets/papers/' + name)
            run = subprocess.run
            def run_with_fake_git(command, **kwargs):
                if command[0] == 'git':
                    return subprocess.CompletedProcess(command, 0, stdout=b'fixture provenance', stderr=b'')
                return run(command, **kwargs)
            output = Path(directory) / 'handoff'
            with mock.patch.object(packing.subprocess, 'run', side_effect=run_with_fake_git):
                result = packing.package(root, output)
            self.assertTrue(result['clean_extraction_verified'])
            core = output / 'unpacked-validation/restir-final-handoff'
            self.assertEqual((core / 'writing/final/assets/videos/current.ass').read_bytes(), b'fixture')
            self.assertFalse((core / 'writing/final/assets/videos/obsolete.mp4').exists())
            self.assertEqual((core / 'writing/final/build/media-receipts/current.json').read_bytes(), b'{}')
            self.assertEqual((core / 'writing/final/tools/build.ps1').read_bytes(), (TOOLS / 'build.ps1').read_bytes())
            with zipfile.ZipFile(core / 'runs/pt-6-views-spatial-compare/records.zip') as records:
                self.assertEqual(records.read('record.json'), b'{}')
            with self.assertRaises(FileExistsError):
                packing.package(root, output)

    def test_handoff_output_cannot_modify_a_consumed_source_tree(self):
        packing = module('package_handoff')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'repo'
            root.mkdir()
            for relative in ('runs/pt-6-views-spatial-compare/new-handoff',
                             'writing/final/source/new-handoff', 'src/new-handoff'):
                output = root / relative
                with self.subTest(relative=relative):
                    with self.assertRaisesRegex(ValueError, 'source|archive'):
                        packing.package(root, output)
                    self.assertFalse(output.exists())

    def test_packaging_resolves_current_links_and_rejects_workspace_escape(self):
        packing = module('package_handoff')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'repo';src = root / 'writing/final/source';src.mkdir(parents=True)
            asset = root / 'writing/final/assets/current.mp4';asset.parent.mkdir();asset.write_bytes(b'video')
            for name in ('final', 'appendix'):(src / (name+'.md')).write_text('<video src="../assets/current.mp4"></video>')
            self.assertEqual(packing.slide_assets(root), {asset.resolve()})
            outside = Path(directory) / 'outside.mp4';outside.write_bytes(b'outside')
            (src / 'final.md').write_text('<video src="../../../../outside.mp4"></video>')
            with self.assertRaisesRegex(ValueError, 'escaping'):packing.slide_assets(root)


if __name__ == '__main__':
    unittest.main()
