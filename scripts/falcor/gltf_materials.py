"""Strict glTF-to-Falcor material plan and binding.

The caller must import the glTF into SceneBuilder first, disable material
constant-texture optimizations, and use a separately verified shader runtime
that multiplies glTF texture values by their source factors.  This module
fails closed for unsupported features; it does not promise BRDF parity with
another renderer.  Default BLEND behavior is rejection, not approximation.
"""
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import unquote, urlsplit

_MATERIAL_EXT = {'KHR_materials_pbrSpecularGlossiness', 'KHR_materials_transmission',
                 'KHR_materials_ior', 'KHR_materials_emissive_strength'}
_TEXTURE_EXT = {'MSFT_texture_dds'}
_KNOWN_SCENE_EXT = {'KHR_lights_punctual'}


def _sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _number(value, label, *, low=0.0, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label} must be finite numeric')
    value = float(value)
    if value < low or (high is not None and value > high):
        raise ValueError(f'{label} outside supported range')
    return value


def _vector(value, size, label, *, high=None):
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f'{label} must have {size} components')
    return [_number(v, label, high=high) for v in value]


def _index(values, index, label):
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(values):
        raise ValueError(f'Invalid {label} index')
    return values[index]


def _no_unknown_extensions(container, allowed, where):
    ext = container.get('extensions', {})
    if not isinstance(ext, dict):
        raise ValueError(f'Invalid {where} extensions')
    unknown = set(ext) - allowed
    if unknown:
        raise ValueError(f'Unsupported {where} extensions: {sorted(unknown)}')
    return ext


