"""Fail-closed shader adaptation for explicitly marked glTF StandardMaterial.

Bit 20 is reserved by the matching runtime plugin and validated at build time.
This does not claim BSDF equivalence or support glTF alpha blending.
"""

MARKER = '(1u << 20)'


def _replace_once(text, old, new):
    count = text.count(old)
    if count != 1:
        raise ValueError(f'Expected one shader anchor, found {count}: {old[:80]}')
    return text.replace(old, new, 1)


def patch_sources(sources):
    patched = dict(sources)
    changes = {
        'standard': [
            ('const float3 baseColor = ms.sampleTexture(data.texBaseColor, s, sd.uv, data.baseColor, lod).rgb;',
             'const float3 baseColor = (data.flags & (1u << 20)) != 0\n            ? data.baseColor.rgb * ms.sampleTexture(data.texBaseColor, s, sd.uv, float4(1.f), lod).rgb\n            : ms.sampleTexture(data.texBaseColor, s, sd.uv, data.baseColor, lod).rgb;'),
            ('const float4 spec = ms.sampleTexture(data.texSpecular, s, sd.uv, data.specular, lod);',
             'const float4 spec = (data.flags & (1u << 20)) != 0\n            ? data.specular * ms.sampleTexture(data.texSpecular, s, sd.uv, float4(1.f), lod)\n            : ms.sampleTexture(data.texSpecular, s, sd.uv, data.specular, lod);'),
            ('emission = ms.sampleTexture(data.texEmissive, s, sd.uv, float4(data.emissive, 1), lod).rgb * data.emissiveFactor;',
             'emission = (data.flags & (1u << 20)) != 0\n                ? data.emissive * ms.sampleTexture(data.texEmissive, s, sd.uv, float4(1.f), lod).rgb * data.emissiveFactor\n                : ms.sampleTexture(data.texEmissive, s, sd.uv, float4(data.emissive, 1), lod).rgb * data.emissiveFactor;'),
            ('d.diffuse = baseColor;\n            d.specular = spec.rgb;',
             'd.diffuse = (data.flags & (1u << 20)) != 0 ? baseColor * (1.f - max(spec.r, max(spec.g, spec.b))) : baseColor;\n            d.specular = spec.rgb;'),
        ],
        'system': [
            ('float alphaThreshold = header.getAlphaThreshold();',
             'if (header.isBasicMaterial())\n        {\n            BasicMaterialData md = getBasicMaterialData(materialID);\n            if ((md.flags & (1u << 20)) != 0) alpha *= float(md.baseColor.a);\n        }\n        float alphaThreshold = header.getAlphaThreshold();'),
            ('return sampleTexture(md.texEmissive, s, uv, float4(md.emissive, 1.f), lod).rgb * md.emissiveFactor;',
             'return (md.flags & (1u << 20)) != 0\n                ? md.emissive * sampleTexture(md.texEmissive, s, uv, float4(1.f), lod).rgb * md.emissiveFactor\n                : sampleTexture(md.texEmissive, s, uv, float4(md.emissive, 1.f), lod).rgb * md.emissiveFactor;'),
        ],
        'finalize': [
            ('float3 averageRadiance = averageEmissiveColor * materialData.emissiveFactor;',
             'if ((materialData.flags & (1u << 20)) != 0 && gScene.materials.isEmissiveTextured(tri.materialID))\n        averageEmissiveColor *= materialData.emissive;\n    float3 averageRadiance = averageEmissiveColor * materialData.emissiveFactor;'),
        ],
    }
    for key, replacements in changes.items():
        for old, new in replacements:
            patched[key] = _replace_once(patched[key], old, new)
    return patched
