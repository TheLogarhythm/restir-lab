import unittest
from scripts.falcor.gltf_factor_shader_patch_v2 import patch_sources
from tests.fixtures.falcor_shaders import SHADERS, PATHS

class SpecGlossSamplingTests(unittest.TestCase):
    def test_real_wall_would_generate_nan_without_fix(self):
        diffuse=(.214,.061,.044); spec=.003
        lum=sum(x*y for x,y in zip(diffuse,(.2126,.7152,.0722)))
        discriminant=(spec+lum-.08)**2-.16*(.04-spec)
        self.assertLess(discriminant,0)
    def test_only_regular_marked_specgloss_uses_safe_weight(self):
        sources={k:(SHADERS/p).read_text(encoding='utf8') for k,p in PATHS.items()}
        result=patch_sources(sources)['standard']
        self.assertEqual(result.count('d.metallic = (data.flags & (1u << 20)) != 0 ? 0.f : getMetallic(d.diffuse, d.specular);'),1)
        self.assertEqual(result.count('d.metallic = getMetallic(d.diffuse, d.specular);'),1)
        self.assertIn('d.metallic = spec.b;',result)
    def test_source_mismatch_fails_closed(self):
        sources={k:(SHADERS/p).read_text(encoding='utf8') for k,p in PATHS.items()}
        sources['standard']=sources['standard'].replace('d.metallic = getMetallic(d.diffuse, d.specular);','d.metallic = 0;')
        with self.assertRaises(ValueError):patch_sources(sources)

if __name__ == '__main__':unittest.main()
