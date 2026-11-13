import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch
from scripts.falcor import reference_runner as ref, reference_extension_runner as extension, adapted_reference_runner as adapted

CAMERA={'position':[0,0,0],'direction':[0,0,1],'up':[0,1,0],'vertical_fov':45}

class PortableReferenceTests(unittest.TestCase):
    def test_reference_scripts_are_independent_of_workspace_root(self):
        for make in (lambda s,o:ref.render_script(s,CAMERA,o,0,2,portable=True),
                     lambda s,o:adapted.make_render_script(s,CAMERA,o,0,2,portable=True),
                     lambda s,o:extension.render_script(s,CAMERA,o,[0],2,adapted=True,portable=True)):
            scripts=[]
            for _ in range(2):
                with tempfile.TemporaryDirectory() as d:
                    root=Path(d)
                    scripts.append(make(root/'scenes'/'scene.pyscene',root/'runs'/'job'))
            self.assertEqual(scripts[0],scripts[1])
            compile(scripts[0],'render.py','exec')
            self.assertIn("str(Path('.').resolve())",scripts[0])
            self.assertNotIn(str(root),scripts[0])

    def test_manifest_command_has_workspace_relative_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);exe=root/'build'/'Mogwai.exe';script=root/'runs'/'job'/'render.py'
            with patch.object(ref,'ROOT',root):
                result=ref.portable_command([str(exe),'--script',str(script)])
            self.assertEqual(result,{'path_format':'workspace-relative-v1','command_path_base':'workspace',
                                     'command':['build/Mogwai.exe','--script','runs/job/render.py']})

    def test_audit_finalization_preserves_progress_and_checks_original_hash(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);audit=root/'scene-audit.json';progress=root/'progress.json'
            audit.write_text(json.dumps({'models':[{'loaded_texture_slots':[{'path':str(root/'asset.dds'),'sha256':'x'}]}]}))
            original=adapted.file_sha256(audit)
            progress.write_text(json.dumps({'status':'submitted','scene_audit_sha256':original,'block':0}))
            adapted.finalize_portable_audit(audit,root,[progress])
            value=json.loads(audit.read_text());record=json.loads(progress.read_text())
            self.assertEqual(value['path_base'],'workspace')
            self.assertEqual(value['models'][0]['loaded_texture_slots'][0]['path'],'asset.dds')
            self.assertEqual(record,{'status':'submitted','scene_audit_sha256':adapted.file_sha256(audit),'block':0})
            with self.assertRaises(ValueError):adapted.finalize_portable_audit(audit,root,[progress])

    def test_audit_finalization_rejects_unverified_progress_without_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);audit=root/'scene-audit.json';progress=root/'progress.json'
            audit.write_text(json.dumps({'models':[{'loaded_texture_slots':[{'path':str(root/'asset.dds')}]}]}))
            progress.write_text(json.dumps({'scene_audit_sha256':'wrong'}));before=audit.read_bytes()
            with self.assertRaises(ValueError):adapted.finalize_portable_audit(audit,root,[progress])
            self.assertEqual(audit.read_bytes(),before)

if __name__=='__main__':unittest.main()
