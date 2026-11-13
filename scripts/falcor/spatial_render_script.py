"""Generate a fixed-camera Mogwai script for smoke and paired PT captures."""

import math
from pathlib import Path

from . import reference_runner


VBUFFER_OPTIONS = {
    "samplePattern": "Center",
    "sampleCount": 1,
    "useAlphaTest": True,
    "useDOF": False,
}


def build_script(
    scene,
    camera,
    output,
    frames,
    options,
    *,
    adapted=False,
    capture_frames=None,
    static_clock=False,
    record_scene_state=False,
    portable=False,
    duplication_map=False,
):
    """Capture scheduled frames inside the loop, or the final frame for smoke runs."""
    scene_import = ", SceneBuilderFlags" if adapted else ""
    load_flags = ", SceneBuilderFlags.DontOptimizeMaterials" if adapted else ""
    near_plane = ""
    if "near_plane" in camera:
        near = float(camera["near_plane"])
        if not math.isfinite(near) or near <= 0:
            raise ValueError("Invalid near plane")
        near_plane = f"\ncamera.nearPlane = {near!r}"
    clock_setup = "m.clock.framerate = 0\n" if static_clock else ""
    clock_check = (
        (
            "\n    if m.clock.framerate != 0 or abs(m.clock.time) > 1e-9: "
            'raise RuntimeError("Static clock drift")'
        )
        if static_clock
        else ""
    )
    extra_output = "\ng.markOutput('PathTracer.dupMap')" if duplication_map else ""
    output = Path(output)
    output_expression = "str(Path('.').resolve())" if portable else repr(str(output))
    capture_frame = ""
    last_capture = "m.frameCapture.capture()\n"
    if capture_frames is not None:
        capture_frame = f"\n    if frame in {list(capture_frames)!r}: m.frameCapture.capture()"
        last_capture = ""
    record_scene = ""
    if record_scene_state:
        state_file = str(output / "scene-state.json")
        record_scene = f"""
    if frame == 1:
        settings = m.scene.renderSettings
        state = {{
            'lights': [{{'name': light.name, 'active': light.active,
                        'intensity': [light.intensity.x, light.intensity.y, light.intensity.z]}}
                       for light in m.scene.lights],
            'environment_present': m.scene.envMap is not None,
            'useAnalyticLights': settings.useAnalyticLights,
            'useEnvLight': settings.useEnvLight,
            'useEmissiveLights': settings.useEmissiveLights,
            'stats': m.scene.stats,
        }}
        Path({state_file!r}).write_text(json.dumps(state, indent=2), encoding='utf8')"""
    target = reference_runner.camera_target(camera)
    focal = 12.0 / math.tan(math.radians(camera["vertical_fov"]) / 2)
    return f"""import json, contextlib
from pathlib import Path
from falcor import float3, RenderGraph, createPass{scene_import}
g = RenderGraph('LabCGNSPTSmoke')
g.addPass(createPass('VBufferRT', {VBUFFER_OPTIONS!r}), 'VBufferRT')
g.addPass(createPass('PathTracer', {options!r}), 'PathTracer')
for name in ('vbuffer', 'viewW', 'mvec'):
    g.addEdge('VBufferRT.' + name, 'PathTracer.' + name)
g.markOutput('PathTracer.color'){extra_output}
m.addGraph(g)
m.loadScene({str(scene)!r}{load_flags})
m.scene.animated = False
camera = m.scene.camera
camera.animated = False
camera.position = float3(*{camera['position']!r})
camera.target = float3(*{target!r})
camera.up = float3(*{camera['up']!r})
camera.frameHeight = 24
camera.focalLength = {focal!r}
camera.apertureRadius = 0{near_plane}
{clock_setup}m.clock.pause()
m.clock.time = 0
m.frameCapture.outputDir = {output_expression}
m.frameCapture.baseFilename = 'capture'
m.frameCapture.captureAllOutputs = False
tracer = g['PathTracer']
tracer.useFixedSeed = True
def camera_state():
    return {{'position': [camera.position.x,camera.position.y,camera.position.z], 'target': [camera.target.x,camera.target.y,camera.target.z], 'up': [camera.up.x,camera.up.y,camera.up.z], 'frameHeight': camera.frameHeight, 'focalLength': camera.focalLength, 'apertureRadius': camera.apertureRadius, 'nearPlane': camera.nearPlane, 'farPlane': camera.farPlane, 'animated': camera.animated}}
records = {{'initial': camera_state()}}
for frame in range(1, {frames+1}):
    tracer.fixedSeed = frame - 1
    m.clock.frame = frame
    m.renderFrame(){clock_check}{capture_frame}{record_scene}
    if frame == 1: records['first_frame'] = {{**camera_state(), 'frame': frame}}
    if frame == {frames}: records['last_frame'] = {{**camera_state(), 'frame': frame}}
with Path({str(output / 'resolved.py')!r}).open('w',encoding='utf-8') as f, contextlib.redirect_stdout(f):
    g.print()
Path({str(output / 'resolved-camera.json')!r}).write_text(json.dumps(records,indent=2),encoding='utf-8')
{last_capture}exit()
"""
