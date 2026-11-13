"""Bounded Falcor CGNS PT smoke graph and camera contracts."""
import importlib
import importlib.util
import unittest
import hashlib
import tempfile
from pathlib import Path


class FalcorCgnsPtSmokeTests(unittest.TestCase):
    def module(self):
        name = "scripts.falcor.cgns_pt_smoke"
        self.assertIsNotNone(importlib.util.find_spec(name), "Falcor CGNS smoke runner missing")
        return importlib.import_module(name)

    def test_modes_use_same_spatial_only_reuse_settings(self):
        m = self.module()
        baseline = m.graph_options("baseline")
        cgns = m.graph_options("cgns")
        self.assertEqual(baseline, cgns)
        self.assertTrue(baseline["useReSTIRPT"])
        self.assertEqual(baseline["sampleGenerator"], 0, "ReSTIR PT replay requires TinyUniform 32-bit state")
        opts = baseline["reSTIRPathTracingOptions"]
        self.assertEqual(opts["spatialNeighborCount"], 4)
        self.assertEqual(opts["spatialGatherRadius"], 32)
        self.assertEqual(opts["spatialIterations"], 1)
        self.assertTrue(opts["useSpatialResampling"])
        self.assertFalse(opts["useAreaReservoirs"])
        self.assertFalse(opts["useTemporalResampling"])
        self.assertFalse(opts["usePairedNeighbors"])
        self.assertFalse(opts["useDoFReconnectionShift"])
        self.assertFalse(opts["useDoFReconnectionForTemporalReuse"])
        self.assertFalse(opts["deriveDoFReconnectionShiftProbabilityFromCoC"])

    def test_resolved_graph_requires_exact_requested_values(self):
        m = self.module()
        options = m.graph_options("baseline")
        resolved = "g.create_pass('PathTracer','PathTracer'," + repr(options) + ")"
        m.validate_resolved_graph(resolved, options)
        wrong = dict(options)
        wrong["reSTIRPathTracingOptions"] = dict(options["reSTIRPathTracingOptions"], spatialGatherRadius=33)
        with self.assertRaises(ValueError):
            m.validate_resolved_graph("g.create_pass('PathTracer','PathTracer'," + repr(wrong) + ")", options)
        with self.assertRaises(ValueError): m.validate_resolved_graph("pass", options)

    def test_runtime_inventory_rejects_missing_modified_and_unknown_files(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "shader.slang").write_bytes(b"correct")
            expected = {"shader.slang": hashlib.sha256(b"correct").hexdigest()}
            m.validate_runtime_inventory(root, expected)
            (root / "shader.slang").write_bytes(b"incorrect")
            with self.assertRaises(ValueError): m.validate_runtime_inventory(root, expected)
            (root / "shader.slang").write_bytes(b"correct")
            (root / "surprise.dll").write_bytes(b"extra")
            with self.assertRaises(ValueError): m.validate_runtime_inventory(root, expected)
            (root / "surprise.dll").unlink()
            (root / "shader.slang").unlink()
            with self.assertRaises(ValueError): m.validate_runtime_inventory(root, expected)

    def test_budget_is_bounded_and_rejects_unknown_modes(self):
        m = self.module()
        for w, h, frames in [(0, 64, 1), (641, 64, 1), (64, 361, 1), (64, 64, 17)]:
            with self.assertRaises(ValueError): m.validate_budget(w, h, frames)
        m.validate_budget(320, 180, 4)
        with self.assertRaises(ValueError): m.graph_options("unknown")

    def test_embedded_script_preserves_reference_camera_and_captures_last_frame(self):
        m = self.module()
        camera = {"position": [1, 2, 3], "direction": [0, 0, -1], "up": [0, 1, 0], "vertical_fov": 40}
        script = m.render_script(Path("scene.pyscene"), camera, Path("output"), 4, "baseline")
        self.assertIn("camera.position = float3(*[1, 2, 3])", script)
        self.assertIn("camera.target = float3(*[1.0, 2.0, 2.0])", script)
        self.assertIn("m.scene.animated = False", script)
        self.assertIn("useDOF", script)
        self.assertIn("m.frameCapture.capture()", script)
        self.assertIn("range(1, 5)", script)
        self.assertIn("resolved-camera.json", script)


if __name__ == "__main__": unittest.main()
