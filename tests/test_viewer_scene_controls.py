"""Viewer transport controls do not change controlled experiment defaults."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/run"))
from experiment.scenes import load_scene
from rtxdi_pdf_viewer import viewer_config


class ViewerSceneControlTests(unittest.TestCase):
    def test_path_traced_preview_can_enable_existing_denoiser(self):
        config = viewer_config(load_scene("cornell-box"), "combined", [640, 360], indirect="RESTIRPT", denoise=True)
        self.assertEqual(config["arguments"]["lighting.indirectMode"], "RESTIRPT")
        self.assertEqual(config["arguments"]["denoiser.mode"], "NRD_RELAX")
        self.assertEqual(config["arguments"]["postProcessing.aaMode"], "TAA")

    def test_default_remains_direct_only(self):
        config = viewer_config(load_scene("cornell-box"), "combined", [640, 360])
        self.assertEqual(config["arguments"]["lighting.indirectMode"], "NONE")
        self.assertEqual(config["arguments"]["denoiser.mode"], "OFF")
