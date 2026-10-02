"""Shader selection follows active output links, not node collection order."""
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/assets"))
from material_graph import surface_shaders


def socket(*nodes):
    return NS(type="SHADER", links=[NS(from_node=n) for n in nodes])


def material(*nodes, surface):
    output = NS(type="OUTPUT_MATERIAL", is_active_output=True,
                inputs={"Surface": socket(surface)})
    return NS(name="fixture", node_tree=NS(nodes=[*nodes, output]))


class MaterialGraphTests(unittest.TestCase):
    def test_disconnected_emission_is_ignored(self):
        emission = NS(type="EMISSION", inputs={})
        diffuse = NS(type="BSDF_DIFFUSE", inputs={})
        self.assertEqual(surface_shaders(material(emission, diffuse, surface=diffuse)), [diffuse])

    def test_connected_mixture_only_contains_reachable_shaders(self):
        emission = NS(type="EMISSION", inputs={})
        diffuse = NS(type="BSDF_DIFFUSE", inputs={})
        glossy = NS(type="BSDF_GLOSSY", inputs={})
        mix = NS(type="MIX_SHADER", inputs={"a": socket(diffuse), "b": socket(glossy)})
        self.assertEqual(surface_shaders(material(emission, diffuse, glossy, mix, surface=mix)),
                         [diffuse, glossy])

    def test_unsupported_group_fails_explicitly(self):
        group = NS(type="GROUP", inputs={})
        with self.assertRaisesRegex(ValueError, "GROUP"):
            surface_shaders(material(group, surface=group))
