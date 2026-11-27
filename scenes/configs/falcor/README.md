# Falcor scene loaders

## Cornell Box smoke test

From the repository root, after [building Falcor](../../../renderers/falcor/README.md), run:

~~~powershell
python -B scripts/falcor/run.py --mode restir-pt --output runs/my-falcor-smoke
~~~

The runner imports the pinned RTXDI Cornell Box glTF and sets the camera from the [smoke-test configuration](../../../experiments/configs/falcor-sanity-check.json).

## Spatial-comparison scenes

The [preparation guide](../../../experiments/configs/falcor-pt-spatial-comparison/PREPARATION.md) lists the loaders, asset conversion commands, and runtime checks for all six views. Classroom uses `gallery-lights.py`, Emerald Square uses the converted ORCA Dusk scene, and Bistro Interior uses the [adapted glTF loader](bistro-gltf/adapted.pyscene) with its scene plan, descriptors, and sky bake receipt. Bistro Exterior uses the ORCA 5.2 exterior loader.

The [experiment scene profiles](../../../experiments/scenes/falcor-pt-spatial-comparison/) link each loader to its inventory. The [camera presets](../../../experiments/views/falcor-pt-spatial-comparison/) define the views separately. Verify the locked scene inputs with:

~~~powershell
python -B -m scripts.falcor.scene_inputs --check-assets
~~~
