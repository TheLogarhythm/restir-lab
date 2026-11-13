"""Extract an auditable material plan from a glTF without modifying assets."""
import json
from pathlib import Path


def effective_alpha_cutoff(mode, cutoff, alpha_factor=1.0):
    if mode == 'OPAQUE':
        return 0.0
    if mode == 'MASK':
        return float(cutoff) / float(alpha_factor) if alpha_factor > 0 else 2.0
    raise ValueError('Alpha blending is not implemented')


def build_material_plan(data):
    images = data.get('images', [])
    textures = data.get('textures', [])
    def texture(info):
        if not info:
            return None
        if info.get('texCoord', 0) != 0 or info.get('extensions'):
            raise ValueError('Unsupported texture coordinate or transform')
        entry = textures[info['index']]
        source = entry.get('extensions', {}).get('MSFT_texture_dds', {}).get('source', entry.get('source'))
        if source is None:
            raise ValueError('Texture source is missing')
        uri = images[source].get('uri')
        if not uri or uri.startswith('data:') or ':' in uri or uri.startswith(('/', '\\')):
            raise ValueError('Unsupported image URI')
        return uri
    result = []
    seen = set()
    for m in data.get('materials', []):
        name = m.get('name')
        if not name or name in seen:
            raise ValueError('Material names must be nonempty and unique')
        seen.add(name)
        ext = m.get('extensions', {})
        sg = ext.get('KHR_materials_pbrSpecularGlossiness')
        mr = m.get('pbrMetallicRoughness', {})
        shading = sg if sg is not None else mr
        trans = ext.get('KHR_materials_transmission', {})
        result.append({
            'name': name,
            'model': 'specular_glossiness' if sg is not None else 'metallic_roughness',
            'base_color_factor': shading.get('diffuseFactor', [1,1,1,1]) if sg is not None else shading.get('baseColorFactor', [1,1,1,1]),
            'specular_factor': shading.get('specularFactor', [1,1,1]) if sg is not None else None,
            'glossiness_factor': shading.get('glossinessFactor', 1) if sg is not None else None,
            'metallic_factor': None if sg is not None else shading.get('metallicFactor', 1),
            'roughness_factor': None if sg is not None else shading.get('roughnessFactor', 1),
            'emissive_factor': m.get('emissiveFactor', [0,0,0]),
            'transmission_factor': trans.get('transmissionFactor', 0),
            'alpha_mode': m.get('alphaMode', 'OPAQUE'),
            'alpha_cutoff': m.get('alphaCutoff', .5),
            'double_sided': m.get('doubleSided', False),
            'textures': {
                'base_color': texture(shading.get('diffuseTexture') if sg is not None else shading.get('baseColorTexture')),
                'specular': texture(shading.get('specularGlossinessTexture') if sg is not None else shading.get('metallicRoughnessTexture')),
                'normal': texture(m.get('normalTexture')),
                'emissive': texture(m.get('emissiveTexture')),
                'transmission': texture(trans.get('transmissionTexture')),
            },
        })
    return result


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('gltf', type=Path)
    args = p.parse_args()
    print(json.dumps(build_material_plan(json.loads(args.gltf.read_text(encoding='utf-8-sig'))), indent=2))


if __name__ == '__main__':
    main()


