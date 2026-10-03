# Multi-scene harness validation — 2026-09-29

Cornell Box, Arcade, Bistro and Zero-Day Measure One completed all four reuse
modes across static, motion and history-reset sequences: **48 runs** at
1920×1080, 128 frames, seed 1, on an RTX 4060 Laptop GPU.

- Compared modes used matching controls within each scene/scenario.
- Linear HDR captures and GPU timings were exported successfully; captures were
  finite, with denoising and AA disabled.
- Cornell's temporal reservoir history reset as expected at frame 65.
- Zero-Day's material and lighting fidelity remains unvalidated.

This establishes the experiment harness. Quantitative quality and timing results
are in the subsequent [three-scene DI baseline](di-baseline/README.md).

See the [run index](../index.csv) for retained baseline results and the
[experiment controls](../../experiments/suites/di-reuse.md) for their settings.