def build_material_plan(gltf_path, *, blend_policy='reject', asset_root=None):
    """Parse JSON glTF, hash its buffers and the actual selected texture files.

    `asset_root` bounds external resource paths; choose a common root when the
    glTF intentionally refers to assets outside its parent directory.
    `rtxdi-mask` explicitly reproduces RTXDI G-buffer's 0.5 alpha threshold;
    it is not glTF BLEND or a claim about indirect/shadow equivalence.
    """
    if blend_policy not in ('reject', 'rtxdi-mask'):
        raise ValueError('Unknown BLEND policy')
    source = Path(gltf_path).resolve(strict=True)
    if source.suffix.lower() != '.gltf':
        raise ValueError('Only JSON .gltf is supported; GLB is not implemented')
    root = Path(asset_root).resolve(strict=True) if asset_root else source.parent
    if not source.is_relative_to(root):
        raise ValueError('glTF source is outside asset_root')
    data = json.loads(source.read_text(encoding='utf-8-sig'))
    if data.get('asset', {}).get('version') != '2.0':
        raise ValueError('Only glTF 2.0 is supported')
    known = _MATERIAL_EXT | _TEXTURE_EXT | _KNOWN_SCENE_EXT
    for key in ('extensionsUsed', 'extensionsRequired'):
        unknown = set(data.get(key, [])) - known
        if unknown:
            raise ValueError(f'Unsupported glTF {key}: {sorted(unknown)}')
    resources = {}
    def record(path, uri, role):
        key = str(path)
        if key not in resources:
            resources[key] = {'path': key, 'uri': uri, 'bytes': path.stat().st_size,
                              'sha256': _sha256(path), 'roles': []}
        if role not in resources[key]['roles']:
            resources[key]['roles'].append(role)
        return resources[key]
    record(source, source.name, 'gltf')
    def resolve(uri, role):
        if not isinstance(uri, str) or not uri or uri.startswith('data:'):
            raise ValueError(f'Unsupported {role} URI or embedded resource')
        parsed = urlsplit(uri)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError(f'Unsupported {role} URI: {uri}')
        path = (source.parent / unquote(parsed.path)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f'Missing or out-of-root {role}: {uri}')
        if path.suffix.lower() == '.dds':
            with path.open('rb') as f:
                if f.read(4) != b'DDS ':
                    raise ValueError(f'Invalid DDS file: {uri}')
        return record(path, uri, role)
    for buffer in data.get('buffers', []):
        if 'uri' not in buffer:
            raise ValueError('Embedded GLB buffer is not implemented')
        resolve(buffer['uri'], 'buffer')
    images = data.get('images', [])
    textures = data.get('textures', [])
    samplers = data.get('samplers', [])
    def texture(info, slot, color_space):
        if info is None:
            return None
        if not isinstance(info, dict) or info.get('texCoord', 0) != 0 or info.get('extensions'):
            raise ValueError(f'Unsupported {slot} UV set or texture transform')
        if slot == 'normal' and info.get('scale', 1) != 1:
            raise ValueError('Normal texture scale other than 1 is not implemented')
        tex = _index(textures, info.get('index'), 'texture')
        exts = _no_unknown_extensions(tex, _TEXTURE_EXT, 'texture')
        if 'sampler' in tex:
            sampler = _index(samplers, tex['sampler'], 'sampler')
            # This adapter cannot bind distinct glTF sampler modes to each slot.
            if sampler:
                raise ValueError('Non-default texture sampler is not implemented')
        dds = exts.get('MSFT_texture_dds')
        source_index = dds.get('source') if dds is not None else tex.get('source')
        image = _index(images, source_index, 'image')
        if image.get('extensions'):
            raise ValueError('Unsupported image extension')
        resolved = resolve(image.get('uri'), 'texture')
        return {'uri': resolved['uri'], 'path': resolved['path'], 'sha256': resolved['sha256'],
                'bytes': resolved['bytes'], 'color_space': color_space,
                'alpha_channel': 'linear' if slot in ('base_color', 'specular') else None,
                'source_extension': 'MSFT_texture_dds' if dds is not None else None}
    rows = []
    limitations = []
    factor_shader = False
    for idx, material in enumerate(data.get('materials', [])):
        if not isinstance(material, dict):
            raise ValueError('Invalid material')
        ext = _no_unknown_extensions(material, _MATERIAL_EXT, 'material')
        if material.get('occlusionTexture') is not None:
            raise ValueError('Occlusion texture is not implemented')
        sg = ext.get('KHR_materials_pbrSpecularGlossiness')
        if sg is not None and 'pbrMetallicRoughness' in material:
            # glTF allows a core fallback with SpecGloss: preserve SG as the active model.
            pass
        shading = sg if sg is not None else material.get('pbrMetallicRoughness', {})
        if not isinstance(shading, dict): raise ValueError('Invalid PBR material')
        trans = ext.get('KHR_materials_transmission', {})
        if not isinstance(trans, dict): raise ValueError('Invalid transmission extension')
        if trans.get('transmissionTexture') is not None:
            raise ValueError('Per-texel transmissionTexture is not implemented')
        base = _vector(shading.get('diffuseFactor', [1,1,1,1]) if sg is not None else
                       shading.get('baseColorFactor', [1,1,1,1]), 4, 'base color', high=1.0)
        spec = _vector(shading.get('specularFactor', [1,1,1]), 3, 'specular', high=1.0) if sg is not None else None
        gloss = _number(shading.get('glossinessFactor', 1), 'glossiness', high=1.0) if sg is not None else None
        metallic = None if sg is not None else _number(shading.get('metallicFactor', 1), 'metallic', high=1.0)
        roughness = None if sg is not None else _number(shading.get('roughnessFactor', 1), 'roughness', high=1.0)
        emission = _vector(material.get('emissiveFactor', [0,0,0]), 3, 'emissive')
        strength = _number(ext.get('KHR_materials_emissive_strength', {}).get('emissiveStrength', 1), 'emissive strength')
        transmission = _number(trans.get('transmissionFactor', 0), 'transmission', high=1.0)
        ior = _number(ext.get('KHR_materials_ior', {}).get('ior', 1.5), 'IOR', low=1.0)
        double_sided = material.get('doubleSided', False)
        if type(double_sided) is not bool:
            raise ValueError('doubleSided must be a boolean')
        alpha = material.get('alphaMode', 'OPAQUE')
        cutoff = _number(material.get('alphaCutoff', .5), 'alpha cutoff', high=1.0)
        if alpha not in ('OPAQUE', 'MASK', 'BLEND'): raise ValueError('Unsupported alpha mode')
        if alpha == 'BLEND' and blend_policy != 'rtxdi-mask':
            raise ValueError('BLEND requires explicit rtxdi-mask approximation or exact implementation')
        interpretation = 'rtxdi-gbuffer-mask-approximation' if alpha == 'BLEND' else alpha.lower()
        target = .5 if alpha == 'BLEND' else cutoff
        # The verified glTF shader multiplies texture alpha by the source factor.
        effective = 0.0 if alpha == 'OPAQUE' else target
        if alpha == 'BLEND' and 'BLEND is approximated with RTXDI G-buffer 0.5 alpha mask; indirect/shadow equivalence is unverified' not in limitations:
            limitations.append('BLEND is approximated with RTXDI G-buffer 0.5 alpha mask; indirect/shadow equivalence is unverified')
        slots = {
            'base_color': texture(shading.get('diffuseTexture') if sg is not None else shading.get('baseColorTexture'), 'base_color', 'srgb'),
            'specular': texture(shading.get('specularGlossinessTexture') if sg is not None else shading.get('metallicRoughnessTexture'), 'specular', 'srgb' if sg is not None else 'linear'),
            'normal': texture(material.get('normalTexture'), 'normal', 'linear'),
            'emissive': texture(material.get('emissiveTexture'), 'emissive', 'srgb'),
        }
        if slots['base_color'] and any(v != 1 for v in base[:3]): factor_shader = True
        if slots['specular'] and (sg is not None and (any(v != 1 for v in spec) or gloss != 1) or
                                  sg is None and (roughness != 1 or metallic != 1)): factor_shader = True
        if slots['emissive'] and any(v != 1 for v in emission): factor_shader = True
        if transmission > 0 and 'Falcor thinSurface is an approximation: refraction, tint, and BRDF are not proven glTF-equivalent' not in limitations:
            limitations.append('Falcor thinSurface is an approximation: refraction, tint, and BRDF are not proven glTF-equivalent')
        rows.append({'index':idx, 'name':material.get('name'), 'model':'specular_glossiness' if sg is not None else 'metallic_roughness',
                     'base_color_factor':base, 'specular_factor':spec, 'glossiness_factor':gloss,
                     'metallic_factor':metallic, 'roughness_factor':roughness, 'emissive_factor':emission,
                     'emissive_strength':strength, 'transmission_factor':transmission, 'thin_surface':transmission > 0, 'ior':ior,
                     'alpha_mode':alpha, 'alpha_cutoff':cutoff, 'effective_alpha_cutoff':effective,
                     'alpha_interpretation':interpretation, 'double_sided':double_sided,
                     'textures':slots})
    return {'schema_version':1, 'source':str(source), 'source_sha256':_sha256(source), 'asset_root':str(root),
            'alpha_policy':blend_policy, 'shader_contract':'gltf-factor-material-v1', 'requires_texture_factor_shader':factor_shader,
            'material_optimization_must_be_disabled':True, 'limitations':limitations,
            'resources':sorted(resources.values(), key=lambda r:r['path']), 'materials':rows}


