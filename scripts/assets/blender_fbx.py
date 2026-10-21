"""Scoped compatibility for Blender FBX imports using a removed Cycles shadow flag."""
from contextlib import contextmanager


@contextmanager
def legacy_light_property(bpy):
    # Blender 5.2's bundled FBX importer assigns this removed RNA property after
    # already setting Light.use_shadow. Keep the redundant legacy value only
    # during import; do not change installed Blender code or exported lighting.
    settings = getattr(bpy.types, "CyclesLightSettings", None)
    if settings is None:
        try:
            from cycles.properties import CyclesLightSettings as settings
        except ImportError:
            pass
    added = settings is not None and "cast_shadow" not in settings.bl_rna.properties
    if added:
        settings.cast_shadow = bpy.props.BoolProperty(default=True)
    try:
        yield added
    finally:
        if added:
            del settings.cast_shadow
