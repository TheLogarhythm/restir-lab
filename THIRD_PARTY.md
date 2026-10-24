# Third-party materials

## Course materials

The original `proposal.tex`, `report.tex`, and `projguidelines.pdf` came from the [COMP5411 course webpage](https://course.cse.ust.hk/comp5411/). They are preserved in `writing/course/templates/` and `writing/course/guidelines/`; working copies are under `writing/course/`.

## Renderer and assets

| Material | Source and revision | License |
| --- | --- | --- |
| RTXDI | [v3.1.0](https://github.com/NVIDIA-RTX/RTXDI/tree/a6efab966b7c3b272da0461578eb56ac61c7cbff) | NVIDIA RTX SDKs License; submodule unchanged |
| Cornell Box and Arcade | [RTXDI Assets](https://github.com/NVIDIA-RTX/RTXDI-Assets/tree/1da7b749ef0e3fb606ab46dde8e5bfbacd078a02) | Root MIT notice; [file hashes](scenes/manifest.yaml) |
| Bistro | [RTXDI Assets](https://github.com/NVIDIA-RTX/RTXDI-Assets/tree/1da7b749ef0e3fb606ab46dde8e5bfbacd078a02/bistro); [original ORCA source](https://developer.nvidia.com/orca/amazon-lumberyard-bistro) | ORCA scene CC BY 4.0; [bundle hash](scenes/manifest.yaml) |
| Zero-Day Measure One/Seven | [NVIDIA ORCA / Beeple](https://developer.nvidia.com/orca/beeple-zero-day) | CC BY 4.0; source and conversions remain in ignored `assets/` |
| San Miguel 2.1 (low-poly) | [McGuire archive](https://casual-effects.com/g3d/data10/); Guillermo M. Leal Llaguno, 2017 updates by Morgan McGuire, Guedis Cardenas, Michael Mara and Nicholas Hull | Bundled license: research and educational use with attribution; source/conversion in ignored `assets/` |
| Classroom | [Blender demo](https://www.blender.org/download/demo-files/), Christophe Seux; [source ZIP](https://download.blender.org/demo/test/classroom.zip) | CC0; source/conversion in ignored `assets/` |
| Open Sans font | RTXDI Assets, `fonts/OpenSans/` | Bundled Apache 2.0 notice |

Nested submodules retain their notices. CMake fetches DXC `v1.8.2505.1`, DLSS `a8ed84e2d1cc1efa7bef63fb9394be6cb06c0d74`, and MathLib `v11`. Falcor is not installed. [Pitch illustrations](writing/course/slides/sources.md) have separate attribution.

## Provenance

Codex assisted the project documentation, validation script, scene records, conversion tools, and RTXDI runners. The [external-scene patch](scripts/run/rtxdi_external.patch) is project integration code; pinned RTXDI source is restored after building its local variant. Record later contributions and external code in the report.

The [Multi-scene experiment integration](scripts/run/rtxdi_experiments.patch) and [readback helper](scripts/run/rtxdi_experiments/LabExperiment.h) were developed with Codex. The integration adapts pinned RTXDI; NVIDIA notices and licensing remain applicable to upstream code.

The [conventional reference shader](scripts/run/rtxdi_experiments/ReferenceSamples.hlsl), reference runner and analysis tools are project code developed with Codex, using pinned RTXDI's light, material and visibility interfaces.

The local renderer builds apply [emissive-strength support](scripts/run/rtxdi_emission.py) to Donut temporarily and restore its source afterward.

The [PDF Similarity extension](docs/reproductions/pdf-similarity.md) is an independent implementation developed with Codex from Tokuyoshi's 2023 paper. Its build-time spatial shader adaptation retains the pinned NVIDIA source notice; no author implementation was imported.

The local progress presentation reproduces Figure 2 from Yusuke Tokuyoshi, *Efficient Spatial Resampling Using the PDF Similarity* (2023), [DOI: 10.1145/3585501](https://doi.org/10.1145/3585501), with attribution on slide 4. The source paper and generated figure crop are Git-ignored; [extraction provenance](writing/progress/data/paper-figure.json) records the source hash and crop. Copyright remains with the owner/author(s), with publication rights licensed to ACM; no open license is asserted for this figure.

## Additional scene imports

- [Emerald Square](https://developer.nvidia.com/orca/nvidia-emerald-square): NVIDIA / Nicholas Hull, Kate Anderson and Nir Benty; CC BY-NC-SA 3.0. Uses the ORCA Dusk variant.
- [Sun Temple](https://developer.nvidia.com/ue4-sun-temple): Epic Games; CC BY-NC-SA 4.0.
- [Veach Ajar](https://benedikt-bitterli.me/resources/): Benedikt Bitterli; bundled notice confirms CC0/public domain.

Original notices remain in ignored `assets/prepared/<scene>/`; archive hashes and
adaptations are in [the scene manifest](scenes/manifest.yaml). The Tungsten converter
follows the documented WO3 layout and transform conventions in
[Tungsten](https://github.com/tunabrain/tungsten); it is a local implementation.
