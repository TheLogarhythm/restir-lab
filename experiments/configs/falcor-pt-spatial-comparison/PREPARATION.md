# Prepare the six Falcor views

Run the commands in PowerShell at the repository root. The [scene lock](scene-inputs-v2.json) binds each camera preset to a scene profile, resource inventory and expected runtime. Fixed references also bind the camera, resolution and transport. A changed scene, runtime, camera or transport target needs a matching qualified reference. [Camera presets](../../views/falcor-pt-spatial-comparison/) · [Scene profiles](../../scenes/falcor-pt-spatial-comparison/) · [Reference catalog](../../references/README.md)

| View | Scene and loader |
| --- | --- |
| Bistro Interior | RTXDI glTF composite, `scenes/configs/falcor/bistro-gltf/adapted.pyscene` |
| Bistro Exterior | ORCA Bistro 5.2, `BistroExterior.pyscene` |
| Classroom | Converted Blender scene, `scenes/configs/falcor/classroom-reference.pyscene` |
| Emerald Square | Converted ORCA 4.1 Dusk, `scenes/configs/falcor/emerald-square-converted-reference.pyscene` |
| Veach Ajar | Converted Tungsten scene, `scenes/configs/falcor/veach-ajar-reference.pyscene` |
| Zero Day Measure Seven | Visible geometry at source frame 1, `scenes/configs/falcor/zero-day-measure-seven-reference.pyscene` |

The active lock is `scene-inputs-v2.json`. The older lock and monolithic `*-reference.json` names serve as validated aliases and historical records.

## Dependencies

Use the pinned Falcor 9.0 Release build with Visual Studio 2022 and Windows SDK `10.0.22621.0`. The recorded conversions used Blender 5.2.0 LTS and glTF exporter 5.2.39. The glTF runtime also needs the matching Falcor import libraries, Packman Python 3.10 and CUDA 12.6 development headers. Exact benchmark reuse requires assets and runtime receipts that match the locked hashes. A regenerated input with different bytes needs a qualified profile and reference binding. [Falcor build guide](../../../renderers/falcor/README.md) · [Dependency pins](../../../renderers/falcor/integration.json) · [Asset sources and hashes](../../../scenes/manifest.yaml)

~~~powershell
python -m pip install -r scripts/assets/requirements.txt
python -m pip install -r scripts/falcor/requirements.txt
$blender = 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe'
~~~

## Scene assets

### Bistro Interior

Use the full pinned RTXDI glTF scene, including the Bistro and BrainStem models, exterior props, lights and environment. The sky receipt expects the pinned RTXDI and Donut text sources with CRLF line endings. The sky builder verifies the generated EXR. The indoor scene uses `DontOptimizeMaterials` and the v3 composite runtime.

~~~powershell
git -c core.autocrlf=true submodule update --init --recursive
git -C renderers/rtxdi/Assets/Media lfs pull
python -B -m scripts.falcor.prepare_bistro_sky_asset
~~~

### Bistro Exterior

Use the ORCA `Bistro_v5_2.zip` and the original exterior loader, with HDR intensity 10. Exact replay also requires the matching `source-manifest.json` beside the extracted folder.

~~~powershell
python -B scripts/assets/extract_orca.py --archive assets/sources/bistro/Bistro_v5_2.zip --folder Bistro_v5_2 --output assets/prepared/bistro-orca-v5-2 --expected-sha256 0d50e3c724c6c5da19f8eb99ad3f53e36fec37ffa2df9621f9ccf0603f3934e1
~~~

### Classroom, Emerald Square, Veach Ajar and Zero Day

Verify `classroom.zip` against SHA-256 `0f0ecc58d45f12b2f4272a53e2d8e69135518e16e956b118f10c20d8dcfdf5e6`. Extract it to `assets/prepared/classroom/` with `classroom/classroom.blend` inside. The wrapper supplies the recorded emission and lighting adjustments. The Emerald installer uses ORCA Dusk and the converted scene wrapper. The Veach installer uses the original Tungsten scene. The Zero Day export keeps visible geometry at source frame 1 and uses the wrapper's derelict-overpass environment.

