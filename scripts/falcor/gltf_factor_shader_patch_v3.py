"""Add marked glTF metal/rough transmission tint to the SpecGloss fix.

No claim of Falcor/RTXDI Fresnel or shadow-ray equivalence. Transmission
textures and differentiable material execution remain unsupported.
"""
if __package__:
    from .gltf_factor_shader_patch_v2 import patch_sources as previous_patch_sources
else:
    from gltf_factor_shader_patch_v2 import patch_sources as previous_patch_sources


def patch_sources(sources):
    result = previous_patch_sources(sources)
    anchor = '#if defined(SCENE_DIFFUSE_ALBEDO_MULTIPLIER)'
    if result['standard'].count(anchor) != 2:
        raise ValueError('Expected regular and differentiable multiplier anchors')
    inserted = '''// glTF metal/rough transmission applies to the dielectric fraction,
        // and carries the linear base color; marked materials only.
        if ((data.flags & (1u << 20)) != 0 && data.getShadingModel() == ShadingModel::MetalRough)
        {
            d.specularTransmission *= 1.f - d.metallic;
            if (d.specularTransmission > 0.f) d.transmission = baseColor;
        }

#if defined(SCENE_DIFFUSE_ALBEDO_MULTIPLIER)'''
    result['standard'] = result['standard'].replace(anchor, inserted, 1)
    return result
