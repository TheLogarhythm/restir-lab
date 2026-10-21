"""Blender worker for the unified conversion CLI; ordinary Python uses blender_runner."""
import argparse
from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=("fbx", "obj", "classroom", "orca-scene"))
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--texture-size", type=int, default=512)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.profile == "classroom":
        from profiles.classroom import convert
        convert(args.source, args.output, args.texture_size)
        return
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if args.profile in ("fbx", "orca-scene"):
        from blender_fbx import legacy_light_property
        with legacy_light_property(bpy) as compatibility:
            bpy.ops.import_scene.fbx(filepath=str(args.source), use_image_search=True)
    else:
        bpy.ops.wm.obj_import(filepath=str(args.source))
    options = {}
    if args.profile == "orca-scene":
        import json
        from blender_scene import camera_record
        cameras = [obj for obj in bpy.context.scene.objects if obj.type == "CAMERA"]
        if not cameras:
            raise ValueError("ORCA FBX has no source camera")
        bpy.context.scene.frame_set(1)
        bpy.context.view_layer.update()
        metadata = {"camera": camera_record(cameras[0], bpy.context.scene),
                    "camera_names": [obj.name for obj in cameras],
                    "punctual_lights": sum(obj.type == "LIGHT" for obj in bpy.context.scene.objects),
                    "fbx_legacy_shadow_compatibility": compatibility}
        args.output.with_suffix(".import.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        options.update(export_cameras=True, export_lights=True, export_import_convert_lighting_mode="COMPAT")
    bpy.ops.export_scene.gltf(filepath=str(args.output), export_format="GLTF_SEPARATE",
                              export_image_format="AUTO", export_animations=args.profile == "fbx", **options)


if __name__ == "__main__":
    main()
