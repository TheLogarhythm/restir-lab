"""Portable paths must retain strict frozen-scene validation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.falcor import reference_extension_provenance as provenance
from scripts.falcor import cgns_pt_six_view_smoke as six
from scripts.falcor import reference_extension_batch as batch


class PortableProvenanceTests(TestCase):
    def test_historical_windows_workspace_is_derived_from_baseline(self):
        record = {'old_root': r'C:\Users\Alice\project\runs\falcor-pt-spatial-comparison'}
        root = provenance.historical_workspace(record)
        self.assertEqual(str(root), r'C:\Users\Alice\project')
        self.assertEqual(provenance.workspace_relative(
            r'C:\Users\Alice\project\experiments\configs\scene.json', root),
            'experiments/configs/scene.json')
        with self.assertRaises(ValueError):
            provenance.workspace_relative(r'C:\Users\Other\project\scene.json', root)
        with self.assertRaises(ValueError):
            provenance.workspace_relative(r'C:\Users\Alice\project\..\outside', root)
        with self.assertRaises(ValueError):
            provenance.workspace_relative(r'\outside\scene.json', root)

    def test_relative_paths_never_escape_workspace(self):
        root = provenance.historical_workspace({'old_root': '/old/repo/runs/falcor-pt-spatial-comparison'})
        self.assertEqual(provenance.workspace_relative('/old/repo/scenes/file', root), 'scenes/file')
        self.assertEqual(provenance.workspace_relative('scenes/file', root), 'scenes/file')
        with self.assertRaises(ValueError): provenance.workspace_relative('../outside', root)
        with self.assertRaises(ValueError): provenance.workspace_relative('/old/other/file', root)

    def test_frozen_config_rebases_without_mutating_historical_entry(self):
        old_root = r'C:\Users\Alice\project'
        old = {'scene_id': 'classroom', 'view_id': 'view-a',
               'config_path': old_root + r'\experiments\configs\classroom.json',
               'config_sha256': 'abc'}
        before = deepcopy(old)
        with TemporaryDirectory() as directory:
            current = Path(directory).resolve()
            result = six.rebase_frozen_config(old, old_root, current)
            self.assertEqual(Path(result['config_path']), current / 'experiments/configs/classroom.json')
            self.assertEqual(old, before)
            bad = dict(old, config_path=r'C:\Users\other\config.json')
            with self.assertRaises(ValueError): six.rebase_frozen_config(bad, old_root, current)

    def test_historical_copy_receipt_rebases_to_new_workspace(self):
        old_root = r'C:\Users\Alice\project'
        receipt={'copies':[{'original':old_root+r'\scripts\source.py',
                            'preserved':old_root+r'\runs\history\source.py'}]}
        with TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            result=provenance.historical_copy_map(receipt,old_root,root)
            self.assertEqual(result['scripts/source.py'],root/'runs/history/source.py')
            receipt['copies'][0]['preserved']=r'C:\outside\source.py'
            with self.assertRaises(ValueError):provenance.historical_copy_map(receipt,old_root,root)

    def test_audit_normalizes_texture_paths_only_and_retains_other_checks(self):
        old_root = r'C:\Users\Alice\project'
        new_root = r'D:\work\project'
        old = {'models': [{'material_count': 1, 'loaded_texture_slots': [
            {'material_index': 0, 'path': old_root + r'\assets\tex.dds', 'source_sha256': 'x'}]}], 'issues': []}
        new = deepcopy(old)
        new['models'][0]['loaded_texture_slots'][0]['path'] = new_root + r'\assets\tex.dds'
        six.validate_adapted_audit(old, new, old_root=old_root, current_root=new_root)
        new['models'][0]['loaded_texture_slots'][0]['source_sha256'] = 'different'
        with self.assertRaises(ValueError): six.validate_adapted_audit(old, new, old_root=old_root, current_root=new_root)
        new = deepcopy(old)
        new['models'][0]['loaded_texture_slots'][0]['path'] = r'D:\outside\tex.dds'
        with self.assertRaises(ValueError): six.validate_adapted_audit(old, new, old_root=old_root, current_root=new_root)

    def test_portable_audit_marks_workspace_paths_and_preserves_all_other_values(self):
        root=r'C:\Users\Alice\project'
        audit={'models':[{'loaded_texture_slots':[{'path':root+r'\assets\texture.dds','sha256':'xyz'}]}]}
        original=deepcopy(audit)
        portable=six.portable_adapted_audit(audit,root)
        self.assertEqual(audit,original)
        self.assertEqual(portable['path_base'],'workspace')
        self.assertEqual(portable['models'][0]['loaded_texture_slots'][0]['path'],'assets/texture.dds')
        six.validate_adapted_audit(original,portable,old_root=root,current_root=root)
        portable['path_base']='other'
        with self.assertRaises(ValueError):six.validate_adapted_audit(original,portable,old_root=root,current_root=root)

    def test_schema_two_audit_uses_current_workspace_as_baseline(self):
        with TemporaryDirectory() as d:
            root=Path(d).resolve();baseline=root/'baseline.json'
            baseline.write_text(json.dumps({'schema_version':2,'path_base':'workspace','old_root':'runs/falcor-pt-spatial-comparison'}))
            audit={'models':[{'loaded_texture_slots':[{'path':'assets/texture.dds'}]}]}
            with patch.object(six,'ROOT',root),patch.object(six,'historical_baseline_path',return_value=baseline):
                six.validate_adapted_audit(audit,audit)

    def test_scene_json_migration_changes_only_approved_paths_and_hashes(self):
        old_root=r'C:\Users\Alice\project'
        old={'scene':{'actions':[{'source':old_root+r'\assets\model.gltf','strength':5}],
                      'dependencies':[{'path':old_root+r'\runs\sky.json','sha256':'old'}]}}
        new={'path_format':'workspace-relative-v1',
             'scene':{'actions':[{'source':'assets/model.gltf','strength':5}],
                      'dependencies':[{'path':'scenes/new-sky.json','sha256':'new'}]}}
        mapping={'runs/sky.json':{'new_path':'scenes/new-sky.json','old_sha256':'old','new_sha256':'new'}}
        provenance.validate_portable_json_semantics(old,new,old_root,mapping,marker=True)
        changed=deepcopy(new);changed['scene']['actions'][0]['strength']=6
        with self.assertRaises(ValueError):provenance.validate_portable_json_semantics(old,changed,old_root,mapping,marker=True)


class PortableBistroEntryTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.reference=self.root/'runs/falcor-pt-spatial-comparison'
        self.history=self.reference/'scene-assets/bistro/frozen-scene/scout-config.json'
        self.config=self.root/'experiments/configs/falcor-pt-spatial-comparison/bistro-interior-reference.json'
        self.receipt=self.reference/'provenance/relocations/bistro-portable-v1.json'
        self.old_root=r'C:\Users\Alice\project'
        oldpath='runs/falcor-pt-spatial-comparison/scene-assets/bistro/frozen-scene/adapted.pyscene'
        newpath='scenes/configs/falcor/bistro-gltf/adapted.pyscene'
        snapshot='runs/falcor-pt-spatial-comparison/provenance/relocations/old-adapted.pyscene'
        asset='assets/bistro/texture.dds'
        helper='scripts/falcor/project_paths.py'
        self.write(snapshot,b'old scene');self.write(newpath,b'new scene');self.write(asset,b'pixels');self.write(helper,b'path helper')
        oldscene={'path':self.old_root+'\\'+oldpath.replace('/','\\'),'sha256':self.sha(snapshot),'bytes':9}
        oldasset={'path':self.old_root+'\\'+asset.replace('/','\\'),'sha256':self.sha(asset),'kinds':['texture']}
        old={'scene_id':'bistro','view_id':'view-a','scene_source':oldscene['path'],
             'camera':{'x':7},'resources':[oldasset],'sources':[oldscene]}
        self.write(self.history.relative_to(self.root),json.dumps(old).encode())
        new={'scene_id':'bistro','view_id':'view-a','scene_source':newpath,'camera':{'x':7},
             'resources':[{'path':asset,'sha256':self.sha(asset),'kinds':['texture']}],
             'sources':[{'path':newpath,'sha256':self.sha(newpath),'bytes':9},
                        {'path':helper,'sha256':self.sha(helper),'bytes':11}]}
        self.write(self.config.relative_to(self.root),json.dumps(new).encode())
        self.entry={'scene_id':'bistro','view_id':'view-a','adapted':True,'config_sha256':self.sha(self.history.relative_to(self.root)),
                    'asset_sha256':{asset:self.sha(asset)},'source_sha256':{oldpath:self.sha(snapshot)}}
        receipt={'schema_version':1,'kind':'bistro_portable_scene_v1',
                 'historical_config_sha256':self.entry['config_sha256'],'portable_config_sha256':self.sha(self.config.relative_to(self.root)),
                 'files':[{'historical_path':oldpath,'old_path':snapshot,'old_sha256':self.sha(snapshot),
                           'new_path':newpath,'new_sha256':self.sha(newpath)}],
                 'added_sources':[{'path':helper,'sha256':self.sha(helper),'bytes':11}]}
        self.write(self.receipt.relative_to(self.root),json.dumps(receipt).encode())

    def write(self,path,data):
        path=self.root/path;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)

    def sha(self,path):
        return hashlib.sha256((self.root/path).read_bytes()).hexdigest()

    def test_rebases_only_proven_paths_and_preserves_original_entry(self):
        original=deepcopy(self.entry)
        with patch.object(provenance,'verify_bistro_migration_semantics'):
            result=provenance.portable_bistro_entry(self.entry,self.old_root,self.root,self.reference)
        self.assertEqual(self.entry,original)
        self.assertEqual(Path(result['config_path']),self.config)
        self.assertEqual(result['config_sha256'],self.sha(self.config.relative_to(self.root)))
        self.assertIn('scenes/configs/falcor/bistro-gltf/adapted.pyscene',result['source_sha256'])
        self.assertIn('scripts/falcor/project_paths.py',result['source_sha256'])

    def test_changed_camera_or_unapproved_source_is_rejected(self):
        data=json.loads(self.config.read_text());data['camera']['x']=8
        self.config.write_text(json.dumps(data),encoding='utf8')
        record=json.loads(self.receipt.read_text());record['portable_config_sha256']=self.sha(self.config.relative_to(self.root))
        self.receipt.write_text(json.dumps(record),encoding='utf8')
        with self.assertRaises(ValueError):provenance.portable_bistro_entry(self.entry,self.old_root,self.root,self.reference)

    def test_changed_historical_source_is_rejected(self):
        self.write('runs/falcor-pt-spatial-comparison/provenance/relocations/old-adapted.pyscene',b'tampered')
        with self.assertRaises(ValueError):provenance.portable_bistro_entry(self.entry,self.old_root,self.root,self.reference)

    def test_recheck_still_rejects_changed_asset_after_lightweight_catalog(self):
        self.write('scripts/falcor/reference_graph.py',b'graph')
        self.write('build/falcor-gltf-composite-runtime-v3/receipt.json',b'runtime')
        self.entry['graph_sha256']=self.sha('scripts/falcor/reference_graph.py')
        self.entry['runtime_receipt_sha256']=self.sha('build/falcor-gltf-composite-runtime-v3/receipt.json')
        config=json.loads(self.config.read_text(encoding='utf8'))
        with patch.object(provenance,'verify_bistro_migration_semantics'), \
             patch.object(provenance.adapted_reference_runner,'inventory_resources',side_effect=AssertionError('must not scan catalog')):
            entry=provenance.portable_bistro_entry(self.entry,self.old_root,self.root,self.reference)
        with patch.object(batch,'ROOT',self.root):
            batch.recheck_view(entry,config)
            self.write('assets/bistro/texture.dds',b'tampered')
            with self.assertRaises(ValueError):batch.recheck_view(entry,config)
