"""Current slide media is verified through its own receipts, never the legacy media index."""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / 'writing/final/tools'
sys.path.insert(0, str(TOOLS))


def load_media():
    import presentation_media
    return presentation_media


class CurrentMediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.root = self.repo / 'writing/final'
        for folder in ('source', 'data', 'assets/videos', 'tools'):
            (self.root / folder).mkdir(parents=True)
        self.main = self.root / 'source/final.md'
        self.main.write_text('---\nmarp: true\n---\n# Intro\n\n---\n<video poster="../assets/videos/clip.png" src="../assets/videos/clip.mp4"></video>\n', encoding='utf-8')
        (self.root / 'source/appendix.md').write_text('---\nmarp: true\n---\n# Appendix\n', encoding='utf-8')
        (self.root / 'assets/videos/clip.mp4').write_bytes(b'approved encoded bytes')
        (self.root / 'assets/videos/clip.png').write_bytes(b'approved poster bytes')
        (self.root / 'assets/videos/clip.ass').write_bytes(b'approved overlays')
        import hashlib
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        output = 'writing/final/assets/videos/clip.mp4'
        self.receipt = {
            'scene': 'fixture', 'output': output,
            'output_sha256': sha(self.repo / output),
            'poster': 'writing/final/assets/videos/clip.png',
            'poster_sha256': sha(self.root / 'assets/videos/clip.png'),
            'ass_sha256': sha(self.root / 'assets/videos/clip.ass'),
            'probe': {'width': 1920, 'height': 1080, 'r_frame_rate': '30/1',
                      'avg_frame_rate': '30/1', 'nb_read_frames': '300',
                      'duration': '10.000000', 'codec_name': 'h264', 'pix_fmt': 'yuv420p'},
            'decode': {'command': ['ffmpeg', '-hide_banner', '-v', 'error', '-nostdin', '-xerror',
                                   '-err_detect', 'explode', '-i', output, '-map', '0:v:0', '-an', '-f', 'null', '-'],
                       'exit_code': 0, 'stderr': '', 'all_frames_decoded': True},
            'sources': [], 'command': ['ffmpeg', '-i', 'input', output], 'layout': {'background': 'white'},
        }
        self.receipt_path = self.root / 'data/clip.json'
        self.receipt_path.write_text(json.dumps(self.receipt), encoding='utf-8')

    def index(self):
        media = load_media()
        index = media.create_index(self.root, repo=self.repo)
        (self.root / 'data/current-media.json').write_text(json.dumps(index), encoding='utf-8')
        return index

    def test_current_slide_reference_selects_receipt_and_pptx_position(self):
        self.index()
        media = load_media()
        result = media.presentation_inputs(self.root, repo=self.repo)
        self.assertEqual(result['slides'], 2)
        self.assertEqual([(v['slide'], Path(v['path']).name) for v in result['videos']], [(2, 'clip.mp4')])

    def test_changed_source_video_cannot_pass_using_old_media_index(self):
        self.index()
        self.main.write_text(self.main.read_text().replace('clip.mp4', 'other.mp4'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'source|reference'):
            load_media().load_current_media(self.root, repo=self.repo)

    def test_tampered_receipt_cannot_reuse_output_verification(self):
        self.index()
        self.receipt['decode']['all_frames_decoded'] = False
        self.receipt_path.write_text(json.dumps(self.receipt), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'receipt|hash'):
            load_media().load_current_media(self.root, repo=self.repo)

    def test_success_receipt_for_another_clip_is_rejected_on_adoption(self):
        self.receipt['decode']['command'][9] = 'writing/final/assets/videos/other.mp4'
        self.receipt_path.write_text(json.dumps(self.receipt), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'decode|input'):
            load_media().create_index(self.root, repo=self.repo)

    def test_missing_current_clip_is_rejected(self):
        self.index()
        (self.root / 'assets/videos/clip.mp4').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing|missing'):
            load_media().load_current_media(self.root, repo=self.repo)

    def test_portable_current_validation_needs_no_original_video_or_overlay(self):
        self.receipt['sources'] = [{'manifest': {'path': 'runs/not-shipped/manifest.json', 'sha256': 'a' * 64},
                                   'artifacts': {'video.mp4': {'path': 'runs/not-shipped/video.mp4', 'sha256': 'b' * 64}}}]
        self.receipt_path.write_text(json.dumps(self.receipt), encoding='utf-8')
        self.index()
        (self.root / 'assets/videos/clip.ass').unlink()
        inputs = load_media().presentation_inputs(self.root, repo=self.repo)
        self.assertEqual(inputs['videos'][0]['slide'], 2)
        self.assertEqual(Path(inputs['videos'][0]['path']).read_bytes(), b'approved encoded bytes')

    def test_bad_probe_and_decode_status_are_rejected(self):
        for field, value in [('nb_read_frames', '299'), ('duration', '9.0')]:
            with self.subTest(field=field):
                old = self.receipt['probe'][field]
                self.receipt['probe'][field] = value
                self.receipt_path.write_text(json.dumps(self.receipt), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'probe|format'):
                    load_media().create_index(self.root, repo=self.repo)
                self.receipt['probe'][field] = old
        self.receipt['decode']['exit_code'] = 1
        self.receipt_path.write_text(json.dumps(self.receipt), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'decode'):
            load_media().create_index(self.root, repo=self.repo)

    def test_cache_rejects_recipe_changes_but_keeps_identical_outputs(self):
        media = load_media()
        index = self.index()
        entry = index['entries'][0]
        identity = {'sources': ['sha256:a'], 'recipe': 'course-v2', 'scripts': {'builder': 'sha256:1'}}
        entry['build_identity'] = identity
        self.assertTrue(media.reusable(entry, identity, self.root))
        self.assertFalse(media.reusable(entry, {**identity, 'scripts': {'builder': 'sha256:2'}}, self.root))
        (self.root / 'assets/videos/clip.mp4').write_bytes(b'changed')
        self.assertFalse(media.reusable(entry, identity, self.root))

    def test_builder_import_is_safe_and_compatibility_cli_uses_current_index(self):
        # Exercise the real CLI in a portable checkout containing only fixture
        # assets and receipts; no ignored production/current repository media.
        self.index()
        fixture_tools = self.root / 'tools'
        for name in ('build_media.py', 'build_media_course.py', 'presentation_media.py'):
            shutil.copyfile(TOOLS / name, fixture_tools / name)
        result = subprocess.run([sys.executable, '-B', '-c',
            'import sys; sys.path.insert(0, sys.argv[1]); import build_media_course; print("safe import")', str(fixture_tools)],
            capture_output=True, text=True, cwd=self.repo)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, 'safe import'), result.stderr)
        result = subprocess.run([sys.executable, '-B', str(fixture_tools / 'build_media_course.py'), '--describe'],
                                capture_output=True, text=True, cwd=self.repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        inputs = json.loads(result.stdout)
        self.assertEqual(inputs['slides'], 2)
        self.assertEqual([(video['deck'], video['slide'], Path(video['path']).name)
                          for video in inputs['videos']], [('final', 2, 'clip.mp4')])
        self.assertEqual(Path(inputs['videos'][0]['path']).read_bytes(), b'approved encoded bytes')


if __name__ == '__main__':
    unittest.main()