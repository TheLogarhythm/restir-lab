import unittest
import numpy as np
from scripts.falcor import reference_extension_gallery as gallery

class PreviewTests(unittest.TestCase):
    def test_per_view_exposure_and_transform_match_prior_recipe(self):
        self.assertEqual(gallery.RECIPES[('bistro','view-a')],('aces',7.0))
        self.assertEqual(gallery.RECIPES[('emerald-square','view-a')],('reinhard',8.25))
        self.assertEqual(gallery.RECIPES[('zero-day-measure-seven','view-a')],('reinhard',6.0))
        x=np.array([[[0.0,0.1,1.0]]],dtype=np.float32)
        np.testing.assert_array_equal(gallery.display(x,'reinhard',0),np.array([[[0,85,188]]],dtype=np.uint8))
        self.assertEqual(gallery.display(x,'aces',7).dtype,np.uint8)
    def test_old_preview_difference_over_one_is_rejected(self):
        a=np.zeros((2,3,3),dtype=np.uint8);b=a.copy();b[0,0,0]=1
        self.assertEqual(gallery.preview_difference(a,b),1)
        b[0,0,0]=2
        with self.assertRaises(ValueError):gallery.preview_difference(a,b)

    def test_gallery_compares_six_views_and_is_idempotent(self):
        import hashlib,json,tempfile
        from pathlib import Path
        import OpenEXR
        from PIL import Image
        digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'old';out=root/'new';old.mkdir();out.mkdir();ov=[];nv=[]
            for (scene,view),(method,ev) in gallery.RECIPES.items():
                op=old/scene/view;npth=out/scene/view;op.mkdir(parents=True);npth.mkdir(parents=True)
                x=np.full((2,3,3),.2,dtype=np.float32);y=np.full((2,3,3),.3,dtype=np.float32)
                oe=op/'reference.exr';ne=npth/'reference-16384.exr';png=op/'preview.png'
                OpenEXR.File({}, {'RGB':x}).write(str(oe));OpenEXR.File({}, {'RGB':y}).write(str(ne));Image.fromarray(gallery.display(x,method,ev)).save(png)
                ov.append({'scene_id':scene,'view_id':view,'reference':str(oe.relative_to(old)),'reference_sha256':digest(oe),'preview':str(png.relative_to(old)),'preview_sha256':digest(png)})
                nv.append({'scene_id':scene,'view_id':view,'status':'completed','reference':str(ne.relative_to(out)),'reference_sha256':digest(ne)})
            (old/'manifest.json').write_text(json.dumps({'views':ov}));(out/'manifest.json').write_text(json.dumps({'views':nv}))
            page=gallery.create(old,out);self.assertTrue(page.is_file());self.assertEqual(page.read_text(encoding='utf-8').count('<section>'),6)
            before=page.read_bytes();gallery.create(old,out);self.assertEqual(before,page.read_bytes())
