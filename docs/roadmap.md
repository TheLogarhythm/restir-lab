# Roadmap

**Draft.** The [scope](scope.md) proposes ReSTIR DI, PDF Similarity, and CGNS on one primary backend. Weeks below are planning estimates.

The [proposal](../writing/course/proposal/main.tex) and [DI baseline](../results/summaries/di-baseline/README.md) are ready. The baseline covers Cornell Box, Arcade and Bistro: four reuse modes, static/motion/reset sequences, linear HDR, GPU timings and checked conventional references. It is a single-seed, fixed-parameter evaluation. Zero-Day remains optional pending material/light validation.

## Next: PDF Similarity

The [PDF Similarity DI extension](reproductions/pdf-similarity.md) is implemented; [runtime checks and remaining validation](reproductions/pdf-similarity.md#validation) are recorded.

Direction MIS and fractional-M spatial tests are in place; analysis distinguishes PDF on/off.

Follow the [controlled comparison plan](../experiments/suites/pdf-similarity.md):

1. SMAPE/TRMAE, error-map/video export, deterministic camera/light controls and frozen-state reference generation are implemented. The approved order is technical pilot checks, all 78 method runs (main, ablation and equal-time) and reference-free comparison products, then matched references.
2. Run the 1080p comparison, emphasizing Bistro interior/exterior, 30 FPS motion clips (32 static / 32 moving / 32 stopped frames) and one isolated lighting change; retain original PDF/history defaults (`pdf_history_mode=0`).
3. Use the remainder of the fixed 30-hour total budget, including elapsed work, for references; acceptance gates quantitative error analysis and reference-based products. Keep the 1,048,576-local-sample per-stream cap and precision gates unless explicitly approved in advance. Prioritize static pairs and one referenced Bistro motion clip for Oct 25, then complete evaluation alongside CGNS.

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
