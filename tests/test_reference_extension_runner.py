import unittest
from pathlib import Path
from scripts.falcor.reference_extension_runner import block_seed_range, render_script


class ReferenceExtensionRunnerTests(unittest.TestCase):
    def test_block_ranges_are_disjoint_and_after_existing(self):
        assert [list(block_seed_range(i,1024)) for i in range(8)] == [list(range(8192+i*1024,8192+(i+1)*1024)) for i in range(8)]
        with self.assertRaises(ValueError): block_seed_range(8,1024)
        with self.assertRaises(ValueError): block_seed_range(0,1025)


    def test_script_per_block_reset_and_camera(self):
        camera={'position':[0,0,0],'direction':[0,0,-1],'up':[0,1,0],'vertical_fov':60,'near_plane':0.01}
        script=render_script(Path('a.pyscene'),camera,Path('out'),[1,5],4,adapted=True)
        compile(script,'render.py','exec')
        assert "SceneBuilderFlags.DontOptimizeMaterials" in script
        assert "camera.nearPlane = 0.01" in script
        assert "g['AccumulatePass'].reset()" in script
        assert '8192 + block * 1024 + sample' in script
        assert 'm.clock.frame = sample + 1' in script
        assert 'block-{:02d}' in script


    def test_invalid_blocks_rejected(self):
        camera={'position':[0,0,0],'direction':[0,0,-1],'up':[0,1,0],'vertical_fov':60}
        for blocks in ([],[1,1],[-1],[8]):
            with self.assertRaises(ValueError):render_script('s',camera,'o',blocks,4)

if __name__ == '__main__': unittest.main()
