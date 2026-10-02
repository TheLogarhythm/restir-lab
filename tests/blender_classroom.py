"""Run with Blender --background --python tests/blender_classroom.py."""
import json
import math
from pathlib import Path
import sys
import tempfile
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/assets'))
from profiles import classroom as exporter

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_plane_add()
    obj = bpy.context.object
    glass = bpy.data.materials.new('mesh-glass')
    obj.data.materials.append(glass)
    light = bpy.data.materials.new('object-emitter')
    light.use_nodes = True
    nodes = light.node_tree.nodes
    nodes.clear()
    emission = nodes.new('ShaderNodeEmission')
    emission.inputs['Strength'].default_value = 2
    output = nodes.new('ShaderNodeOutputMaterial')
    light.node_tree.links.new(emission.outputs[0], output.inputs['Surface'])
    obj.material_slots[0].link = 'OBJECT'
    obj.material_slots[0].material = light
    bpy.ops.mesh.primitive_plane_add(location=(3, 0, 0))
    portal = bpy.context.object
    material = light.copy()
    material.name = 'dayLight_portal'
    portal.data.materials.append(material)
    portal.visible_camera = False
    portal.visible_shadow = False
    # An unconnected emission must not turn a diffuse surface into a light.
    bpy.ops.mesh.primitive_plane_add(location=(6, 0, 0))
    diffuse = bpy.data.materials.new('connected-diffuse')
    diffuse.use_nodes = True
    nodes = diffuse.node_tree.nodes
    nodes.clear()
    nodes.new('ShaderNodeEmission')
    shader = nodes.new('ShaderNodeBsdfDiffuse')
    output = nodes.new('ShaderNodeOutputMaterial')
    diffuse.node_tree.links.new(shader.outputs[0], output.inputs['Surface'])
    bpy.context.object.data.materials.append(diffuse)
    for kind, energy in (("SUN", 1), ("POINT", 4 * math.pi), ("AREA", 4 * math.pi)):
        data = bpy.data.lights.new(kind, kind)
        data.energy = energy
        data.normalize = True
        if kind == "AREA": data.size = 2
        lamp = bpy.data.objects.new(kind, data)
        bpy.context.scene.collection.objects.link(lamp)
    bpy.ops.object.camera_add()
    bpy.context.scene.camera = bpy.context.object
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'source.blend'))
    exporter.convert(root / "source.blend", root / "result.gltf", texture_size=64)
    document = json.loads((root/'result.gltf').read_text())
    emitters = [m for m in document['materials'] if any(m.get('emissiveFactor', []))]
    assert len(emitters) == 2, 'Emission was lost or an unconnected emitter was exported'
    assert not any(next(m for m in document['materials'] if m['name'].startswith('connected-diffuse')).get('emissiveFactor', []))
    assert next(m for m in emitters if m['name'].startswith('object-emitter'))['extensions']['KHR_materials_emissive_strength']['emissiveStrength'] == 2
    assert 'KHR_lights_punctual' not in document.get('extensions', {}), 'Invented light'
    portal = next(m for m in emitters if m['name'].startswith('dayLight_portal'))
    assert portal['alphaMode'] in ('BLEND', 'MASK') and portal['pbrMetallicRoughness']['baseColorFactor'][3] == 0, portal
    scene = json.loads((root/'result.scene.json').read_text())
    lights = {n['type']: n for n in scene['graph'] if 'type' in n}
    assert set(lights) == {'DirectionalLight', 'PointLight', 'RectLight'}
    assert abs(lights['PointLight']['intensity'] - 1) < 1e-6
    area = lights['RectLight']
    assert abs(area['flux'] / (area['width'] * area['height']) - 1) < 1e-6
    print('PASS: object-level emission and strength retained; no injected lights')
