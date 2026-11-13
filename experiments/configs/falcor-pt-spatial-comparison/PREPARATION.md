# Preparing the six Falcor views

Run commands from the repository root in PowerShell. This guide describes the
existing fixed reference target; the preparation and verification commands do
not render. The optional reference commands at the end are budgeted render
entry points, not work performed by this preparation step.

## Scene records, cameras and preserved files

The active lock is `scene-inputs-v2.json`. The six editable camera records are
under `experiments/views/falcor-pt-spatial-comparison/`:

| Camera file | Scene/view | Reusable scene | Falcor loader |
| --- | --- | --- | --- |
| `bistro-interior.json` | Bistro / view-a | RTXDI glTF composite | `scenes/configs/falcor/bistro-gltf/adapted.pyscene` |
| `bistro-exterior.json` | Bistro / view-b | ORCA Bistro 5.2 exterior | `assets/prepared/bistro-orca-v5-2/Bistro_v5_2/BistroExterior.pyscene` |
| `classroom.json` | Classroom / view-a | Converted Blender Classroom | `scenes/configs/falcor/classroom-reference.pyscene` |
| `emerald-square.json` | Emerald Square / view-a | Converted ORCA 4.1 Dusk | `scenes/configs/falcor/emerald-square-converted-reference.pyscene` |
| `veach-ajar.json` | Veach Ajar / view-a | Converted Tungsten | `scenes/configs/falcor/veach-ajar-reference.pyscene` |
| `zero-day-measure-seven.json` | Zero-Day Measure Seven / view-a | Static visible source frame 1 | `scenes/configs/falcor/zero-day-measure-seven-reference.pyscene` |

Each camera names a profile in `experiments/scenes/falcor-pt-spatial-comparison/`.
Profiles contain the scene loader, runtime requirements, qualification and
limitations, with a separate deduplicated resource/source inventory. A profile
contains no camera. In particular the indoor Bistro profile can be reused with
other cameras and by `adapted_reference_runner` and `adapted_reference_batch`.
Its inventory has 360 unique resource records and 17 unique source records;
the preserved preparation config has 710 and 18 records respectively.

The old `scene-inputs.json`, `*-reference.json` and original scene/preparation
sources remain byte-preserved for migration audits. The six-view capture APIs
accept their old filenames as validated aliases to the active composed views.
The old indoor file's `ready_for_reference: false` is retained historical
metadata; the shared active scene profile is accepted with its recorded limits.
The old direct-spec camera is a preparation snapshot, not the active camera.

Changing a camera/profile or inventory requires updating the active lock as a
reviewed scene change. A fixed reference also contains a camera, scene/runtime
and transport binding. Updating only the lock cannot make an altered camera
silently match an existing reference. New views need corresponding references.

## Pinned tools and generated bundles

The renderer is Falcor 9.0 at commit
`759aad033ff610fb0d82c74f7e0a508d0096d5f2`, using Visual Studio 2022 Release,
Windows SDK `10.0.22621.0` and the pinned dependencies in
`renderers/falcor/integration.json`. The recorded scene conversions used Blender
**5.2.0 LTS**, glTF exporter **5.2.39** and the repository conversion scripts.
Classroom used 512-pixel texture bakes. Veach Ajar uses the repository Tungsten
converter directly, without Blender. The historical plugin compilation uses
MSVC C++17 `/MD /O2 /LD`, Falcor's Release import libraries, Packman Python 3.10
and CUDA 12.6 headers; the plugin builder records actual compiler details.

Install the Python dependencies in the environment selected for these commands:

```powershell
python -m pip install -r scripts/assets/requirements.txt
python -m pip install -r scripts/falcor/requirements.txt
```

Use `build/falcor/verify-env/Scripts/python.exe` instead of `python` if reusing the
project's existing verification environment. Large source ZIPs, converted asset
bundles, EXRs and compiled runtimes are ignored generated artifacts. A clean
checkout needs those separately. Keep notices and original source archives.

For exact reuse of the catalog images, obtain the byte-identical prepared
bundles/runtimes and verify them below. Regeneration recipes reconstruct the
scene, but converter/library versions, serialized absolute provenance paths and
PE linker metadata can change bytes. A regenerated mismatch needs a reviewed
new profile/runtime/reference set; do not silently rewrite frozen hashes.

Frozen inputs are verified as raw bytes, including line endings. The parent
repository's `.gitattributes` preserves its pinned files. For a fresh Windows
checkout of the RTXDI and Donut submodules, pass `-c core.autocrlf=true` to
the submodule update command below. The historical Bistro sky receipt matches
CRLF checkouts of Donut's `sky.hlsli` and `SkyPass.cpp` and RTXDI's
`RenderEnvironmentMap.hlsl`. The no-render check below verifies the files
actually on disk, including previously initialized submodules.

## Obtain or regenerate the scene inputs

