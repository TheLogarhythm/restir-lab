# Scenes

**Shortlist checked: 2026-09-19.** Use these three public scenes for the proposed DI study. Their files are available in [RTXDI Assets](https://github.com/NVIDIA-RTX/RTXDI-Assets), which reduces expected preparation work for the preferred backend. These are candidates: no assets have been downloaded, imported, or benchmarked.

| Scene and source | Available entry | Proposed experiment role |
| --- | --- | --- |
| [Cornell Box](https://github.com/NVIDIA-RTX/RTXDI-Assets/tree/main/CornellBox) | `CornellBox/CornellBox.gltf` | Small correctness case: validate direct lighting, reservoir normalization, and reuse switches before complex scenes |
| [Bistro](https://github.com/NVIDIA-RTX/RTXDI-Assets/tree/main/bistro) | `bistro/bistro.gltf`; repository also supplies `bistro-rtxdi.scene.json` | Complex-scene comparison: choose one exterior view and a short camera move across occluding geometry |
| [Arcade](https://github.com/NVIDIA-RTX/RTXDI-Assets/tree/main/Arcade) | `Arcade/Arcade.gltf`; includes emissive and normal-map textures | Probe reuse across material/normal changes and localized emitters; choose a short camera move past cabinet edges |

The experiment roles are our proposed uses, not validated performance claims. Start with Cornell Box, then Arcade, then Bistro. Use one static view per scene and at most two short trajectories in the initial suite. Keep lighting identical across methods, use direct-only references, and record any light, material, or geometry edits. Check that Arcade's emission and normal maps survive import and that Bistro fits the available GPU memory before fixing the suite.

## Acquisition and attribution

RTXDI's [setup instructions](https://github.com/NVIDIA-RTX/RTXDI#building-and-running-the-sample-apps) identify `Assets/Media` as the asset submodule and require Git LFS for the actual files. Pin the asset revision together with the selected renderer; a checkout containing only LFS pointers is not a usable scene.

The asset repository has a [root MIT license](https://github.com/NVIDIA-RTX/RTXDI-Assets/blob/main/LICENSE). Preserve that notice and inspect asset-specific attribution when acquiring the files. Bistro's [original ORCA page](https://developer.nvidia.com/orca/amazon-lumberyard-bistro) credits Amazon Lumberyard and specifies CC BY 4.0; retain that attribution for the adapted asset as well. Do not infer that the repository's root license replaces third-party asset terms.

[Bitterli's scene collection](https://benedikt-bitterli.me/resources/) remains a fallback if the shortlist fails import or resource checks. Its Tungsten, Mitsuba, and pbrt variants require conversion and material validation for this project, so it is not the first acquisition route.

## Registration

`manifest.yaml` remains empty until assets are acquired and verified. It uses JSON syntax, a valid YAML subset. For each registered scene, provide `id`, `source_url`, `source_revision`, `sha256`, `license`, `local_path`, `conversion`, `modifications`, and `backend_configs`. Use relative paths and identify the archive or bundle being hashed.

Keep camera/material/light settings in `configs/`, deterministic motion in `trajectories/`, generators in `procedural/`, and optional Blender sources in `authoring/`. Keep large binaries in ignored local asset storage.
