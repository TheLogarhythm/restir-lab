"""Blender worker for the unified conversion CLI; ordinary Python uses blender_runner."""
import argparse
from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=("fbx", "obj", "classroom"))
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--texture-size", type=int, default=512)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.profile == "classroom":
        from profiles.classroom import convert
        convert(args.source, args.output, args.texture_size)
        return
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if args.profile == "fbx":
        bpy.ops.import_scene.fbx(filepath=str(args.source), use_image_search=True)
    else:
        bpy.ops.wm.obj_import(filepath=str(args.source))
    bpy.ops.export_scene.gltf(filepath=str(args.output), export_format="GLTF_SEPARATE",
                              export_image_format="AUTO", export_animations=args.profile == "fbx")


if __name__ == "__main__":
    main()
