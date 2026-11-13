"""Exact source transformations for a diagnostic glTF-factor Falcor runtime.

This does not establish full renderer equivalence or implement glTF alpha blend.
"""


def _replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Expected exactly one shader match: ' + old[:65])
    return text.replace(old, new)


def patch_sources(sources):
    patched = dict(sources)
    replacements = {
        'standard': [
            ('const float3 baseColor = ms.sampleTexture(data.texBaseColor, s, sd.uv, data.baseColor, lod).rgb;',
             'const float3 baseColor = data.baseColor.rgb * ms.sampleTexture(data.texBaseColor, s, sd.uv, float4(1.f), lod).rgb;'),
            ('const float4 spec = ms.sampleTexture(data.texSpecular, s, sd.uv, data.specular, lod);',
             'const float4 spec = data.specular * ms.sampleTexture(data.texSpecular, s, sd.uv, float4(1.f), lod);'),
            ('emission = ms.sampleTexture(data.texEmissive, s, sd.uv, float4(data.emissive, 1), lod).rgb * data.emissiveFactor;',
             'emission = data.emissive * ms.sampleTexture(data.texEmissive, s, sd.uv, float4(1.f), lod).rgb * data.emissiveFactor;'),
        ],
        'system': [
            ('return sampleTexture(md.texEmissive, s, uv, float4(md.emissive, 1.f), lod).rgb * md.emissiveFactor;',
             'return md.emissive * sampleTexture(md.texEmissive, s, uv, float4(1.f), lod).rgb * md.emissiveFactor;'),
        ],
        'finalize': [
            ('float3 averageRadiance = averageEmissiveColor * materialData.emissiveFactor;',
             'if (gScene.materials.isEmissiveTextured(tri.materialID)) averageEmissiveColor *= materialData.emissive;\n    float3 averageRadiance = averageEmissiveColor * materialData.emissiveFactor;'),
        ],
    }
    for key, changes in replacements.items():
        for old, new in changes:
            patched[key] = _replace_once(patched[key], old, new)
    return patched