Source URLs, archive hashes and licenses are in `scenes/manifest.yaml`,
`scenes/catalog.md` and `THIRD_PARTY.md`. Install/export into unused destinations;
existing files are verified/reused or rejected, never replaced by the converters.

**Bistro indoor.** Use the RTXDI media and Donut submodules pinned by this
repository, including `bistro-rtxdi.scene.json`, Bistro, BrainStem and exterior
props referenced by that scene. The registered RTXDI-Assets revision is
`1da7b749ef0e3fb606ab46dde8e5bfbacd078a02`. Fetch the actual LFS payloads, not
pointer files. The existing scene-plan/descriptors at
`scenes/configs/falcor/bistro-gltf/` already describe all model transforms,
materials, 15 active analytic lights and the environment. Use those checked-in
wrappers; importing only `bistro.gltf` loses the composite scene setup.

```powershell
git -c core.autocrlf=true submodule update --init --recursive
# With Git LFS installed, run in the actual Assets checkout:
git -C renderers/rtxdi/Assets/Media lfs pull
python -B -m scripts.falcor.prepare_bistro_sky_asset
```

The sky command reconstructs `assets/generated/bistro/environment.exr` from the
pinned source sky and verifies SHA-256
`3d99d20cae2d2168a01ee97cb81d0ae3a62dba58897e0c2517e07922e32e650d`.
It preserves the historical empty EXR name header. No previous run is needed.
Indoor material factors use marker bit 20, `DontOptimizeMaterials` and the v3
composite runtime. The active inventory verifies the scene plan, shader-facing
loader sources, model descriptors, selected DDS resources and sky receipt.

**Bistro outdoor.** Download the ORCA `Bistro_v5_2.zip` source bundle, SHA-256
`0d50e3c724c6c5da19f8eb99ad3f53e36fec37ffa2df9621f9ccf0603f3934e1`.
Extract the unmodified `Bistro_v5_2` folder including its `.pyscene`, FBX, DDS,
HDR and notices. This view uses the author's standalone exterior scene,
including HDR intensity 10; it does not use the indoor RTXDI glTF composite.

```powershell
python scripts/assets/extract_orca.py --archive assets/sources/bistro/Bistro_v5_2.zip --folder Bistro_v5_2 --output assets/prepared/bistro-orca-v5-2 --expected-sha256 0d50e3c724c6c5da19f8eb99ad3f53e36fec37ffa2df9621f9ccf0603f3934e1
```

The frozen exterior inventory also includes `source-manifest.json` beside the
extracted folder. Obtain that recorded provenance file with the prepared
bundle for exact reference replay; its timestamped metadata is not recreated
by ZIP extraction. The camera is the recorded gallery-to-ORCA mapping. Analytic
light duplication remains a documented limitation of this source setup.

**Classroom.** Verify `assets/sources/classroom/classroom.zip` against SHA-256
`0f0ecc58d45f12b2f4272a53e2d8e69135518e16e956b118f10c20d8dcfdf5e6`, then extract
it to `assets/prepared/classroom/` so the source is `classroom/classroom.blend`.
The Falcor wrapper restores three named emissive factors and loads the recorded
source-light approximation through `gallery-lights.py` and the urban-street HDR.

```powershell
python scripts/assets/convert_scene.py --profile classroom --source assets/prepared/classroom/classroom/classroom.blend --output assets/converted/classroom/classroom.gltf --texture-size 512 --blender 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe'
```

**Emerald Square and Veach Ajar.** The installer verifies their pinned ZIPs and
checks the resulting registered runtime bundle. It selects ORCA 4.1 Dusk for
Emerald and the original Tungsten scene for Veach Ajar. The Falcor wrappers
restore the documented emissive/transmission factors. Use the converted Emerald
wrapper, not the different retained ORCA `.pyscene` with a similar name.

```powershell
python scripts/assets/install_scene.py --scene emerald-square --blender 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe'
python scripts/assets/install_scene.py --scene veach-ajar
```

**Zero-Day Measure Seven.** The ZIP SHA-256 is
`a9d040fe9720ee88937778659205fd76bad4499431a37156aaeeba382f08d592`.
Export source frame 1 and visible/renderable geometry: the registered conversion
excluded 1,708 hidden meshes. The Falcor wrapper uses the derelict-overpass HDR
and omits the gallery analytic sun.

```powershell
python scripts/assets/extract_orca.py --archive assets/sources/zero-day/ZeroDay_v1.zip --folder MEASURE_SEVEN --output assets/prepared/zero-day-measure-seven --expected-sha256 a9d040fe9720ee88937778659205fd76bad4499431a37156aaeeba382f08d592
python scripts/assets/convert_scene.py --profile orca --source assets/prepared/zero-day-measure-seven/MEASURE_SEVEN/MEASURE_SEVEN.fbx --output assets/converted/zero-day/measure-seven-viewer/measure-seven.gltf --static-frame 1 --visible-only --blender 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe'
```

