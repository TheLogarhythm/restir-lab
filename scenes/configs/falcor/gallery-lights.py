"""Approximate Donut gallery analytic lights with Falcor lights for visual scouts.

Areas become isotropic point lights; source radius/range and exact spot falloff
are not reproduced. This is not renderer-equivalent photometric conversion.
"""
import json
import math
import re


def _forward(q):
    x, y, z, w = q
    return (-2 * (x*z + w*y), -2 * (y*z - w*x), -(1 - 2*(x*x + y*y)))


def _nodes(nodes):
    for node in nodes:
        yield node
        yield from _nodes(node.get('children', []))


def add_gallery_lights(builder, file_path):
    text = file_path.read_text(encoding='utf-8')
    scene = json.loads(re.sub(r',\s*([}\]])', r'\1', text))
    counts = {'DirectionalLight': 0, 'PointLight': 0, 'SpotLight': 0, 'RectLight': 0}
    for node in _nodes(scene['graph']):
        kind = node.get('type')
        if kind not in counts:
            continue
        counts[kind] += 1
        name = node.get('name', kind)
        color = node.get('color', [1.0, 1.0, 1.0])
        if kind == 'DirectionalLight':
            light = DirectionalLight(name)
            light.direction = float3(*_forward(node.get('rotation', [0, 0, 0, 1])))
            magnitude = node.get('irradiance', 1.0)
        else:
            light = PointLight(name)
            light.position = float3(*node['translation'])
            magnitude = node.get('intensity', 1.0)
            if kind == 'RectLight':
                magnitude = node['flux'] / (4 * math.pi)
            if kind == 'SpotLight':
                light.direction = float3(*_forward(node.get('rotation', [0, 0, 0, 1])))
                outer = math.radians(node.get('outerAngle', 180))
                inner = math.radians(node.get('innerAngle', 0))
                light.openingAngle = outer
                light.penumbraAngle = max(0.0, outer - inner)
        light.intensity = float3(*(c * magnitude for c in color))
        builder.addLight(light)
    print('Approximate gallery lights:', counts, flush=True)
