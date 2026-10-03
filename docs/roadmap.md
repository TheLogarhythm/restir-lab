# Roadmap

**Draft.** The [scope](scope.md) proposes ReSTIR DI, PDF Similarity, and CGNS on one primary backend. Weeks below are planning estimates.

The [proposal](../writing/course/proposal/main.tex) and [DI baseline](../results/summaries/di-baseline/README.md) are ready. The baseline covers Cornell Box, Arcade and Bistro: four reuse modes, static/motion/reset sequences, linear HDR, GPU timings and checked conventional references. It is a single-seed, fixed-parameter evaluation. Zero-Day remains optional pending material/light validation.

## Next: PDF Similarity

The [PDF Similarity DI extension](reproductions/pdf-similarity.md) is implemented; [runtime checks and remaining validation](reproductions/pdf-similarity.md#validation) are recorded.

Direction MIS and fractional-M spatial tests are in place; analysis distinguishes PDF on/off.

1. Resolve the existing reference index's missing lighting provenance.
2. Compare PDF on/off spatial/combined reuse with matched builds, scenes, cameras and metrics. Include an equal-time comparison.
3. Use the findings to scope CGNS and prepare the progress demo.

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

Track tasks on the [Project board](https://github.com/users/TheLogarhythm/projects/1/views/1), decisions in [docs/decisions](decisions/), and measured runs in [results/index.csv](../results/index.csv).
