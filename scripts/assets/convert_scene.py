"""Convert a source scene using an explicit profile into a new self-contained directory."""
import argparse
import json
from pathlib import Path
import tempfile
from asset_io import validate_bundle
from blender_runner import export_scene
from gltf import digest

PROFILES = {"orca": (".fbx", ".gltf"), "san-miguel": (".obj", ".gltf"),
            "classroom": (".blend",), "orca-scene": (".fbx",), "tungsten": (".json",)}


def static_export_metadata(raw, frame, visible_only):
    """Reject an incomplete static export before material conversion or publication."""
    metadata = json.loads(raw.with_suffix(".import.json").read_text(encoding="utf-8"))
    if type(metadata.get("source_frame")) is not int or metadata["source_frame"] != frame:
        raise ValueError("Exported static pose differs from the requested frame")
    if visible_only and (metadata.get("visibility_filter") != "visible_and_renderable"
                         or type(metadata.get("excluded_meshes")) is not int
                         or metadata["excluded_meshes"] < 0):
        raise ValueError("Exported visibility policy does not confirm visible-only filtering")
    if json.loads(raw.read_text(encoding="utf-8")).get("animations"):
        raise ValueError("Static export still contains animation")
    return metadata


def convert_scene(source, output, profile, *, blender=None, texture_size=512, expected_emissive=None,
                  source_archive_sha256=None, static_frame=None, visible_only=False):
    source, output = Path(source).resolve(), Path(output).resolve()
    if profile not in PROFILES or source.suffix.lower() not in PROFILES[profile]:
        raise ValueError("Source format does not match conversion profile")
    if not source.is_file():
        raise FileNotFoundError(source)
    if output.suffix.lower() != ".gltf":
        raise ValueError("Output must end in .gltf")
    if not 64 <= texture_size <= 4096:
        raise ValueError("texture-size must be 64..4096")
    if expected_emissive is not None and (profile != "orca" or expected_emissive < 0):
        raise ValueError("expected-emissive-triangles is a nonnegative ORCA-only check")
    if static_frame is not None and (type(static_frame) is not int or static_frame < 0
                                     or profile != "orca" or source.suffix.lower() != ".fbx"):
        raise ValueError("static-frame requires a nonnegative integer and an ORCA FBX source")
    if type(visible_only) is not bool or (visible_only and static_frame is None):
        raise ValueError("visible-only requires static-frame for an ORCA FBX source")
    destination = output.parent
    if destination.exists():
        raise FileExistsError(f"Use a new conversion directory: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Stage next to the destination for a same-volume rename. No existing resource is modified.
    with tempfile.TemporaryDirectory(prefix=".conversion-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        staged_output = stage / output.name
        version = None
        if profile == "tungsten":
            from profiles.tungsten import convert
            record = convert(source, staged_output)
        elif profile == "classroom":
            version = export_scene(source, staged_output, "classroom", blender=blender, texture_size=texture_size)
            record = json.loads(staged_output.with_suffix(".conversion.json").read_text(encoding="utf-8"))
        else:
            with tempfile.TemporaryDirectory(prefix="raw-", dir=temporary) as raw_directory:
                raw = source
                if source.suffix.lower() != ".gltf":
                    raw = Path(raw_directory) / "raw.gltf"
                    worker_profile = {"orca": "fbx", "orca-scene": "orca-scene", "san-miguel": "obj"}[profile]
                    export_options = {"static_frame": static_frame} if static_frame is not None else {}
                    if visible_only:
                        export_options["visible_only"] = True
                    version = export_scene(source, raw, worker_profile, blender=blender, **export_options)
                if profile in ("orca", "orca-scene"):
                    from profiles.orca import convert
                    metadata = {}
                    if static_frame is not None:
                        metadata = static_export_metadata(raw, static_frame, visible_only)
                    record = convert(raw, staged_output, expected_emissive)
                    record.update(metadata)
                    if profile == "orca-scene":
                        from profiles.orca_scene import finish_scene
                        metadata = json.loads(raw.with_suffix(".import.json").read_text(encoding="utf-8"))
                        record.update(finish_scene(source, staged_output, metadata))
                else:
                    from profiles.san_miguel import prepare
                    record = prepare(raw, staged_output)
        record.pop("source_gltf", None)
        record.pop("output_gltf", None)
        record.update(profile=profile, source=str(source), source_sha256=digest(source),
                      output_gltf=output.name, output_sha256=digest(staged_output),
                      resources=validate_bundle(staged_output))
        if source_archive_sha256 is not None:
            record["source_archive_sha256"] = source_archive_sha256.lower()
        if version:
            record["blender_version"] = version
        staged_output.with_suffix(".conversion.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8")
        if destination.exists():
            raise FileExistsError(f"Output directory appeared during conversion: {destination}")
        stage.rename(destination)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--blender")
    parser.add_argument("--texture-size", type=int, default=512)
    parser.add_argument("--expected-emissive-triangles", type=int)
    parser.add_argument("--static-frame", type=int, help="Bake one Blender timeline frame after ORCA FBX import into a static glTF")
    parser.add_argument("--visible-only", action="store_true", help="Respect source visibility/renderability when baking a static FBX frame")
    args = parser.parse_args()
    try:
        record = convert_scene(args.source, args.output, args.profile, blender=args.blender,
                               texture_size=args.texture_size, expected_emissive=args.expected_emissive_triangles,
                               static_frame=args.static_frame, visible_only=args.visible_only)
    except (OSError, ValueError, KeyError, IndexError, RuntimeError) as exc:
        parser.exit(1, f"Conversion failed: {exc}\n")
    print(f"Converted {args.profile}: {args.output} ({len(record['resources'])} resources)")


if __name__ == "__main__":
    main()
