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
    parser.add_argument("--static-frame", type=int)
    parser.add_argument("--visible-only", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.visible_only and args.static_frame is None:
        parser.error("visible-only requires static-frame")
    if args.static_frame is not None and (args.profile != "fbx" or args.static_frame < 0):
        parser.error("static-frame requires the FBX profile and a nonnegative frame")
    if args.profile == "classroom":
        from profiles.classroom import convert
        convert(args.source, args.output, args.texture_size)
        return
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if args.profile in ("fbx", "orca-scene"):
        from blender_fbx import legacy_light_property
        with legacy_light_property(bpy) as compatibility:
            bpy.ops.import_scene.fbx(filepath=str(args.source), use_image_search=True, anim_offset=1.0)
    else:
        bpy.ops.wm.obj_import(filepath=str(args.source))
    options = {}
    if args.profile == "orca-scene" or args.static_frame is not None:
        import json
        from blender_scene import camera_record
        cameras = [obj for obj in bpy.context.scene.objects if obj.type == "CAMERA"]
        if not cameras and args.profile == "orca-scene":
            raise ValueError("ORCA FBX has no source camera")
        bpy.context.scene.frame_set(args.static_frame if args.static_frame is not None else 1)
        bpy.context.view_layer.update()
        metadata = {"camera": camera_record(cameras[0], bpy.context.scene) if cameras else None,
                    "camera_names": [obj.name for obj in cameras],
                    "punctual_lights": sum(obj.type == "LIGHT" for obj in bpy.context.scene.objects),
                    "fbx_legacy_shadow_compatibility": compatibility}
        if args.static_frame is not None:
            metadata["source_frame"] = bpy.context.scene.frame_current
            metadata["fbx_animation_offset"] = 1.0
            options.update(export_current_frame=True, export_cameras=True)
            if args.visible_only:
                options.update(use_visible=True, use_renderable=True)
                metadata["visibility_filter"] = "visible_and_renderable"
                metadata["excluded_meshes"] = sum(obj.type == "MESH" and
                    (not obj.visible_get() or obj.hide_render) for obj in bpy.context.scene.objects)
        args.output.with_suffix(".import.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        if args.profile == "orca-scene":
            options.update(export_cameras=True, export_lights=True, export_import_convert_lighting_mode="COMPAT")
    bpy.ops.export_scene.gltf(filepath=str(args.output), export_format="GLTF_SEPARATE",
                              export_image_format="AUTO",
                              export_animations=args.profile == "fbx" and args.static_frame is None, **options)


if __name__ == "__main__":
    main()
