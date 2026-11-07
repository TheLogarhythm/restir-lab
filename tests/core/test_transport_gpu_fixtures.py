"""The GPU fixture gate must reject a vacuous all-black environment result."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts/run")]
import rtxdi_transport_validate as api
from experiment.images import write_pfm


class TransportGpuFixtureGateTests(unittest.TestCase):
    def test_environment_fixture_preserves_sparse_rgb_texels(self):
        import OpenEXR
        expected = np.zeros((16, 32, 3), dtype=np.float32)
        expected[8, 16] = [16, 8, 4]
        expected[15, 31] = [.25, .5, 1]
        with tempfile.TemporaryDirectory() as temp, patch.object(api, "ROOT", Path(temp)):
            folder = Path(temp) / "fixture"
            api.plane_scene(folder, "sparse-roundtrip", environment=expected)
            with OpenEXR.File(str(folder / "environment.exr")) as image:
                np.testing.assert_array_equal(image.channels()["RGB"].pixels, expected)

    def test_sparse_environment_must_illuminate_the_receiver(self):
        base = api.resolve_configs(api.load_spec())[0]["config"]
        def black_capture(config, directory, executable, assets):
            directory.mkdir(parents=True)
            path = directory / "frame.pfm"
            write_pfm(path, np.zeros((32, 32, 3), dtype=np.float32))
            return path
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(api, "plane_scene", return_value=copy.deepcopy(base["scene"])), \
                patch.object(api, "validate_assets", return_value={}), \
                patch.object(api, "capture", side_effect=black_capture):
            with self.assertRaisesRegex(ValueError, "Sparse environment"):
                api.fixture_checks(Path(temp), ["sparse"])
