# RTXDI scene profiles

Profiles: [Cornell](cornell-box.json), [Arcade](arcade.json),
[Bistro](bistro.json), [BistroMirror](bistro-mirror.json), [Zero-Day Measure One](zero-day-measure-one.json),
[Zero-Day Measure Seven](zero-day-measure-seven.json),
[San Miguel](san-miguel.json), [Classroom](classroom.json),
[Emerald Square](emerald-square.json), [Sun Temple](sun-temple.json), [Veach Ajar](veach-ajar.json).

San Miguel and Classroom are optional static import previews; they are excluded
from the default baseline scene list. Motion paths are not validated.

Schema 2 separates scene settings from the shared [experiment](../../../experiments/configs/di-reuse.json):
source (repository-relative asset root and entry), camera (position/direction/up/FOV),
motion endpoint, lighting and fixed PNG exposure. Lighting supports the sample's procedural environment, a local HDR/EXR (`environment: file`,
`environment_map` relative to the asset root), or no environment (`none`).
File maps must also appear in the scene wrapper's `environmentMaps`; they are hashed with the assets.
Preview exposure never changes PFM radiance.

To add a scene:

1. Prepare a Donut-compatible glTF or .scene.json and local resources.
2. Copy a profile, set a new ID, source.kind=file, asset root/entry and camera.
   Choose a short motion path clear of geometry; omit source.asset for file sources.
3. Register provenance and backend_configs.rtxdi in [the manifest](../../manifest.yaml).
   Record runtime_assets.sha256 and file_count from the dependency bundle:
   ~~~python
   import sys
   sys.path.insert(0, "scripts/run")
   from experiment.scenes import load_scene, asset_files, bundle_digest
   scene = load_scene("new-scene")
   files = asset_files(scene["source"]["path"], scene["source"]["root"])
   print({"sha256": bundle_digest(files), "file_count": len(files)})
   ~~~
4. Run rtxdi_reuse.py --scene new-scene --check, then a 640×360 motion check;
   inspect the start/end views and converted materials before comparisons.

The dependency check follows scene wrappers, local glTF resources, Donut's DDS
texture preference and referenced IES profiles. Missing files, LFS pointers and
paths outside the configured asset root fail before rendering. GLB is not supported
by this validator yet. Adding a supported scene requires no Python/C++ changes.

## BistroMirror

Uses the upstream composite scene, including the archway/bar mirrors, BrainStem
and sphere-with-holes models. The profile keeps the upstream default camera and
a fixed motion endpoint; it is excluded from the default baseline scenes.
Resource validation does not establish rendered correctness or a benchmark trajectory.

From the repository root:

~~~powershell
python scripts/run/rtxdi_reuse.py --scene bistro-mirror --check
python scripts/run/rtxdi_pdf_viewer.py --scene bistro-mirror --off --indirect RESTIRPT --denoise
~~~

The assets come from the existing RTXDI-Assets checkout; no conversion is needed.
See the manifest for the pinned revision, resource hash and component notices.

## CGNS scene imports

Install the public source versions (archives are pinned in the manifest), then open the existing viewer:

```powershell
python scripts/assets/install_scene.py --scene emerald-square
python scripts/assets/install_scene.py --scene sun-temple
python scripts/assets/install_scene.py --scene veach-ajar
python scripts/run/build_rtxdi_pdf.py
python scripts/run/rtxdi_pdf_viewer.py --scene emerald-square --off --denoise
```

Use `--scene sun-temple` for the temple. For Veach Ajar, whose room relies on indirect lighting:

```powershell
python scripts/run/rtxdi_pdf_viewer.py --scene veach-ajar --off --indirect RESTIRPT --denoise
```

`--indirect` selects existing RTXDI transport; `--denoise` enables NRD RELAX and TAA for viewing.
These options do not change controlled experiment defaults. Close the viewer before opening another.
Emerald uses ORCA Dusk with its HDR and emission x5; Sun Temple retains source HDR,
lamps and emission x1000. Veach Ajar uses the original static Tungsten scene with
its emitter and no added sun/sky. These are public-source adaptations; exact CGNS
camera/material equivalence and motion paths have not been established. They remain optional scenes.

## Zero-Day Measure Seven

The registered profile uses the standard MEASURE_SEVEN FBX variant from the existing
ZeroDay_v1.zip download. The source scene and DynamicCamera are baked at Blender timeline frame 1 after
FBX import (the importer applies its standard +1 frame offset).
The export respects source visibility and excludes hidden construction meshes;
the old glTF included those meshes, which occluded the starting camera.

Open the existing interactive viewer from the repository root:

```powershell
python scripts/run/rtxdi_pdf_viewer.py --scene zero-day-measure-seven --off --indirect RESTIRPT --denoise --resolution 1280 720
```

`--check` validates the profile, complete resource hashes and viewer build without
rendering. Hold the left mouse button to look around; WASD moves the camera.
ReSTIR PT and NRD/TAA are viewing settings. The profile retains the authored camera
FOV, uses the sample's procedural environment and an explicit emissive multiplier.
The motion endpoint equals the start position; no benchmark trajectory is defined.

For a fresh conversion, use the existing pipeline and a new output directory:

```powershell
python scripts/assets/extract_orca.py --archive assets/sources/zero-day/ZeroDay_v1.zip --folder MEASURE_SEVEN --output assets/prepared/zero-day-measure-seven --expected-sha256 a9d040fe9720ee88937778659205fd76bad4499431a37156aaeeba382f08d592
python scripts/assets/convert_scene.py --profile orca --source assets/prepared/zero-day-measure-seven/MEASURE_SEVEN/MEASURE_SEVEN.fbx --output assets/converted/zero-day/measure-seven-viewer/measure-seven.gltf --static-frame 1 --visible-only
```

Both commands require new output directories and publish only after validation.
Skip extraction/conversion when those outputs already exist. The conversion record
contains the frame, visibility policy/excluded mesh count, source camera, FBX hash,
Blender version, opacity decisions and resource hashes. A different re-export must be checked against the registered bundle
using the resource-closure procedure above. The runtime bundle and profile live
outside `tmp/`; disposable diagnostics can be removed without breaking the viewer.
