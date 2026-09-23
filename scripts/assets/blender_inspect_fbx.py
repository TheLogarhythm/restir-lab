"""Print imported FBX camera names and world transforms as JSON."""

import json
import sys

import bpy
from mathutils import Vector


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=sys.argv[sys.argv.index("--") + 1], use_image_search=False)
    scene = bpy.context.scene
    frames = sorted({scene.frame_start, scene.frame_end,
                     scene.frame_start + (scene.frame_end - scene.frame_start) // 4,
                     scene.frame_start + (scene.frame_end - scene.frame_start) // 2,
                     scene.frame_start + 3 * (scene.frame_end - scene.frame_start) // 4})
    records = []
    for frame in frames:
        scene.frame_set(frame)
        for obj in bpy.data.objects:
            if obj.type != "CAMERA":
                continue
            position = obj.matrix_world.translation
            direction = -(obj.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
            # Blender is Z-up; exported glTF is Y-up.
            records.append({"name": obj.name, "frame": frame,
                            "gltf_position": [position.x, position.z, -position.y],
                            "gltf_direction": [direction.x, direction.z, -direction.y]})
    print("CAMERAS_JSON=" + json.dumps(records))


if __name__ == "__main__":
    main()
