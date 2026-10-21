"""FBX compatibility is scoped and does not replace existing Blender properties."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/assets"))
from blender_fbx import legacy_light_property


class FbxCompatibilityTests(unittest.TestCase):
    def fixture(self, existing=False):
        class Settings:
            bl_rna = SimpleNamespace(properties={"cast_shadow": True} if existing else {})
        if existing:
            Settings.cast_shadow = "original"
        return SimpleNamespace(types=SimpleNamespace(CyclesLightSettings=Settings),
                               props=SimpleNamespace(BoolProperty=lambda **kw: True)), Settings

    def test_removed_property_is_only_available_inside_import(self):
        bpy, settings = self.fixture()
        with legacy_light_property(bpy) as added:
            self.assertTrue(added)
            self.assertTrue(settings.cast_shadow)
        self.assertFalse(hasattr(settings, "cast_shadow"))

    def test_existing_property_is_preserved(self):
        bpy, settings = self.fixture(True)
        with legacy_light_property(bpy) as added:
            self.assertFalse(added)
        self.assertEqual(settings.cast_shadow, "original")

    def test_import_failure_still_restores_property(self):
        bpy, settings = self.fixture()
        with self.assertRaises(RuntimeError):
            with legacy_light_property(bpy):
                raise RuntimeError("import failed")
        self.assertFalse(hasattr(settings, "cast_shadow"))
