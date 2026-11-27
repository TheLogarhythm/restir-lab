# RTXDI scene profiles

The [manifest](../../manifest.yaml) maps each scene ID to its profile and pins the asset bundle. Profiles specify the asset entry, camera, motion endpoint, lighting, and preview exposure. The [experiment configuration](../../../experiments/configs/di-reuse.json) supplies shared render settings.

Validate the profile and its asset dependencies from the repository root:

~~~powershell
python -B scripts/run/rtxdi_reuse.py --scene cornell-box --check
~~~

Replace `cornell-box` with any registered ID. To register a scene, prepare a Donut-compatible glTF or `.scene.json`, copy a profile, and add the source and `backend_configs.rtxdi` entry to the manifest. Record the dependency bundle's SHA-256 and file count:

~~~python
import sys

sys.path.insert(0, "scripts/run")
from experiment.scenes import asset_files, bundle_digest, load_scene

scene = load_scene("new-scene")
files = asset_files(scene["source"]["path"], scene["source"]["root"])
print({"sha256": bundle_digest(files), "file_count": len(files)})
~~~

Run `--check`, then inspect a small motion preview before comparing the new scene. File-backed HDR or EXR environments must be listed in the scene wrapper's `environmentMaps`. The dependency validator follows referenced DDS textures and IES profiles and supports glTF rather than GLB.

## BistroMirror

The optional profile uses the pinned upstream mirror composite and its default camera.

~~~powershell
python -B scripts/run/rtxdi_reuse.py --scene bistro-mirror --check
python -B scripts/run/rtxdi_pdf_viewer.py --scene bistro-mirror --off --indirect RESTIRPT --denoise
~~~

## CGNS scene imports

~~~powershell
python -B scripts/assets/install_scene.py --scene emerald-square
python -B scripts/assets/install_scene.py --scene sun-temple
python -B scripts/assets/install_scene.py --scene veach-ajar
python -B scripts/run/build_rtxdi_pdf.py
python -B scripts/run/rtxdi_pdf_viewer.py --scene emerald-square --off --denoise
python -B scripts/run/rtxdi_pdf_viewer.py --scene veach-ajar --off --indirect RESTIRPT --denoise
~~~

Use the Emerald Square viewer command with `--scene sun-temple` for Sun Temple. Emerald Square keeps the ORCA Dusk HDR and emission ×5. Sun Temple keeps its HDR and lamps with emission ×1000. Veach Ajar keeps its original emitter and relies on indirect lighting. These imports use public source versions, with approximate materials for Veach Ajar. `--denoise` enables NRD RELAX and TAA for viewing. [Conversion details](../../../scripts/assets/README.md)

## Zero-Day Measure Seven

Bake the imported Blender frame 1 with its authored camera. Use `--visible-only` to exclude hidden construction meshes that obstruct the camera. For a fresh conversion, use new output paths and validate the result against the manifest.

~~~powershell
python -B scripts/assets/extract_orca.py --archive assets/sources/zero-day/ZeroDay_v1.zip --folder MEASURE_SEVEN --output assets/prepared/zero-day-measure-seven --expected-sha256 a9d040fe9720ee88937778659205fd76bad4499431a37156aaeeba382f08d592
python -B scripts/assets/convert_scene.py --profile orca --source assets/prepared/zero-day-measure-seven/MEASURE_SEVEN/MEASURE_SEVEN.fbx --output assets/converted/zero-day/measure-seven-viewer/measure-seven.gltf --static-frame 1 --visible-only
python -B scripts/run/rtxdi_pdf_viewer.py --scene zero-day-measure-seven --off --indirect RESTIRPT --denoise --resolution 1280 720
~~~

The viewer profile uses the sample's procedural environment and a static camera preset. Run the viewer with `--check` to validate the profile, assets, and build before opening it.
