# Project scope

**Draft, 2026-09-19.** Reproduce three ReSTIR methods on a shared direct-lighting pipeline and leave a repository that supports further research.

## Question and methods

Under a matched rendering budget, how do spatial reuse strategies affect image error and temporal stability?

| Role | Work | Planned implementation |
| --- | --- | --- |
| Baseline | ReSTIR DI (2020) | Reservoir updates, initial sampling, temporal and spatial reuse, and diagnostic switches |
| Improvement | PDF Similarity (2023) | Distribution approximation and estimation, similarity-based rejection, and required temporal safeguards |
| Recent work | Compatibility-Guided Neighbor Selection (2026) | Compatibility scoring, weighted stochastic neighbor selection, and integration with spatial resampling |

See the [literature review](literature/README.md) and [proposal](../writing/course/proposal/main.tex) for sources. Compare each extension separately against the shared baseline. Combining the extensions is optional.

## Implementation boundary

- Use one primary backend. RTXDI is the preferred starting point; Falcor author code is a reference and possible alternative if the early build check favors it. Pin the chosen revision before implementation.
- Reuse scene loading, materials, ray tracing, and display. Implement or port the selected algorithms, document their equations and assumptions, and identify upstream versus team contributions.
- Validate the CGNS transfer from its Falcor path tracer to DI. Identify modern renderer features that must be disabled or documented for the baseline.
- The [scene shortlist](../scenes/README.md) is Cornell Box, Bistro, and Arcade. Start with one static view per scene and one or two short camera trajectories overall. Keep scene preparation small and record modifications.

## Completion criteria

1. Three selectable methods render the same direct-lighting target with documented differences.
2. The baseline is checked against a converged conventional reference; extensions pass controlled correctness and behavior checks.
3. Shared scripts/configurations produce HDR images, GPU timings, and repeatable comparisons under the [experiment protocol](../experiments/protocol.md).
4. Results include matched-time comparisons, a small ablation set, dynamic behavior, and unsuccessful cases. No specific speedup or novel algorithm is promised.
5. A teammate can build the pinned backend and repeat a small experiment from the documented steps. The report and demo identify code provenance and limitations.

## Workload and open decisions

The provisional schedule spans ten weeks. Confirm hardware, availability, member backgrounds, and course dates before finalizing it. Reduce parameter sweeps and optional features before reducing the three-method target; record any target change explicitly.

Further transport domains, a second maintained backend, extensive scene authoring, and a new algorithm are future extensions. The [roadmap](roadmap.md) tracks milestones. Record confirmed backend and method choices in [decisions](decisions/).
