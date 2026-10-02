"""Temporary pinned-Donut adapter for KHR_materials_emissive_strength."""
from contextlib import contextmanager
from pathlib import Path

SUPPORT_FILE = Path(__file__).resolve()
IMPORTER = Path('External/donut/src/engine/GltfImporter.cpp')

@contextmanager
def emission_support(source):
    original = source.read_bytes()
    text = original.decode('utf-8')
    needle = '        matinfo->emissiveColor = material.emissive_factor;'
    if text.count(needle) != 1 or 'material.emissive_strength.emissive_strength' in text:
        raise RuntimeError(f'Unexpected pinned Donut importer: {source}')
    newline = '\r\n' if '\r\n' in text else '\n'
    replacement = needle + newline + '        if (material.has_emissive_strength)' + newline + \
        '            matinfo->emissiveColor *= material.emissive_strength.emissive_strength;'
    try:
        source.write_bytes(text.replace(needle, replacement).encode('utf-8'))
        yield
    finally:
        source.write_bytes(original)
        if source.read_bytes() != original:
            raise RuntimeError(f'Donut importer restoration failed: {source}')
