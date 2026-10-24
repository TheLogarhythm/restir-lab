# Scene asset sources

Source survey: 2026-09-23; San Miguel/Classroom import checks: 2026-10-02. Sizes are source ZIP bytes except Bistro (Git LFS payloads).

## Ready for the current RTXDI sample

| Scene  | Download                                                                    | Format | Size                         | Note                                                                                                                                                    |
| ------ | --------------------------------------------------------------------------- | ------ | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Bistro | [RTXDI Assets](https://github.com/NVIDIA-RTX/RTXDI-Assets/tree/main/bistro) | glTF   | ~2.27 GiB (393 LFS payloads) | Acquired; FullSample 1280×720 capture passed. [Original ORCA terms](https://developer.nvidia.com/orca/amazon-lumberyard-bistro): CC BY 4.0. |
| Zero-Day Measure One | [ORCA](https://developer.nvidia.com/orca/beeple-zero-day) | FBX/DDS → glTF | 1.14 GB source ZIP (shared) | CC BY 4.0; RTXDI capture passed with no texture warnings; fidelity review pending. [Conversion](../scripts/assets/README.md). |
| Zero-Day Measure Seven | [ORCA](https://developer.nvidia.com/orca/beeple-zero-day) | FBX/DDS → static glTF | same source ZIP | Interactive viewer verified at 1280×720 with ReSTIR PT + NRD/TAA. Source frame 1 and camera retained; 1,708 source-hidden meshes excluded. [Open and prepare](configs/rtxdi/README.md#zero-day-measure-seven). |

Measure Seven acceptance (2026-10-24): the existing interactive build produced a
renderer-owned 1280×720 framebuffer at frame 64 and exited normally. This is a
scene-import check, with the sample procedural environment and emissive scale 1,
not a quantitative comparison. Hidden construction geometry in the old all-object
export blocked the camera. The new conversion explicitly bakes imported Blender frame 1 with
`--visible-only`; genuine alpha-bearing materials retain their alpha modes.
The active bundle contains 5,284,343 instantiated triangles and 10,321 emissive
triangles; these runtime counts differ from the source README and are not claimed
as its unique-mesh statistics. Logs and a viewing image are preserved under
`build/measure-seven-registration-20261024/acceptance/`; temporary probes are under
`tmp/measure-seven-20261024/`.

San Miguel and Classroom are optional imports, excluded from the default baseline
scene list. Both passed static 1280×720 previews; no baseline evaluation or motion
validation was performed. [Conversion and limitations](../scripts/assets/README.md).

| Scene | Download | Format | Size | Import details |
| --- | --- | --- | --- | --- |
| San Miguel 2.1 (low-poly) | [McGuire ZIP](https://casual-effects.com/g3d/data10/research/model/San_Miguel/San_Miguel.zip) | OBJ/PNG → glTF | 535.5 MB | Research/educational use with attribution; PNG cutouts restored, approximate PBR; no local lights added. |
| Classroom | [Blender ZIP](https://download.blender.org/demo/test/classroom.zip) | Blender → glTF | 70.3 MB | Christophe Seux, CC0; source lamps and emissive material overrides restored; use `.scene.json`. Baked portal/PBR approximations; no invented local lights. |

## Additional CGNS scene imports

| Scene | Public version | Status / limits |
| --- | --- | --- |
| Emerald Square | ORCA v4.1 Dusk, CC BY-NC-SA 3.0 | Source camera, HDR and emission x5; interactive viewer checked. |
| Sun Temple | ORCA v4, CC BY-NC-SA 4.0 | Source camera, HDR, lamps and emission x1000; interactive viewer checked. |
| Veach Ajar | Bitterli Tungsten, CC0 | Original static camera and emitter; approximate conductor/glass materials; interactive viewer checked. |

[Install and open](configs/rtxdi/README.md#cgns-scene-imports). Source hashes and notices
are registered in [the manifest](manifest.yaml). These public versions are not confirmed
to match CGNS's scene modifications. Motion and quantitative comparisons remain unvalidated.

Acceptance (2026-10-21): all three ran in interactive mode at 1280x720 and exited
normally after renderer-owned framebuffer captures. NRD/TAA previews were inspected;
Veach Ajar passed ReSTIR PT, Sun Temple retained its source directional light and
rendered with transparent geometry disabled, and Cornell Box passed a regression check.
Local images/logs: `build/scene-viewer-acceptance/review-20261021/`.
Keyboard/mouse interaction was not automatically verified.

## Free source; RTXDI conversion/import needed

| Scene              | Download                                                                                                                             | Format          | Size | Note                                                                                                                   |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------ | --------------- | ---- | ---------------------------------------------------------------------------------------------------------------------- |
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
