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
| Open Sans font | RTXDI Assets, `fonts/OpenSans/` | Bundled Apache 2.0 notice |

Nested submodules retain their notices. CMake fetches DXC `v1.8.2505.1`, DLSS `a8ed84e2d1cc1efa7bef63fb9394be6cb06c0d74`, and MathLib `v11`. Falcor is not installed. [Pitch illustrations](writing/course/slides/sources.md) have separate attribution.

## Provenance

Codex assisted the project documentation, validation script, scene records, conversion tools, and RTXDI runners. The [external-scene patch](scripts/run/rtxdi_external.patch) is project integration code; pinned RTXDI source is restored after building its local variant. Record later contributions and external code in the report.
