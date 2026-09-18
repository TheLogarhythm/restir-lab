# ReSTIR Lab

A two-person COMP5411 project for reproducing selected ReSTIR methods, understanding their behavior, and developing evidence for future rendering research.

**Status:** scaffold and initial literature review. Renderer dependencies, assets, and experiments have not been installed or run. No reproduction results are claimed. Setup guidance and the roadmap are drafts and will evolve as project decisions are made.

## Start here

1. Read [scope](docs/scope.md), [milestones](docs/roadmap.md), and the [literature review](docs/literature/README.md).
2. Follow [setup](docs/setup.md) to check the scaffold.
3. Select and pin the [renderer implementations](renderers/README.md).
4. Register assets using [the scene manifest](scenes/README.md).
5. Follow [the experiment protocol](experiments/protocol.md).

## Repository map

| Directory | Purpose |
| --- | --- |
| `docs/` | Scope, setup, literature, reproduction records, observations, decisions |
| `renderers/` | Independent RTXDI and Falcor integrations |
| `scenes/` | Asset provenance, backend settings, trajectories, generators |
| `experiments/` | Experiment configurations and suites |
| `scripts/` | Asset preparation, execution, analysis, scaffold validation |
| `tests/` | Future numerical and small-scene regression checks |
| `results/` | Small summaries, selected figures, artifact index |
| `writing/` | Course guidelines, templates, working documents, references |
| `assets/`, `runs/`, `build/` | Ignored local assets and generated output |

Use Issues for tasks and the roadmap for milestones. See [contributing](CONTRIBUTING.md).

## Course writing

Originals are preserved in [templates](writing/course/templates/README.md). Edit the [proposal](writing/course/proposal/main.tex) and [report](writing/course/report/main.tex) working copies. They still contain instructional template text, not completed coursework.

## Licensing

No open-source license has been selected; see [LICENSE](LICENSE). External materials retain their own terms; see [THIRD_PARTY.md](THIRD_PARTY.md). Check course-material redistribution terms before public distribution.
