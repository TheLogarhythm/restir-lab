# ReSTIR Spatial Reuse: Implementation and Evaluation

This HKUST COMP5411 project compares ordinary spatial reuse, PDF Similarity, and compatibility-guided neighbor selection (CGNS) in Falcor 9.0. The earlier RTXDI experiments focus on direct illumination.

![Six reference views: Bistro Interior, Bistro Exterior, Classroom, Emerald Square, Veach Ajar, and Zero Day Measure Seven](results/figures/benchmark-scenes.jpg)

The six benchmark views, shown as 16,384-spp reference renders. [Scene credits](THIRD_PARTY.md#scene-assets-and-fonts)

## ReSTIR PT results

At 1920 × 1080 and one sample per pixel, all three methods use temporal reuse and are evaluated against 16,384-spp references.

- **CGNS** achieved the lowest whole-image SMAPE in all 24 paired comparisons across six fixed views. It reduced error by 3.9–22.7% relative to ordinary reuse and added about 4–6% to GPU frame time in the five timed views.
- **PDF Similarity** reduced error by 2.1% in Bistro Exterior, nearly tied ordinary reuse in Bistro Interior, and increased error by 5.6% in Emerald Square.
- CGNS lowered temporal noise covariance and raised spatial covariance in every fixed view.

![Emerald Square per-pixel SMAPE differences for CGNS minus original reuse and PDF Similarity minus original reuse](results/figures/smape-improvement.png)

Both maps subtract original reuse pixel by pixel. Blue marks lower error and red marks higher error, with the same ±20 percentage-point display scale. [Six-view results and CSVs](results/summaries/falcor-pt-spatial-reuse/README.md)

![Emerald Square reference and matching crops for ordinary reuse, PDF Similarity, CGNS, and the reference](results/figures/emerald-square-comparison.png)

The marked Emerald Square crop illustrates a local CGNS improvement. [Bistro Interior comparison](results/figures/bistro-interior-comparison.png)

[Bistro Exterior walkthrough](results/figures/bistro-exterior-trajectory.mp4) · [Zero Day Measure Seven walkthrough](results/figures/zero-day-trajectory.mp4) · [Camera trajectories](scenes/trajectories/README.md)

## Project guide

- Prepare the pinned renderer builds and scene inputs. [Setup](docs/setup.md) · [Scene catalogue](scenes/README.md)
- Reproduce the six-view comparison or inspect the saved results. [Falcor methods](docs/reproductions/falcor-pt.md) · [Benchmark protocol](docs/reproductions/pt-6-views-spatial-compare.md) · [Metrics](docs/metrics.md)
- Explore the earlier direct-lighting work. [RTXDI baseline](results/summaries/di-baseline/README.md) · [RTXDI experiments](docs/reproductions/rtxdi.md)
- Read the write-up and presentation materials. [Report source](writing/course/report/main.tex) · [Final presentation](writing/final/README.md) · [Literature guide](docs/literature/README.md)

## Live Falcor demo

With the Windows runtime and scene assets prepared, launch the demo from PowerShell at the repository root.

```powershell
.\run-demo.ps1 -Scene Classroom
```

Use **Graphs** to switch scenes and spatial reuse methods, or select Raw, Accumulation, or NRD. Run `.\run-demo.ps1 -PrecompileShaders` to prepare shaders for all seven presets. The shader-cache replay exercised all 63 scene, method, and display combinations. [Demo setup](docs/setup.md#falcor-and-live-demo)

[Contributing](CONTRIBUTING.md) · [Third-party sources](THIRD_PARTY.md) · [License](LICENSE)