def verify_plan_resources(plan):
    """Reject changed or incomplete source/selected resource fingerprints."""
    root = Path(plan['asset_root']).resolve(strict=True)
    source = Path(plan['source']).resolve(strict=True)
    if not source.is_relative_to(root):
        raise ValueError('Source is outside asset_root')
    records = {}
    for record in plan['resources']:
        path = Path(record['path']).resolve()
        if (not path.is_relative_to(root) or not path.is_file() or
                path.stat().st_size != record['bytes'] or _sha256(path) != record['sha256']):
            raise ValueError('Resource changed since plan: ' + str(path))
        if str(path) in records:
            raise ValueError('Duplicate resource record')
        records[str(path)] = record['sha256']
    if records.get(str(source)) != plan['source_sha256']:
        raise ValueError('glTF source changed or is missing from resources')
    for row in plan['materials']:
        for item in row['textures'].values():
            if item and records.get(str(Path(item['path']).resolve())) != item['sha256']:
                raise ValueError('Material texture is missing from resources')
    return True


_SRGB_FORMATS = frozenset(('RGBA8UnormSrgb', 'BGRA8UnormSrgb', 'BGRX8UnormSrgb',
                           'BC1UnormSrgb', 'BC2UnormSrgb', 'BC3UnormSrgb', 'BC7UnormSrgb'))
_LINEAR_FORMATS = frozenset(('R8Unorm', 'R8Snorm', 'R16Unorm', 'R16Snorm', 'RG8Unorm',
    'RG8Snorm', 'RG16Unorm', 'RG16Snorm', 'RGB5A1Unorm', 'RGBA8Unorm', 'RGBA8Snorm',
    'RGB10A2Unorm', 'RGBA16Unorm', 'RGBA16Snorm', 'R16Float', 'RG16Float', 'RGBA16Float',
    'R32Float', 'RG32Float', 'RGB32Float', 'RGBA32Float', 'R11G11B10Float', 'RGB9E5Float',
    'BGRA4Unorm', 'BGRA8Unorm', 'BGRX8Unorm', 'R5G6B5Unorm', 'BC1Unorm', 'BC2Unorm',
    'BC3Unorm', 'BC4Unorm', 'BC4Snorm', 'BC5Unorm', 'BC5Snorm', 'BC6HS16', 'BC6HU16', 'BC7Unorm'))


def verify_texture_format(actual_format, expected_color_space):
    """Fail closed if Falcor loaded the texture with the wrong sampling color space."""
    name = str(actual_format).removeprefix('ResourceFormat.')
    allowed = {'srgb': _SRGB_FORMATS, 'linear': _LINEAR_FORMATS}
    if expected_color_space not in allowed or name not in allowed[expected_color_space]:
        raise ValueError(f'Unexpected texture format {actual_format} for {expected_color_space} color space')
    return True


