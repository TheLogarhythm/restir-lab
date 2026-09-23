# Scene asset sources

Checked 2026-09-23. Bistro size sums Git LFS payloads; Zero-Day and San Miguel sizes are measured ZIP bytes.

## Ready for the current RTXDI sample

| Scene  | Download                                                                    | Format | Size                         | Note                                                                                                                                                    |
| ------ | --------------------------------------------------------------------------- | ------ | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Bistro | [RTXDI Assets](https://github.com/NVIDIA-RTX/RTXDI-Assets/tree/main/bistro) | glTF   | ~2.27 GiB (393 LFS payloads) | Acquired; FullSample 1280×720 capture passed. [Original ORCA terms](https://developer.nvidia.com/orca/amazon-lumberyard-bistro): CC BY 4.0. |
| Zero-Day Measure One | [ORCA](https://developer.nvidia.com/orca/beeple-zero-day) | FBX/DDS → glTF | 1.14 GB source ZIP (shared) | CC BY 4.0; RTXDI capture passed with no texture warnings; fidelity review pending. [Conversion](../scripts/assets/README.md). |

## Free source; RTXDI conversion/import needed

| Scene              | Download                                                                                                                             | Format          | Size | Note                                                                                                                   |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------ | --------------- | ---- | ---------------------------------------------------------------------------------------------------------------------- |
| San Miguel         | [pbrt-v4](https://github.com/mmp/pbrt-v4-scenes/tree/master/sanmiguel/) or [McGuire archive](https://casual-effects.com/g3d/data10/) | pbrt or OBJ/PNG | 535.5 MB ZIP | McGuire low-poly draft glTF exported; lighting and materials need validation. |
| Zero-Day Measure Seven | [ORCA](https://developer.nvidia.com/orca/beeple-zero-day) | FBX/DDS → glTF | same source ZIP | Extracted and converted; current RTXDI capture timed out after texture loading. Source README emissive count differs by eight. |
| Emerald Square     | [ORCA](https://developer.nvidia.com/orca/nvidia-emerald-square)                                                                      | FBX/Falcor      | —    | CC BY-NC-SA 3.0; large scene.                                                                                          |
| Sun Temple         | [ORCA](https://developer.nvidia.com/ue4-sun-temple)                                                                                  | FBX/Falcor      | —    | CC BY-NC-SA 4.0.                                                                                                       |
| Veach Ajar         | [Bitterli ZIP](https://benedikt-bitterli.me/resources/tungsten/veach-ajar.zip)                                                       | Tungsten        | —    | Author-created/public domain; [Falcor demo](https://github.com/DQLin/ReSTIR_PT) also exists.                           |
| Wooden Staircase   | [Bitterli ZIP](https://benedikt-bitterli.me/resources/tungsten/staircase.zip)                                                        | Tungsten        | —    | Check ZIP license; [third-party glTF](https://github.com/ErfanMo77/gltf-research-scenes) is an approximate conversion. |
| Modern Living Room | [Bitterli ZIP](https://benedikt-bitterli.me/resources/tungsten/living-room-3.zip)                                                    | Tungsten        | —    | Check ZIP license; [third-party glTF](https://github.com/ErfanMo77/gltf-research-scenes) is an approximate conversion. |

## Paid or restricted

| Scene             | Download/purchase                                                                                                    | Format        | Size                                                                           | Note                                                                   |
| ----------------- | -------------------------------------------------------------------------------------------------------------------- | ------------- | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------- |
| Burger Restaurant | [Astuff / TurboSquid](https://www.turbosquid.com/3d-models/burger-restaurant-3d-model/1021436)                       | FBX/OBJ       | 74 MB FBX ([listing](https://free3d.com/3d-model/burger-restaurant-8691.html)) | Editorial use only; conversion needed.                                 |
| Subway            | [SilverTM / CGTrader](https://www.cgtrader.com/3d-models/interior/other/subway-c1184128-4c95-4199-a651-32f65a287948) | FBX/Unreal    | 926 MB FBX (seller listing)                                                    | Paid; exact paper revision unconfirmed; Unreal setup needs conversion. |
| Paris Opera House | [GoldSmooth / TurboSquid](https://www.turbosquid.com/3d-models/3d-model-palais-garnier-interior-paris-opera-1309277) | 3ds Max/V-Ray | —                                                                              | Paid, editorial use only; research conversion unavailable.             |
| Carousel          | [carousel_world / TurboSquid](https://www.turbosquid.com/3d-models/3d-carousel-carrousel/932444)                     | FBX/OBJ       | —                                                                              | Paid; match to the paper's version unconfirmed.                        |

## Standalone demo; current setup unsupported

| Scene                             | Download                                                                                                                               | Format                   | Size | Note                                                                                                                                                                         |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ | ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| NVIDIA Amusement Park Demo (2025) | [NVIDIA source project and binary](https://developer.nvidia.com/game-engines/unreal-engine/rtx-branch/technology-showcase/get-started) | Unreal 5.4 NvRTX project | —    | Different from the 2020 paper scene. NVIDIA requires an RTX 50-series GPU and driver 572.16+; current RTXDI import, archive integrity, and asset reuse terms are unverified. |

## No confirmed source

| Scene                       | Reference                                                   | Size | Note                                                                                                                                                                                       |
| --------------------------- | ----------------------------------------------------------- | ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Amusement Park (2020 paper) | [ReSTIR project page](https://benedikt-bitterli.me/restir/) | —    | No original scene download found. The [later NVIDIA Unreal demo](https://developer.nvidia.com/game-engines/unreal-engine/rtx-branch/technology-showcase/get-started) is a different asset. |

Keep third-party binaries in ignored `assets/`. Register a scene in `manifest.yaml` only after acquisition and hash/license checks.
