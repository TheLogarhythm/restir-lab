"""Convert a source scene using an explicit profile into a new self-contained directory."""
import argparse
import json
from pathlib import Path
import tempfile
from asset_io import validate_bundle
from blender_runner import export_scene
from gltf import digest

PROFILES = {"orca": (".fbx", ".gltf"), "san-miguel": (".obj", ".gltf"),
            "classroom": (".blend",)}


def convert_scene(source, output, profile, *, blender=None, texture_size=512, expected_emissive=None):
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
        if profile == "classroom":
            version = export_scene(source, staged_output, "classroom", blender=blender, texture_size=texture_size)
            record = json.loads(staged_output.with_suffix(".conversion.json").read_text(encoding="utf-8"))
        else:
            with tempfile.TemporaryDirectory(prefix="raw-", dir=temporary) as raw_directory:
                raw = source
                if source.suffix.lower() != ".gltf":
                    raw = Path(raw_directory) / "raw.gltf"
                    version = export_scene(source, raw, "fbx" if profile == "orca" else "obj", blender=blender)
                if profile == "orca":
                    from profiles.orca import convert
                    record = convert(raw, staged_output, expected_emissive)
                else:
                    from profiles.san_miguel import prepare
                    record = prepare(raw, staged_output)
        record.pop("source_gltf", None)
        record.pop("output_gltf", None)
        record.update(profile=profile, source=str(source), source_sha256=digest(source),
                      output_gltf=output.name, output_sha256=digest(staged_output),
                      resources=validate_bundle(staged_output))
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
    args = parser.parse_args()
    try:
        record = convert_scene(args.source, args.output, args.profile, blender=args.blender,
                               texture_size=args.texture_size, expected_emissive=args.expected_emissive_triangles)
    except (OSError, ValueError, KeyError, IndexError, RuntimeError) as exc:
        parser.exit(1, f"Conversion failed: {exc}\n")
    print(f"Converted {args.profile}: {args.output} ({len(record['resources'])} resources)")


if __name__ == "__main__":
    main()
