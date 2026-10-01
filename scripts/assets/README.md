# ORCA FBX/DDS conversion

From the repo root, use Blender 5.2 and run `python -m pip install -r scripts/assets/requirements.txt`. Keep assets under ignored `assets/`.

```powershell
python scripts/assets/extract_orca.py --archive assets/sources/zero-day/ZeroDay_v1.zip --folder MEASURE_ONE --output assets/prepared/zero-day-measure-one
python scripts/assets/convert_orca_fbx.py --fbx assets/prepared/zero-day-measure-one/MEASURE_ONE/MEASURE_ONE.fbx --output assets/converted/zero-day/measure-one.gltf --expected-emissive-triangles 10103
```

For similar scenes, change the paths and omit the expected count if unknown. The converter requires UV0 and supports packed DDS (R=AO, G=roughness, B=metallic) with DirectX normals. Check its `.conversion.json` and inspect materials before research comparisons.

Missing emissive UVs are accepted only for proven constant static 8-bit PNG/JPEG textures: their sRGB color is folded into the linear emissive factor, preserving strength. Nonconstant textures, unsupported encodings/extensions, and invalid emission values fail explicitly. Folded materials are listed in `.conversion.json`.

The reusable `gltf_materials.normalize_opaque_materials` pass promotes `BLEND` to
`OPAQUE` only when factor and texture alpha are exactly 1. It verifies static
PNG (up to 8-bit) / JPEG; RGBA vertex colors, material animations, remaining
extensions and unverified image formats retain blending. `MASK` is preserved.
The conversion record lists changed material indices and reasons for retained blends.

[Zero-Day source](https://developer.nvidia.com/orca/beeple-zero-day) ZIP SHA-256: `A9D040FE9720EE88937778659205FD76BAD4499431A37156AAEEBA382F08D592`. See [scene status](../../scenes/catalog.md) and [viewer commands](../run/README.md).
