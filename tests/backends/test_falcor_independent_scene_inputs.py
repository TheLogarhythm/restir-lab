import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.falcor import cgns_pt_six_view_smoke as six


class IndependentSceneInputsTest(unittest.TestCase):
    def test_six_views_load_without_runs_or_reference_images(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); folder=root/'experiments/configs/falcor-pt-spatial-comparison';folder.mkdir(parents=True)
            entries=[]
            for number,key in enumerate(sorted(six.KEYS)):
                config=folder/(str(number)+'.json'); config.write_text(json.dumps({'scene_id':key[0],'view_id':key[1]}))
                digest=hashlib.sha256(config.read_bytes()).hexdigest()
                entries.append({'scene_id':key[0], 'view_id':key[1], 'config_path':config.relative_to(root).as_posix(),
                    'config_sha256':digest,'adapted':key==('bistro','view-a'), 'asset_sha256':{},'source_sha256':{},
                    'graph_sha256':'0'*64,'runtime_receipt_sha256':'1'*64})
            (folder/'scene-inputs.json').write_text(json.dumps({'schema_version':1,'kind':'falcor_scene_inputs','path_base':'workspace','views':entries}))
            with patch.object(six,'ROOT',root):
                views=six.frozen_views()
                self.assertEqual(set(views),six.KEYS)
                for entry in views.values():self.assertEqual(six.load_config(entry['config_path'])['scene_id'],entry['scene_id'])
                self.assertFalse((root/'runs').exists())
                config=Path(views[('classroom','view-a')]['config_path']);config.write_text('{}')
                with self.assertRaises(ValueError):six.frozen_views()

    def test_current_scene_state_rejects_invalid_light_and_does_not_read_history(self):
        state={'lights':[{'name':'sun','active':True,'intensity':[1,2,3]}],
               'environment_present':True,'useAnalyticLights':True,'useEnvLight':True,
               'useEmissiveLights':True,'stats':{}}
        with patch.object(six,'_reference_observations',side_effect=AssertionError('unexpected history')):
            six.validate_current_scene_state({},state)
            state['lights'][0]['intensity'][0]=float('nan')
            with self.assertRaises(ValueError):six.validate_current_scene_state({},state)
