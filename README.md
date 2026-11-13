# ReSTIR Spatial Reuse: Implementation and Evaluation

A two-person COMP5411 project to reproduce and study selected ReSTIR methods. The [ReSTIR DI baseline](results/summaries/di-baseline/README.md) evaluates Cornell Box, Arcade and Bistro using RTXDI `v3.1.0`. [PDF Similarity](docs/reproductions/pdf-similarity.md) and [CGNS](docs/reproductions/cgns.md) are available for DI. PDF's sparse evaluation is complete. The [CGNS spatial-reuse study](docs/reproductions/spatial-reuse.md) covers DI, GI and PT; retained results and their limits are documented separately.

Start with the [scope](docs/scope.md), [literature review](docs/literature/README.md), and [roadmap](docs/roadmap.md). Follow [setup](docs/setup.md) to run RTXDI, then use the [scene manifest](scenes/README.md) and [experiment protocol](experiments/protocol.md) for comparisons.

| Directory | Contents |
| --- | --- |
| `renderers/` | Pinned RTXDI and Falcor 9.0 submodules |
| `scenes/` | Asset provenance and scene settings |
| `experiments/`, `results/` | Configurations and research results |
| `scripts/`, `tests/` | Runners, analysis, and regression tests |
| `docs/` | Plans, literature, decisions, and observations |
| `writing/` | Course templates, working documents, and references |

See the [comparison workflow](docs/comparison.md) for fixed-view spatial-reuse experiments. For the six fixed Falcor ReSTIR PT views, see the [scene preparation guide](experiments/configs/falcor-pt-spatial-comparison/PREPARATION.md) and [ordinary spatial reuse / CGNS configuration](experiments/configs/falcor-pt-spatial-comparison/README.md).

Local assets, builds, and runs are ignored. Edit the [proposal](writing/course/proposal/main.tex) and [report](writing/course/report/main.tex); preserve the [original templates](writing/course/templates/README.md). See [contributing](CONTRIBUTING.md), [third-party sources](THIRD_PARTY.md), and [licensing](LICENSE).

Shared Python metrics and RTXDI/Falcor saved-result readers are documented in [shared offline analysis](docs/shared-analysis.md). Existing renderer commands remain available.
