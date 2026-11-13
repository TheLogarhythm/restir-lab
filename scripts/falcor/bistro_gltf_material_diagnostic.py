"""Diagnostic glTF material rebinding; NOT a qualified reference implementation."""
from pathlib import Path
import json
import os
from bistro_gltf_material_plan import build_material_plan, effective_alpha_cutoff


def apply_materials(builder, source, falcor):
    source = Path(source)
    plan = build_material_plan(json.loads(source.read_text(encoding='utf-8-sig')))
    materials = list(builder.materials)
    by_name = {}
    for material in materials:
        by_name.setdefault(material.name, []).append(material)
    print('LAB_BISTRO imported_materials', len(materials), 'gltf_materials', len(plan), flush=True)
    missing = [item['name'] for item in plan if len(by_name.get(item['name'], [])) != 1]
    if missing:
        raise RuntimeError('Material identity is missing or ambiguous: ' + repr(missing[:20]))
    created = []
    for row in plan:
        model = falcor.ShadingModel.SpecGloss if row['model'] == 'specular_glossiness' else falcor.ShadingModel.MetalRough
        material = falcor.StandardMaterial(row['name'], model)
        material.baseColor = falcor.float4(*row['base_color_factor'])
        if row['model'] == 'specular_glossiness':
            material.specularParams = falcor.float4(*row['specular_factor'], row['glossiness_factor'])
        else:
            material.specularParams = falcor.float4(0, row['roughness_factor'], row['metallic_factor'], 0)
        material.emissiveColor = falcor.float3(*row['emissive_factor'])
        material.specularTransmission = row['transmission_factor']
        material.doubleSided = row['double_sided']
        for key, slot in [('base_color', falcor.MaterialTextureSlot.BaseColor),
                          ('specular', falcor.MaterialTextureSlot.Specular),
                          ('normal', falcor.MaterialTextureSlot.Normal),
                          ('emissive', falcor.MaterialTextureSlot.Emissive)]:
            uri = row['textures'][key]
            if uri:
                path = (source.parent / uri).resolve()
                if not path.is_file():
                    raise FileNotFoundError(path)
                builder.loadMaterialTexture(material, slot, path)
        if row['textures']['transmission']:
            raise RuntimeError('Transmission textures are not implemented')
        if row['alpha_mode'] in ('OPAQUE', 'MASK'):
            material.alphaThreshold = effective_alpha_cutoff(row['alpha_mode'], row['alpha_cutoff'], row['base_color_factor'][3])
        elif row['alpha_mode'] == 'BLEND':
            print('LAB_BISTRO unsupported_alpha_blend', row['name'], flush=True)
        elif row['alpha_mode'] != 'OPAQUE':
            raise RuntimeError('Unsupported alpha mode')
        builder.replaceMaterial(by_name[row['name']][0], material)
        created.append((row, material))
    builder.waitForMaterialTextureLoading()
    loaded = 0
    for row, material in created:
        for key, slot in [('base_color', falcor.MaterialTextureSlot.BaseColor),
                          ('specular', falcor.MaterialTextureSlot.Specular),
                          ('normal', falcor.MaterialTextureSlot.Normal),
                          ('emissive', falcor.MaterialTextureSlot.Emissive)]:
            if row['textures'][key]:
                texture = material.getTexture(slot)
                if texture is None or texture.width < 1 or texture.height < 1:
                    raise RuntimeError('Texture failed to load: ' + row['name'] + '/' + key)
                loaded += 1
        if row['alpha_mode'] in ('OPAQUE', 'MASK'):
            material.alphaThreshold = effective_alpha_cutoff(row['alpha_mode'], row['alpha_cutoff'], row['base_color_factor'][3])
    audit_path = os.environ.get('LAB_BISTRO_MATERIAL_AUDIT')
    if audit_path:
        def vec(value, n):
            return [float(getattr(value, component)) for component in 'xyzw'[:n]]
        audit = []
        for row, material in created:
            audit.append({'name': row['name'], 'model': str(material.shadingModel),
                          'base_color': vec(material.baseColor, 4),
                          'specular': vec(material.specularParams, 4),
                          'emissive': vec(material.emissiveColor, 3),
                          'transmission': float(material.specularTransmission),
                          'alpha_mode': str(material.alphaMode),
                          'alpha_threshold': float(material.alphaThreshold),
                          'double_sided': bool(material.doubleSided)})
        with Path(audit_path).open('x', encoding='utf8') as f:
            json.dump(audit, f, indent=2)
    print('LAB_BISTRO verified_texture_slots', loaded, flush=True)
    print('LAB_BISTRO rebound', len(plan), 'specGloss', sum(r['model']=='specular_glossiness' for r in plan),
          'transmission', sum(r['transmission_factor']>0 for r in plan), flush=True)




