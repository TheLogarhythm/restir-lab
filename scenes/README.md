# Scenes

| Scene | Status | Role |
| --- | --- | --- |
| [Cornell Box](https://github.com/NVIDIA-RTX/RTXDI-Assets/tree/main/CornellBox) | Acquired; FullSample capture verified | Small direct-lighting case |
| [Arcade](https://github.com/NVIDIA-RTX/RTXDI-Assets/tree/main/Arcade) | Acquired; visual check pending | Emissive and normal-map case |
| [Bistro](https://github.com/NVIDIA-RTX/RTXDI-Assets/tree/main/bistro) | Acquired; FullSample 1280×720 capture verified | Larger scene for comparison |
| [Zero-Day](https://developer.nvidia.com/orca/beeple-zero-day) | Measure One RTXDI capture verified; Measure Seven converted, runtime pending | Many emissive lights |

The pinned RTXDI asset submodule uses Git LFS. [The manifest](manifest.yaml) records registered scenes; [the catalog](catalog.md) tracks other asset sources. The asset repository has a [root MIT license](https://github.com/NVIDIA-RTX/RTXDI-Assets/blob/main/LICENSE), while [Bistro](https://developer.nvidia.com/orca/amazon-lumberyard-bistro) and [Zero-Day](https://developer.nvidia.com/orca/beeple-zero-day) specify CC BY 4.0. Keep scene-specific settings in `configs/` and record conversions.