~~~powershell
python -B scripts/assets/convert_scene.py --profile classroom --source assets/prepared/classroom/classroom/classroom.blend --output assets/converted/classroom/classroom.gltf --texture-size 512 --blender $blender
python -B scripts/assets/install_scene.py --scene emerald-square --blender $blender
python -B scripts/assets/install_scene.py --scene veach-ajar
python -B scripts/assets/extract_orca.py --archive assets/sources/zero-day/ZeroDay_v1.zip --folder MEASURE_SEVEN --output assets/prepared/zero-day-measure-seven --expected-sha256 a9d040fe9720ee88937778659205fd76bad4499431a37156aaeeba382f08d592
python -B scripts/assets/convert_scene.py --profile orca --source assets/prepared/zero-day-measure-seven/MEASURE_SEVEN/MEASURE_SEVEN.fbx --output assets/converted/zero-day/measure-seven-viewer/measure-seven.gltf --static-frame 1 --visible-only --blender $blender
~~~

## Runtime and input checks

Install the pinned Falcor build with `.\scripts\falcor\setup.ps1 -Jobs 4` when needed. Verify the standard runtime with the reference sampler patch and the indoor composite runtime with its material and importer plugins.

~~~powershell
.\scripts\falcor\setup.ps1 -CheckOnly
python -B -c "from scripts.falcor import reference_runtime; reference_runtime.verify()"
python -B -m scripts.falcor.prepare_gltf_composite_runtime_v3 --verify
python -B -m scripts.falcor.scene_inputs
python -B -m scripts.falcor.scene_inputs --check-assets --check-runtimes
python -B -m scripts.falcor.scene_inputs --check-assets --check-runtimes --check-reference-images
~~~

The last check also verifies the six 16,384-spp EXRs at their catalog paths. Capture uses the catalog metadata, while analysis checks the reference images. To build a new standard runtime, use `python -B -m scripts.falcor.reference_runtime`. To compile the two indoor adapter DLLs separately, run `python -B -m scripts.falcor.prepare_adapted_plugins --output build/my-new-adapted-plugins`. Qualify new binary receipts before binding them to a scene and reference set. [Runtime adapter](../../../scripts/falcor/prepare_gltf_composite_runtime_v3.py)

For a historical input migration audit, run `python -B -m scripts.falcor.verify_scene_inputs_migration` with the original evidence.

## Run comparisons

The benchmark uses 1920×1080, 1 spp, ten-bounce transport, one round of unpaired point-reservoir reuse, one spatial neighbor at radius 30, and lighting history 20. The suite runs four seeds and a separate timing sequence. Follow the [six-view benchmark commands](../../../docs/reproductions/pt-6-views-spatial-compare.md) for final measurements. [Shared method settings](restir-pt-spatial-comparison.json) · [Suite schedule](../pt-6-views-spatial-compare.json)

For smaller comparisons, the shared campaign uses 40 warm-up frames and eight captures. Use the second command for a one-view ordinary temporal-on/off control.

~~~powershell
python -B -m scripts.falcor.spatial_campaign --experiment-config experiments/configs/falcor-pt-spatial-comparison/restir-pt-spatial-comparison.json --output runs/my-spatial-comparison
python -B -m scripts.falcor.spatial_campaign --temporal-contrast --view classroom/view-a --output runs/my-classroom-temporal-contrast
~~~

Use a new output directory for changed settings. `--retry-failed` reuses the same verified campaign and creates new attempts for failed jobs.

## New reference captures

Use an approved budget and a fresh output path. These entry points average eight independent 1,024-spp streams at 1920×1080. Their 8,192-spp result requires a separately approved extension and qualification to replace a 16,384-spp catalog reference.

~~~powershell
$views = 'experiments/views/falcor-pt-spatial-comparison'
python -B -m scripts.falcor.adapted_reference_batch --configs "$views/bistro-interior.json" --output runs/my-new-bistro-reference
python -B -m scripts.falcor.reference_batch --configs "$views/bistro-exterior.json" "$views/classroom.json" "$views/emerald-square.json" "$views/veach-ajar.json" "$views/zero-day-measure-seven.json" --output runs/my-new-native-references
~~~

The native invocation requests five views, so its batch status is `partial` with each successful requested view marked `completed`. The runners verify the scene, source assets, runtime and transport before capture and again before accepting output. Resume repeats those checks.
