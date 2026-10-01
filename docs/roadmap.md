# Roadmap

**Draft.** The [scope](scope.md) proposes ReSTIR DI, PDF Similarity, and CGNS on one primary backend. Weeks below are planning estimates.

The [proposal](../writing/course/proposal/main.tex) and [DI baseline](../results/summaries/di-baseline/README.md) are ready. The baseline covers Cornell Box, Arcade and Bistro: four reuse modes, static/motion/reset sequences, linear HDR, GPU timings and checked conventional references. It is a single-seed, fixed-parameter evaluation. Zero-Day remains optional pending material/light validation.

## Next: PDF Similarity

1. Read [PDF Similarity](literature/README.md#course-reading-sequence) and define the minimal RTXDI integration and controls.
2. Implement the extension behind an explicit switch, retaining the baseline modes.
3. Compare with baseline spatial/combined reuse using the same scenes, cameras and metrics; add an equal-time comparison when the implementation is ready.
4. Use the findings to scope CGNS and prepare the progress demo.

Follow the [experiment protocol](../experiments/protocol.md).

## Course schedule

| Weeks | Target |
| --- | --- |
| 1–2 | Proposal, backend feasibility, and a repeatable Cornell run |
| 3–4 | ReSTIR DI baseline, reuse controls, and a direct-light reference |
| 5 | PDF Similarity; [project progress video](https://github.com/TheLogarhythm/restir-lab/issues/3) due Oct 25, 23:59 |
| 6–7 | CGNS implementation and integration |
| 8 | Demo and experiment freeze |
| 9–10 | Evaluation, report, and teammate reproduction check |

The [pitch was submitted](https://github.com/TheLogarhythm/restir-lab/issues/1#issuecomment-5762409423) on 2026-09-21. The [proposal task](https://github.com/TheLogarhythm/restir-lab/issues/2) is due **2026-09-29, 23:59 Hong Kong time**. Track work on the [Project board](https://github.com/users/TheLogarhythm/projects/1/views/1); record decisions in [docs/decisions](decisions/) and measured runs in [results/index.csv](../results/index.csv). Split implementation and evaluation between teammates, and review each other's work.
