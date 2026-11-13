"""Locations of pinned material sources for explicit Falcor source checks."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHADERS = ROOT / 'renderers/falcor/upstream/Source/Falcor'
PATHS = {
    'standard': 'Rendering/Materials/StandardMaterial.slang',
    'system': 'Scene/Material/MaterialSystem.slang',
    'finalize': 'Scene/Lights/FinalizeIntegration.cs.slang',
}
