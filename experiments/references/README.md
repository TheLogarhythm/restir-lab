# Falcor reference set

`falcor-pt-spatial-comparison-16384.json` records the six 1920 × 1080,
16384-spp references independently of `runs/`. Paths are relative to the
repository root. The EXRs are generated assets and are not included in Git;
place the files at the paths in the manifest and check their SHA-256 values.

The six hashes were checked against the retained historical catalog at
`runs/pt-6-views-spatial-compare/provenance/reference-catalog.original.json` (SHA-256
`80c4dbcf12379670cec5dd7a4e3db8dc238822572d76c3a2cdfb96b745f54f82`)
and against the original EXR bytes. The original catalog bytes are preserved. Final images remain byte-identical;
redundant historical copies and intermediate blocks were retired in the 2026-11-16 compaction. The new locations were populated by copying those verified bytes.

The Falcor comparison uses this catalog independently of the historical runs.
Image files are required and checked when comparison analysis starts; rendering
only requires the catalog metadata. The scene input inventory is
`experiments/configs/falcor-pt-spatial-comparison/scene-inputs-v2.json`.

The Bistro sky can be prepared from its source scene with:

```powershell
& 'build/falcor/verify-env/Scripts/python.exe' -B -m scripts.falcor.prepare_bistro_sky_asset
```

The generated `assets/generated/bistro/environment.exr` is verified against
SHA-256 `3d99d20cae2d2168a01ee97cb81d0ae3a62dba58897e0c2517e07922e32e650d`.
The preparation script preserves the empty EXR `name` field needed for an
exact byte match. Existing files are never overwritten on a hash mismatch.
The active Bistro scene uses this generated asset.

## Scene inputs

Each camera preset selects a scene profile and resource inventory. The [preparation guide](../configs/falcor-pt-spatial-comparison/PREPARATION.md) gives the commands for these scene inputs.

- `assets/prepared/bistro-orca-v5-2/` for the Bistro exterior;
- `assets/converted/classroom/`, `assets/converted/emerald-square/`,
  `assets/converted/veach-ajar/`, and `assets/converted/zero-day/measure-seven-viewer/`;
- the Bistro glTF, DDS and environment assets under `renderers/rtxdi/Assets/Media/`;
- the generated Bistro sky described above.

The [scene lock](../configs/falcor-pt-spatial-comparison/scene-inputs-v2.json)
pins the six camera, profile and inventory files. Capture checks those records
and the actual scene inputs before and after rendering.

Method capture reads the reference catalog metadata. Analysis verifies the
hash and dimensions of each 16384-spp reference it uses. The default comparison
requires all six EXRs. A single-view temporal contrast requires the selected
view's EXR. Copy each image from the retained results or the project archive to
its path in the catalog.

For source downloads, pinned hashes and conversion commands, see
[scene assets and conversion](../../scripts/assets/README.md),
[scene manifest](../../scenes/manifest.yaml), and the
[Measure Seven extraction and conversion instructions](../../scenes/configs/rtxdi/README.md#zero-day-measure-seven).
Emerald Square and Veach Ajar are prepared with the installer described in the
asset guide. The Bistro exterior requires the ORCA Bistro bundle; the interior
uses the pinned RTXDI media and additional models recorded in its scene input
inventory. Exact-byte checks are necessary because different converter versions
can produce different files.

The schema-2 catalog also binds each image to its camera, scene/runtime inventory
and transport target. See the [six-view preparation guide](../configs/falcor-pt-spatial-comparison/PREPARATION.md)
for reusable profiles, exact recipes and no-render verification.

## Stage archive compaction — 2026-11-16

Six 8192-spp checkpoints and zipped generation records are retained under
`runs/pt-6-views-spatial-compare/<view>/reference/`. The final EXRs above remain
the canonical copies. Original 1024-spp blocks are no longer retained; the archive
cannot rebuild references or recompute block uncertainty. Historical migration
snapshots are under `provenance/scene-migrations/`; the optional migration verifier
resolves their retired paths without modifying frozen migration receipts.
