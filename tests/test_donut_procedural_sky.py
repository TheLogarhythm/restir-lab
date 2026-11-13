import numpy as np
import unittest
from scripts.falcor.donut_procedural_sky import direction_from_uv, evaluate_sky, generate_image


class ProceduralSkyTests(unittest.TestCase):
    def test_equirectangular_axes_match_falcor(self):
        actual = direction_from_uv(np.array([0., .25, .5, .75]), np.full(4, .5))
        np.testing.assert_allclose(actual, [[0,0,1],[-1,0,0],[0,0,-1],[1,0,0]], atol=1e-14)


    def test_environment_default_colors_without_sun(self):
        dirs = np.array([[0,1,0],[0,-1,0],[0,0,1]])
        actual = evaluate_sky(dirs, [0,0,-1], sun_irradiance=0, pixel_angle=0.01)
        np.testing.assert_allclose(actual, np.array([[.17,.37,.65],[.62,.59,.55],[.5,.7,.92]])*.1, atol=1e-12)


    def test_sun_center_and_invalid_input(self):
        actual = evaluate_sky(np.array([[0,1,0]]), [0,1,0], sun_irradiance=1, pixel_angle=.001)
        np.testing.assert_allclose(actual, np.array([[100.017,100.037,100.065]]), atol=1e-10)
        with self.assertRaises(ValueError):
            evaluate_sky(np.array([[0,1,0]]), [0,0,0], pixel_angle=.01)


    def test_generated_texture_is_half_quantized_and_finite(self):
        image = generate_image(64,32, [0,1,0], sun_irradiance=1)
        assert image.shape == (32,64,3) and image.dtype == np.float32
        assert np.isfinite(image).all()
        np.testing.assert_array_equal(image, image.astype(np.float16).astype(np.float32))


if __name__ == '__main__': unittest.main()