def match_materials_by_name(rows, imported, *, material_offset=0):
    """Match a complete, isolated imported suffix by unique nonempty source names."""
    if type(material_offset) is not int or material_offset < 0 or len(imported) != material_offset + len(rows):
        raise ValueError('Imported material count/offset cannot be established')
    if [row['index'] for row in rows] != list(range(len(rows))):
        raise ValueError('Invalid source material indices')
    source_names = [row.get('name') for row in rows]
    target = imported[material_offset:]
    imported_names = [mat.name for mat in target]
    if any(not isinstance(n, str) or not n for n in source_names + imported_names):
        raise ValueError('Unnamed material cannot be matched safely')
    if len(set(source_names)) != len(source_names) or len(set(imported_names)) != len(imported_names):
        raise ValueError('Duplicate material names cannot be matched safely')
    if set(source_names) != set(imported_names):
        raise ValueError('Imported material names do not match source model')
    by_name = dict(zip(imported_names, target))
    return [by_name[name] for name in source_names]


def apply_material_plan(builder, plan, falcor, *, factor_shader_verified=False,
                        material_optimization_disabled=False, material_offset=0):
    """Replace freshly imported glTF materials by unique names, then verify textures.

    Call immediately after importing this single glTF and before the caller
    imports unrelated scene components. Caller is responsible for verifying its
    pinned factor shader and its scene builder flag. This function refuses to
    silently interpret a model with unsupported semantics.
    """
    if not factor_shader_verified:
        raise ValueError('A verified glTF factor shader is required')
    if plan.get('shader_contract') != 'gltf-factor-material-v1' or not hasattr(falcor, 'GltfFactorMaterial'):
        raise ValueError('The verified GltfFactorMaterial runtime is required')
    if not material_optimization_disabled:
        raise ValueError('Disable Falcor material optimization before loading scene')
    verify_plan_resources(plan)
    rows = plan['materials']
    imported = list(builder.materials)
    matched = match_materials_by_name(rows, imported, material_offset=material_offset)
    created = []
    slots = [('base_color', falcor.MaterialTextureSlot.BaseColor), ('specular', falcor.MaterialTextureSlot.Specular),
             ('normal', falcor.MaterialTextureSlot.Normal), ('emissive', falcor.MaterialTextureSlot.Emissive)]
    for row in rows:
        old = matched[row['index']]
        model = falcor.ShadingModel.SpecGloss if row['model']=='specular_glossiness' else falcor.ShadingModel.MetalRough
        material = falcor.GltfFactorMaterial(old.name, model)
        if getattr(material, 'gltfFactorMarker', False) is not True:
            raise RuntimeError('The glTF factor marker was not set by the runtime')
        material.baseColor = falcor.float4(*row['base_color_factor'])
        material.specularParams = (falcor.float4(*row['specular_factor'], row['glossiness_factor'])
                                   if row['model']=='specular_glossiness' else
                                   falcor.float4(0, row['roughness_factor'], row['metallic_factor'], 0))
        material.emissiveColor = falcor.float3(*row['emissive_factor'])
        material.emissiveFactor = row['emissive_strength']
        material.specularTransmission = row['transmission_factor']
        material.thinSurface = row['thin_surface']
        if material.thinSurface != row['thin_surface']:
            raise RuntimeError('Falcor did not preserve the thin-surface setting')
        material.indexOfRefraction = row['ior']
        material.doubleSided = row['double_sided']
        for key, slot in slots:
            item = row['textures'][key]
            if item:
                path = Path(item['path'])
                builder.loadMaterialTexture(material, slot, path)
        created.append((row, old, material))
    builder.waitForMaterialTextureLoading()
    loaded = []
    for row, old, material in created:
        for key, slot in slots:
            item = row['textures'][key]
            if item:
                tex = material.getTexture(slot)
                if tex is None or tex.width < 1 or tex.height < 1:
                    raise RuntimeError(f"Texture failed to load: material {row['index']} slot {key}")
                verify_texture_format(tex.format, item['color_space'])
                loaded.append({'material_index':row['index'], 'slot':key, 'path':item['path'],
                               'source_sha256':item['sha256'], 'expected_color_space':item['color_space'],
                               'actual_format':str(tex.format), 'width':int(tex.width), 'height':int(tex.height),
                               'mip_count':int(tex.mip_count)})
        material.alphaThreshold = row['effective_alpha_cutoff']
    for row, old, material in created:
        builder.replaceMaterial(old, material)
    return {'loaded_texture_slots':loaded, 'material_count':len(created),
            'limitations':list(plan['limitations']), 'source_sha256':plan['source_sha256']}


