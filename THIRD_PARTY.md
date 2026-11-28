# Third-party materials

## Renderers and method sources

| Component | Version and notice |
| --- | --- |
| RTXDI | [v3.1.0](https://github.com/NVIDIA-RTX/RTXDI/tree/a6efab966b7c3b272da0461578eb56ac61c7cbff) · NVIDIA RTX SDKs License |
| Falcor | [9.0 at `759aad0`](https://github.com/NVIDIAGameWorks/Falcor/tree/759aad033ff610fb0d82c74f7e0a508d0096d5f2) · [BSD-3-Clause-style notice](https://github.com/NVIDIAGameWorks/Falcor/blob/759aad033ff610fb0d82c74f7e0a508d0096d5f2/LICENSE.md) |

Submodules, dependencies, and derived source files retain their upstream notices. The RTXDI build pins DXC `v1.8.2505.1`, DLSS `a8ed84e2d1cc1efa7bef63fb9394be6cb06c0d74`, and MathLib `v11`. Falcor pins its build dependencies through [Packman](https://github.com/NVIDIAGameWorks/Falcor/blob/759aad033ff610fb0d82c74f7e0a508d0096d5f2/dependencies.xml) and the [integration record](renderers/falcor/integration.json).

- Falcor supplies the native PathTracer and ReSTIR PT. The live demo combines the two project PT adaptations in a private runtime and uses NVIDIA Real-Time Denoisers (NRD) through a graph based on Falcor's [PathTracerNRD example](https://github.com/NVIDIAGameWorks/Falcor/blob/759aad033ff610fb0d82c74f7e0a508d0096d5f2/scripts/PathTracerNRD.py). The project’s private overlays extend Mogwai’s Graphs panel, reuse compatible Slang sessions and a shared PathTracer shader layout, and keep the NRD branch available for subsequent display changes. The San Miguel sky is a project port of Donut's procedural sky.
- The RTXDI DI and Falcor PT versions of PDF Similarity are independent implementations based on Tokuyoshi (2023). The PT version uses first-hop direction statistics and an effective-confidence rule based on Lin et al.'s GRIS formulation. [Tokuyoshi](https://doi.org/10.1145/3585501) · [Lin et al.](https://doi.org/10.1145/3528223.3530158) · [DI implementation](docs/reproductions/rtxdi.md#pdf-similarity) · [PT implementation](docs/reproductions/falcor-pt.md#pdf-similarity)
- The RTXDI DI and Falcor PT versions of CGNS are independent project adaptations informed by Junkins et al. (2026) and their pinned author code. [Paper](https://doi.org/10.1145/3820024) · [Author code `f28d553`](https://github.com/orion-junkins/ReSTIR-CGNS/tree/f28d553f3b2552b1be829feffea6d1abb1945e1d) · [DI implementation](docs/reproductions/rtxdi.md#cgns) · [PT implementation](docs/reproductions/falcor-pt.md#cgns)
- The RTXDI integration uses pinned NVIDIA transport interfaces for scene loading, emitter indexing, readback, and reference rendering. The visible-GGX sampler follows Heitz (2018), *Sampling the GGX Distribution of Visible Normals*. [Scene patch](scripts/run/rtxdi_external.patch) · [Experiment patch](scripts/run/rtxdi_experiments.patch) · [Readback](scripts/run/rtxdi_experiments/LabExperiment.h) · [Reference shader](scripts/run/rtxdi_experiments/ReferenceSamples.hlsl) · [Donut emissive-strength adapter](scripts/run/rtxdi_emission.py) · [Comparison notes](docs/reproductions/rtxdi.md#fixed-view-di-gi-and-pt-comparison)

## Scene assets and fonts

Source archives, hashes, and conversion details are recorded in the [scene manifest](scenes/manifest.yaml). The project's Tungsten converter follows the [Tungsten WO3 layout and transform conventions](https://github.com/tunabrain/tungsten).

| Asset | Attribution and license |
| --- | --- |
| Cornell Box and Arcade | [RTXDI Assets at `1da7b74`](https://github.com/NVIDIA-RTX/RTXDI-Assets/tree/1da7b749ef0e3fb606ab46dde8e5bfbacd078a02), MIT root notice |
| Bistro and BistroMirror | [Amazon Lumberyard Bistro](https://developer.nvidia.com/orca/amazon-lumberyard-bistro), CC BY 4.0. The [RTXDI Assets composite](https://github.com/NVIDIA-RTX/RTXDI-Assets/blob/1da7b749ef0e3fb606ab46dde8e5bfbacd078a02/bistro_with_mirrors-rtxdi.scene.json) carries the root MIT notice. BrainStem is by Keith Hunter and owned by Smith Micro Software, Inc. Its [bundled notice](https://github.com/NVIDIA-RTX/RTXDI-Assets/blob/1da7b749ef0e3fb606ab46dde8e5bfbacd078a02/BrainStem/README.md) cites Poser Pro EULA clause (g). |
| Zero-Day Measure One and Seven | [NVIDIA ORCA and Beeple](https://developer.nvidia.com/orca/beeple-zero-day), CC BY 4.0 |
| San Miguel 2.1 (low-poly) | Guillermo M. Leal Llaguno, with 2017 updates by Morgan McGuire, Guedis Cardenas, Michael Mara, and Nicholas Hull. Bundled research and educational-use terms require attribution. [McGuire archive](https://casual-effects.com/g3d/data10/) |
| Classroom | Christophe Seux, [Blender demo](https://www.blender.org/download/demo-files/), CC0 |
| Emerald Square (Dusk) | [NVIDIA ORCA](https://developer.nvidia.com/orca/nvidia-emerald-square), Nicholas Hull, Kate Anderson, and Nir Benty, CC BY-NC-SA 3.0 |
| Sun Temple | [Epic Games](https://developer.nvidia.com/ue4-sun-temple), CC BY-NC-SA 4.0 |
| Veach Ajar | [Benedikt Bitterli](https://benedikt-bitterli.me/resources/), CC0/public domain per bundled notice |
| Open Sans | RTXDI Assets `fonts/OpenSans/`, Apache 2.0 per bundled notice |

## Course materials and presentation figures

- The [COMP5411 course site](https://course.cse.ust.hk/comp5411/) supplied the original [proposal and report templates](writing/course/templates/README.md) and [project guidelines](writing/course/guidelines/README.md).
- Illustration credits for the pitch are listed with the slides. The progress presentation uses Tokuyoshi's Figure 2 from *Efficient Spatial Resampling Using the PDF Similarity* (2023). The authors retain copyright, with publication rights licensed to ACM. [Pitch sources](writing/course/slides/sources.md) · [Progress figure record](writing/progress/data/paper-figure.json)
- The final presentation includes a crop of Figure 2 from Junkins et al. (2026), CC BY 4.0. [Presentation figure record on GitHub](https://github.com/TheLogarhythm/restir-lab/blob/main/writing/final/data/cgns-figure2.json)

## ReSTIR Atlas icon

The Atlas uses the [Tabler Prism Light icon](https://github.com/tabler/tabler-icons/blob/main/icons/outline/prism-light.svg) with adapted SVG presentation attributes. Copyright 2020–2026 Paweł Kuna. [MIT license](web/restir-map/public/licenses/tabler-icons-LICENSE.txt)
