# Falcor reference catalog

The six benchmark references are scene-linear 1920×1080 EXRs at 16,384 spp. The catalog binds each file's repository-relative path and SHA-256 to its camera, scene, runtime, resolution and transport. The scene lock pins camera presets, reusable profiles and input inventories. [Reference catalog](falcor-pt-spatial-comparison-16384.json) · [Scene lock](../configs/falcor-pt-spatial-comparison/scene-inputs-v2.json)

Place matching EXRs at the catalog paths before analysis. Method capture needs the catalog metadata and verified scene/runtime inputs. Run the full preflight to check the files and their bindings before analysis.

~~~powershell
python -B -m scripts.falcor.scene_inputs --check-assets --check-runtimes --check-reference-images
~~~

A camera or transport change requires a matching reference. Use the [six-view preparation guide](../configs/falcor-pt-spatial-comparison/PREPARATION.md) for assets, runtime checks and commands for new reference captures.
