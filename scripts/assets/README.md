# Scene conversion

From the repo root, use Blender 5.2 and run `python -m pip install -r scripts/assets/requirements.txt`. Keep assets under ignored `assets/`.

`convert_scene.py` is the single conversion entry point. Use a **new output directory**;
resources and conversion records are validated in staging before publication.
Internal `profiles/` contain source-specific rules; Blender launch, node traversal,
light conversion and glTF resource handling live in shared modules.

## ORCA FBX/DDS

```powershell
python scripts/assets/extract_orca.py --archive assets/sources/zero-day/ZeroDay_v1.zip --folder MEASURE_ONE --output assets/prepared/zero-day-measure-one
python scripts/assets/convert_scene.py --profile orca --source assets/prepared/zero-day-measure-one/MEASURE_ONE/MEASURE_ONE.fbx --output assets/converted/zero-day/measure-one.gltf --expected-emissive-triangles 10103
```

For similar scenes, change the paths and omit the expected count if unknown. The converter requires UV0 and supports packed DDS (R=AO, G=roughness, B=metallic) with DirectX normals. Check its `.conversion.json` and inspect materials before research comparisons.

Missing emissive UVs are accepted only for proven constant static 8-bit PNG/JPEG textures: their sRGB color is folded into the linear emissive factor, preserving strength. Nonconstant textures, unsupported encodings/extensions, and invalid emission values fail explicitly. Folded materials are listed in `.conversion.json`.

The reusable `gltf_materials.normalize_opaque_materials` pass promotes `BLEND` to
`OPAQUE` only when factor and texture alpha are exactly 1. It verifies static
PNG (up to 8-bit) / JPEG; RGBA vertex colors, material animations, remaining
extensions and unverified image formats retain blending. `MASK` is preserved.
The conversion record lists changed material indices and reasons for retained blends.

[Zero-Day source](https://developer.nvidia.com/orca/beeple-zero-day) ZIP SHA-256: `A9D040FE9720EE88937778659205FD76BAD4499431A37156AAEEBA382F08D592`. See [scene status](../../scenes/catalog.md) and [viewer commands](../run/README.md).

## San Miguel and Classroom

Keep downloaded ZIPs in `assets/sources/<scene>/` and extract into
`assets/prepared/<scene>/`. Source links, licenses and ZIP hashes are in
[the manifest](../../scenes/manifest.yaml); never overwrite originals.
These scene-specific conversions were run with Blender 5.2.

```powershell
python scripts/assets/convert_scene.py --profile san-miguel --source assets/prepared/san-miguel-low-poly/san-miguel-low-poly.obj --output assets/converted/san-miguel/san-miguel.gltf
python scripts/assets/convert_scene.py --profile classroom --source assets/prepared/classroom/classroom/classroom.blend --output assets/converted/classroom/classroom.gltf
```

ORCA and San Miguel can also accept an existing raw `.gltf` via `--source`.
San Miguel restores PNG cutout alpha and adds no lights.
Classroom preserves object material overrides, emissive strength and source lamp
instances. Load `classroom.scene.json`: it combines glTF with the original
sun, seven point-light instances and two area lights in Donut's radiometric units.
No local fill lights are invented. The default viewer sun/sky remain available.

Classroom bakes legacy color graphs to 512-pixel atlases. Portal sky color is
baked rather than direction-dependent; the camera/shadow-invisible window emitter
uses zero opacity. Mixed/translucent surfaces and glass remain approximate; unsupported surface nodes
use a recorded neutral-gray fallback. Bump and volumes are omitted.
Both retain `.conversion.json` records. Validate resource hashes and inspect the
[preview](../run/README.md) after conversion; this is not full Cycles equivalence.
