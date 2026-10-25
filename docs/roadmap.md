# Roadmap

**Archive update — 2026-10-23:** PDF results remain complete within the approved sparse scope. Current data live in `runs/pdf-similarity-archive/`: complete seed-1 PNG sequences, all three-seed CSV/timings and selected HDR. Old MP4, full temporal HDR and reference-generation media are retired. The archive inventory controls current availability; no continuation of the original campaign is planned.

**Draft.** The [scope](scope.md) proposes ReSTIR DI, PDF Similarity, and CGNS on one primary backend. Weeks below are planning estimates.

The [proposal](../writing/course/proposal/main.tex) and [three-scene DI baseline](../results/summaries/di-baseline/README.md) are complete. Baseline images, statistics and run records are archived for reporting.

## PDF Similarity — sparse evaluation complete

The [DI extension](reproductions/pdf-similarity.md) and sparse evaluation are complete: 78 runs across three seeds, covering PDF on/off, ablations and bounded equal-time analysis. All 15 reference states are ready; five passed precision checks, while ten Bistro states use fixed-budget references with unassessed uncertainty.

Results show selective quality improvements in static views and Bistro exterior/changing-light conditions, with added GPU cost. Interior and moving-region regressions prevent a general advantage.

The [results summary](../results/summaries/pdf-similarity/README.md) supports the progress report. Detailed settings remain in the [experiment plan](../experiments/suites/pdf-similarity.md).

## CGNS — integration validated

The [DI adaptation](reproductions/cgns.md) passes Release builds, CPU/native checks and 40 short 720p runs across all 10 configured scenes (2026-10-25), with exact off/baseline agreement. Next: define a bounded comparison of baseline, PDF Similarity and CGNS, including image error, correlation and full GPU cost, using matching corrected builds and references. Formal CGNS evaluation remains pending.

Follow the [experiment protocol](../experiments/protocol.md).

## Course schedule

| Weeks | Target |
| --- | --- |
| 1–2 | Proposal, backend feasibility, and a repeatable Cornell run |
| 3–4 | ReSTIR DI baseline, reuse controls, and a direct-light reference |
| 5 | PDF Similarity; [project progress video](https://github.com/TheLogarhythm/restir-lab/issues/3) due Oct 25, 23:59 |
| 6–7 | CGNS implementation and integration |
| 8 | Demo and experiment freeze |
| 9–10 | Evaluation, report, teammate reproduction check; [project presentation](https://github.com/TheLogarhythm/restir-lab/issues/4): slides due **Nov 22, 2026, 23:59 Hong Kong time**; in-class talk ~4m30s, hard max 5m, including ~2 min demo |

Track tasks on the [Project board](https://github.com/users/TheLogarhythm/projects/1/views/1), decisions in [docs/decisions](decisions/), and measured runs in [results/index.csv](../results/index.csv).
