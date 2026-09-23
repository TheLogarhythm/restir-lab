"""Run inside Blender: import an FBX and export a separate glTF draft."""

import sys

import bpy


def main():
    source, target = sys.argv[sys.argv.index("--") + 1 :]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=source, use_image_search=True)
    bpy.ops.export_scene.gltf(
        filepath=target,
        export_format="GLTF_SEPARATE",
        export_image_format="AUTO",
        use_selection=False,
    )


if __name__ == "__main__":
    main()
