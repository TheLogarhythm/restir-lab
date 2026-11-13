"""Prepared CGNS runtime safety contracts."""
import importlib
import importlib.util
import unittest
from pathlib import Path

class PreparedRuntimeTests(unittest.TestCase):
    def module(self):
        name="scripts.falcor.cgns_runtime"
        self.assertIsNotNone(importlib.util.find_spec(name), "CGNS runtime preparer missing")
        return importlib.import_module(name)

    def test_refuses_unknown_sources_and_outside_build_destinations(self):
        m=self.module()
        with self.assertRaises(ValueError): m.validate_request("unknown", m.ROOT/"build/new")
        with self.assertRaises(ValueError): m.validate_request("reference", m.ROOT/"runs/new")
        with self.assertRaises(ValueError): m.validate_request("gltf-v3", m.ROOT/"build/falcor-reference-runtime")
        for protected in ("falcor", "falcor-reference-runtime", "falcor-gltf-composite-runtime-v3"):
            with self.assertRaises(ValueError): m.validate_request("reference", m.ROOT/"build"/protected/"new-cgns-runtime")
        self.assertEqual(m.validate_request("gltf-v3", m.ROOT/"build/new-cgns-test"), (m.ROOT/"build/new-cgns-test").resolve())

if __name__ == "__main__": unittest.main()
