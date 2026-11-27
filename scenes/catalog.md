# Scene asset sources

The [manifest](manifest.yaml) records the scene IDs, source revisions, hashes, and licenses. Follow the [conversion guide](../scripts/assets/README.md), [RTXDI viewer guide](configs/rtxdi/README.md), or [Falcor benchmark preparation](../experiments/configs/falcor-pt-spatial-comparison/PREPARATION.md).

| Scene | Source | Conversion notes |
| --- | --- | --- |
| Cornell Box, Arcade | [RTXDI Assets](https://github.com/NVIDIA-RTX/RTXDI-Assets) | Use the pinned glTF assets via Git LFS. |
| Bistro, BistroMirror | [RTXDI Assets](https://github.com/NVIDIA-RTX/RTXDI-Assets) · [ORCA Bistro](https://developer.nvidia.com/orca/amazon-lumberyard-bistro) | RTXDI uses the pinned scene files. Falcor uses the adapted RTXDI composite for the interior and the ORCA 5.2 loader for the exterior. |
| Classroom | [Blender Classroom](https://download.blender.org/demo/test/classroom.zip) | Convert to glTF. Source lamps and emissive overrides are restored, with baked portal lighting and approximate PBR materials. |
| Emerald Square | [ORCA Emerald Square](https://developer.nvidia.com/orca/nvidia-emerald-square) | Convert the v4.1 Dusk scene. Keep the source HDR and restore emissive strength in Falcor. |
| San Miguel | [McGuire San Miguel 2.1](https://casual-effects.com/g3d/data10/research/model/San_Miguel/San_Miguel.zip) | Convert the low-poly OBJ to glTF with alpha cutouts and approximate PBR materials. |
| Sun Temple | [ORCA Sun Temple](https://developer.nvidia.com/ue4-sun-temple) | Convert the public v4 scene with its source HDR and lamps. |
| Veach Ajar | [Bitterli Rendering Resources](https://benedikt-bitterli.me/resources/) | Convert the Tungsten scene with its original camera and emitter. Conductor and glass materials are approximate. |
| Zero-Day Measure One, Measure Seven | [ORCA Zero-Day](https://developer.nvidia.com/orca/beeple-zero-day) | Convert FBX and DDS to glTF. For Measure Seven, bake Blender frame 1 with the authored camera and export only visible geometry. |