## Prepare and check the renderer/runtime

```powershell
./scripts/falcor/setup.ps1 -CheckOnly
# To build a missing renderer, use ./scripts/falcor/setup.ps1 -Jobs 4.
python -B -c "from scripts.falcor import reference_runtime; reference_runtime.verify()"
python -B -m scripts.falcor.prepare_gltf_composite_runtime_v3 --verify
```

The standard reference runtime contains the checked Uniform-128 sampler patch.
The indoor runtime adds `GltfFactorMaterial`, `LabGltfTransformImporter` and v3
material/light shader changes. Their receipts bind the exact source and DLL
bytes. On a clean checkout obtain those matching build/runtime bundles when
reusing this fixed reference catalog. If a standard runtime does not exist,
`python -B -m scripts.falcor.reference_runtime` creates one from the verified
build, but a different resulting receipt requires a newly qualified profile.

To rebuild the adapter DLLs without touching the frozen binaries:

```powershell
python -B -m scripts.falcor.prepare_adapted_plugins --output build/my-new-adapted-plugins
```

This fresh directory contains both DLLs, compiler response files/logs and a
source/library/output receipt. Compilation was exercised in a fresh directory
during this refactor. It does not install the DLLs or change runtime locks.
For a new runtime, stage the new DLLs at the `PLUGIN` and `IMPORTER` locations
named in `prepare_gltf_composite_runtime_v3.py` only when those destinations do
not exist, then prepare a new isolated runtime using that script's reviewed
source/destination settings. Existing historical DLLs and runtimes must be
preserved. Revalidate material fixtures and qualify the resulting receipt
before registering a new scene/reference set.

## No-render preflight and fixed reference images

```powershell
# Metadata, all six camera/profile locks, and reference integrand bindings:
python -B -m scripts.falcor.scene_inputs
# Actual scene bytes plus expected reference-runtime receipts:
python -B -m scripts.falcor.scene_inputs --check-assets --check-runtimes
# Also verify the six optional fixed EXRs after placing them at catalog paths:
python -B -m scripts.falcor.scene_inputs --check-assets --check-runtimes --check-reference-images
python scripts/check_scaffold.py
```

The fixed EXR locations/hashes are in
`experiments/references/falcor-pt-spatial-comparison-16384.json`; they are
1920x1080, 16,384 spp. Metadata preflight and capture do not need these images;
analysis and `--check-reference-images` do. The loader checks the camera,
scene/resource/source/runtime identity, resolution, bounce limits, RR and RTXDI
transport setting. Reuse radius, temporal history and CGNS candidate parameters
can vary without changing the reference integrand.

Optional historical audits use preserved archives and remain separate:

```powershell
python -B -m scripts.falcor.verify_scene_inputs_migration
```

## Reference capture entry points

These commands render and require an approved budget and unused output paths.
They are provided for subsequent work; no formal reference was generated by
this refactor. The reference runners retain exactly eight independent seeds
of 1,024 spp each at 1920x1080. The resulting 8,192-spp average is not the
existing 16,384-spp catalog image; producing/replacing that set requires a
separately recorded extension and validation.

```powershell
# Shared indoor scene/profile and its separately supplied camera:
python -B -m scripts.falcor.adapted_reference_batch --configs experiments/views/falcor-pt-spatial-comparison/bistro-interior.json --output runs/my-new-bistro-reference
# The five native scene profiles use the standard reference pipeline:
python -B -m scripts.falcor.reference_batch --configs experiments/views/falcor-pt-spatial-comparison/bistro-exterior.json experiments/views/falcor-pt-spatial-comparison/classroom.json experiments/views/falcor-pt-spatial-comparison/emerald-square.json experiments/views/falcor-pt-spatial-comparison/veach-ajar.json experiments/views/falcor-pt-spatial-comparison/zero-day-measure-seven.json --output runs/my-new-native-references
```

The standard batch preserves its six-view staged-batch status contract: a
five-view invocation finishes with `partial` at batch level, with each requested
view marked `completed` and its eight-seed reference written. The independent
indoor batch has its own completed status and artifacts.

A changed indoor camera can reuse the scene profile for a new qualified
reference run. It cannot be compared with the old fixed EXR without an exact
camera binding. Formal comparison commands and configurable spatial/CGNS
settings are in [README.md](README.md).

Schema-2 reference entry points verify the selected scene profile's pinned
resource/source bytes before rendering and again before accepting outputs.
The native pipeline also requires the actual asset-root closure to match the
inventory exactly; changed textures, extra dependencies or changed loader
sources require a reviewed new profile. Batch resume repeats these checks.
The profile adapter flag, selected runtime and active lock must agree. These
checks do not load fixed EXRs, so a new camera can generate its own reference.
The module and direct-script `reference_runner.py` / `reference_batch.py`
entry points share the same schema-2 loading and budget validation.
