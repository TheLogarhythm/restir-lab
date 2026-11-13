import unittest
from scripts.falcor.gltf_factor_shader_patch_v3 import patch_sources
from tests.fixtures.falcor_shaders import SHADERS, PATHS

class TransmissionTintTests(unittest.TestCase):
    def test_only_marked_metalrough_transmission_uses_base_color(self):
        sources={k:(SHADERS/p).read_text(encoding='utf8') for k,p in PATHS.items()}
        standard=patch_sources(sources)['standard']
        self.assertEqual(standard.count('if ((data.flags & (1u << 20)) != 0 && data.getShadingModel() == ShadingModel::MetalRough)'),1)
        self.assertIn('d.specularTransmission *= 1.f - d.metallic;',standard)
        self.assertIn('d.transmission = baseColor;',standard)
        self.assertIn('d.transmission = ms.sampleTexture(data.texTransmission',standard)
    def test_unexpected_source_fails_closed(self):
        sources={k:(SHADERS/p).read_text(encoding='utf8') for k,p in PATHS.items()}
        sources['standard']=sources['standard'].replace('#if defined(SCENE_DIFFUSE_ALBEDO_MULTIPLIER)','#if defined(CHANGED)')
        with self.assertRaises(ValueError):patch_sources(sources)

if __name__ == '__main__':unittest.main()
