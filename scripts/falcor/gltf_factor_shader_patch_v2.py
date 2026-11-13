"""Versioned SG sampling fix for explicitly marked glTF materials.

SpecGloss already defines diffuse and specular lobes directly. Falcor's
getMetallic reconstruction can generate NaNs or remove a nonzero diffuse
lobe from sampling; use an internal sampling weight of zero metallic for the
marked SG path. This value is not a reconstructed glTF material property.
"""
if __package__:
    from .gltf_factor_shader_patch import patch_sources as patch_factor_sources
else:
    from gltf_factor_shader_patch import patch_sources as patch_factor_sources


def patch_sources(sources):
    result = patch_factor_sources(sources)
    old = 'd.metallic = getMetallic(d.diffuse, d.specular);'
    # Only the regular material path; differentiable rendering is unsupported.
    if result['standard'].count(old) != 2:
        raise ValueError('Expected regular and differentiable SpecGloss anchors')
    replacement = 'd.metallic = (data.flags & (1u << 20)) != 0 ? 0.f : getMetallic(d.diffuse, d.specular);'
    result['standard'] = result['standard'].replace(old, replacement, 1)
    return result
