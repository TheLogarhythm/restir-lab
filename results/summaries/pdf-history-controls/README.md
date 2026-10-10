# PDF direction history controls

Independent experimental controls on the existing PDF-similarity adaptation. Mode 0 is the default and retains the original direction history. Set `pdf_similarity: true` and integer `pdf_history_mode` in an experiment definition, then run `python scripts/run/rtxdi_reuse.py --scene cornell-box --config <definition.json> --mode combined --scenario motion` after `python scripts/run/build_rtxdi_pdf.py`.

| Mode | Previous effective direction history |
|---|---|
| 0 | Original light-direction attenuation, capped at 20 |
| 1 | Original attenuation, then cap previous M at 4 |
| 2 | Original attenuation times a heuristic reflected-view overlap scale |

Mode 2 uses `exp(-s * max(0, 1-cos(theta)-1e-6) / max(roughness^4, 1e-6))`. Here theta compares previous/current reflected view directions, s is the larger specular sampling probability, and roughness is the smaller endpoint roughness. This is a heuristic, with a tolerance for normalization error; it is not an exact GGX overlap. The attenuated count participates in direction-reservoir weighting and PDF confidence. Mode 1 therefore also limits confidence to 0.2 after adding the current sample. Neither mode allocates extra direction state or traces extra rays.

Nonzero modes require PDF similarity. Python and renderer validation reject malformed modes; the shared runner requires an exact runtime confirmation before converting captures or marking a run complete. Older ordinary runs can omit the field at default mode 0. The interactive viewer uses mode 0. New/resumed conventional references explicitly clear both PDF similarity and the research history mode.

## Verification recorded on 2026-10-10

Release PDF build succeeded. The full unittest suite passed 141 tests, including shared C++ shader math, the exact generated renderer configuration body against pinned JsonCpp, mismatched/missing/malformed runtime confirmations, and fresh/resumed reference resets. Independent code review found no remaining blocking issue after these repairs.

GPU smoke checks: three modes × static/motion/reset, Cornell Box, 192×108, four frames per run, seed 1, reset frame 3, captures 1/3/4. All nine runs completed, confirmed their requested mode and produced finite, nonblack HDR captures. These checks validate integration; they do not rank image quality or performance. [Runtime/build/source records](smoke-record.json), [per-frame timings](smoke-timings.csv).

## Historical negative screening

The earlier Arcade screen used 1920×1080 combined DI, 128 frames, camera translation during frames 32–96, seeds 1/2/3, four spatial neighbors and radius 32. No denoising, upscaling or indirect illumination. These historical measurements are retained from the existing run snapshots; the review build above does not regenerate them.

| Frame | Original NRMSE | Cap 4 | View-aware |
|---|---:|---:|---:|
| 64 | 0.3261 | 0.3398 | 0.3945 |
| 96 | 0.2690 | 0.3555 | 0.3016 |
| 128 | 0.3015 | 0.3029 | 0.4001 |

[Full-image three-seed means and sample SD](historical-full-image.csv). Neither control established an improvement. Three seeds and correlated captured frames cannot establish a general ranking; no equal-time comparison was performed. Conventional references passed the recorded empirical full-image RMAE agreement/stability rule; shared bias and highlight/ROI precision remain unresolved. Keep mode 0 as the default. This is an experimental ablation, with no novelty claim for the heuristic or its usefulness across scenes.
