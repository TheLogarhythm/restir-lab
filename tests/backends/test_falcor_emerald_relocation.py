"""Renaming the frozen Emerald scene must preserve its recorded contents."""
import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.falcor import cgns_pt_six_view_smoke as six


class EmeraldSceneRelocationTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reference = self.root / 'runs/falcor-pt-spatial-comparison'
        self.relocations = self.reference / 'provenance/relocations'
        self.relocations.mkdir(parents=True)
        self.old_name = 'scenes/configs/falcor/emerald-square-converted-scout.pyscene'
        self.new_name = 'scenes/configs/falcor/emerald-square-converted-reference.pyscene'
        self.config = self.root / 'experiments/configs/falcor-pt-spatial-comparison/emerald-square-reference.json'
        self.config.parent.mkdir(parents=True)
        self.old_config = self.relocations / 'emerald-square-reference-before-rename.json'
        self.old_scene = self.relocations / 'emerald-square-converted-scout.pyscene'
        self.new_scene = self.root / self.new_name
        self.new_scene.parent.mkdir(parents=True)
        self.old_scene.write_bytes(b'# pinned original Emerald scene\n')
        self.new_scene.write_bytes(self.old_scene.read_bytes())
        original = {'scene_id':'emerald-square', 'view_id':'view-a',
                    'scene_source':self.old_name, 'asset_roots':[self.old_name, 'assets/emerald'],
                    'camera':{'x':7}}
        self.old_config.write_text(json.dumps(original,indent=2),encoding='utf8')
        self.config.write_bytes(self.old_config.read_bytes().replace(self.old_name.encode(),self.new_name.encode()))
        self.entry = {'scene_id':'emerald-square', 'view_id':'view-a', 'adapted':False,
                      'config_path':str(self.config), 'config_sha256':self.sha(self.old_config),
                      'asset_sha256':{self.old_name:self.sha(self.old_scene),'assets/emerald/model':'a'*64},
                      'source_sha256':{}}
        self.patchers = [patch.object(six,'ROOT',self.root), patch.object(six,'REFERENCE',self.reference)]
        for p in self.patchers:
            p.start(); self.addCleanup(p.stop)

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_mapping_is_exact_and_does_not_modify_historical_entry(self):
        original=copy.deepcopy(self.entry)
        result=six._relocated_emerald_entry(self.entry)
        self.assertEqual(self.entry,original)
        self.assertEqual(Path(result['config_path']),self.config.resolve())
        self.assertEqual(result['config_sha256'],self.sha(self.config))
        self.assertEqual(result['asset_sha256'][self.new_name],self.sha(self.new_scene))
        self.assertNotIn(self.old_name,result['asset_sha256'])
        self.assertEqual(result['asset_sha256']['assets/emerald/model'],'a'*64)

    def test_rejects_non_path_config_changes_and_tampered_scene(self):
        original=self.config.read_bytes()
        self.config.write_bytes(original.replace(b'"x": 7',b'"x": 8'))
        with self.assertRaisesRegex(ValueError,'Emerald'):
            six._relocated_emerald_entry(self.entry)
        self.config.write_bytes(original)
        self.new_scene.write_bytes(b'changed scene')
        with self.assertRaisesRegex(ValueError,'Emerald'):
            six._relocated_emerald_entry(self.entry)

    def test_rejects_missing_or_tampered_historical_snapshots(self):
        config=self.old_config.read_bytes()
        self.old_scene.write_bytes(b'changed historical scene')
        with self.assertRaisesRegex(ValueError,'Emerald'):
            six._relocated_emerald_entry(self.entry)
        self.old_scene.write_bytes(self.new_scene.read_bytes())
        self.old_config.write_bytes(b'changed historical config')
        with self.assertRaisesRegex(ValueError,'Emerald'):
            six._relocated_emerald_entry(self.entry)
        self.old_config.write_bytes(config)
        self.new_scene.unlink()
        with self.assertRaisesRegex(ValueError,'Emerald'):
            six._relocated_emerald_entry(self.entry)

    def test_frozen_view_activates_rename_without_rewriting_baseline(self):
        history=self.reference/'provenance/original/reference';history.mkdir(parents=True)
        old_index=history/'old-manifest.json';old_index.write_bytes(b'old index')
        baseline=history/'baseline.json';baseline.write_text(json.dumps({'views':[self.entry]}),encoding='utf8')
        original=baseline.read_bytes()
        extension=history/'extension-manifest.json';extension.write_text(json.dumps({
            'status':'completed','baseline_sha256':self.sha(baseline),'old_manifest_sha256':self.sha(old_index)}),encoding='utf8')
        (self.reference/'manifest.json').write_text(json.dumps({'kind':'falcor_pt_spatial_view_catalog'}),encoding='utf8')
        with patch.object(six,'KEYS',{('emerald-square','view-a')}):
            entry=six._relocated_emerald_entry(six.historical_frozen_views()[('emerald-square','view-a')])
            self.assertEqual(entry['config_sha256'],self.sha(self.config))
            self.assertEqual(json.loads(self.config.read_text())['scene_source'],self.new_name)
            self.assertEqual(baseline.read_bytes(),original)

