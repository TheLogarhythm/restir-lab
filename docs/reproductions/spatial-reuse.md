# Spatial-reuse comparison with CGNS

This historical study compares original and CGNS neighbor selection within ReSTIR DI, GI and PT using the local **corrected FullSample** variant. It is an RTXDI adaptation, not a reproduction of paper-quality results. Each pair shares executable, budget, history, depth and reuse settings. GI/PT retain the same original DI direct-light pass; their toggle changes only their respective indirect spatial pass. The [DI implementation guide](cgns.md) describes its separate adapter; [Falcor PT](falcor-cgns-pt.md) is another implementation.

The [controlled target and evidence contract](cgns-di-gi-pt.md) is intentionally frozen at its original path and bytes: historical report validation binds it as non-source evidence, and a source archive cannot replace it. It owns detailed reference transport, numerical/MIS corrections, metric provenance and release-gate requirements. This page provides the experiment overview and retained observations. See [comparison.md](../comparison.md) for analysis conventions.

## Fixed experiment

The pinned dependencies are RTXDI v3.1.0 `a6efab9`, SDK `f12037f` and Donut `2c10776`; build/run manifests record full revisions, shaders and integration fingerprints.

| Setting | Value |
| --- | --- |
| Views | Cornell Box, Bistro interior/exterior, Emerald Square, Sun Temple |
| Resolution / method seed | 1920×1080 / 1 |
| Acquisition | Fixed camera; 40 warmup frames; capture frame 41 |
| Reuse | Temporal + spatial; history 20; four neighbors; radius 32 pixels |
| CGNS | K=32; early stopping; position scale 0.05; normal exponent 8 |
| Postprocessing | Denoiser, AA, pixel jitter and checkerboard off |

The [configuration](../../experiments/configs/cgns-di-gi-pt-static.json) reuses the November 3 DI pair. SDK PT already includes official CGNS; this study substitutes the DI selection policy and adds a GI adapter. Lists are reused across normalization rounds. Native geometry/material rejection follows preselection without replenishment; each algorithm retains its own shifts, Jacobians, weights and normalization. Common transport corrections apply identically within each pair.

## Targets and reference limits

DI includes direct local/environment/analytic illumination, primary emission, background and legacy glass composition. It excludes opaque delta reflection, matching saved methods with zero BRDF candidates. GI/PT include direct light plus one indirect bounce, at most two surface scatterings; terminal emitters/environment are endpoints. PT's native `maxBounceDepth=3` includes that endpoint, while GI retains one secondary surface.

Each conventional PT reference contains exactly 8192 camera-conditioned paths/pixel, including black/background outcomes; NEE proposals are not extra spp. Seed 1001 is independent of method seed 1. The 4096 checkpoint restores the FP32 mean and resumes at absolute sample 4096; output is lossless linear FP32 PFM, optionally gzip-compressed. References use separate disjoint-support NEE/BSDF estimators without roulette, throughput cutoff or radiance clamp. [Reference runner](../../scripts/run/experiment/path_reference.py), [shader](../../scripts/run/rtxdi_experiments/PathReference.hlsl) and the frozen contract specify the sampling support, endpoint conventions and numerical bounds.

Authored secondary materials have no roughness floor. GI retains packed/view-independent secondary radiance and bounded Jacobians; PT retains cached suffixes and quantized lights. Legacy glass approximates layered attenuation/reflection rather than full dielectric paths. These limit target fidelity and do not establish unbiasedness.

## Retained results and interpretation

`runs/cgns-di-gi-pt-20261106` completed 30 method entries (10 reused DI) and 10 references before the latest transport-debug fixes. The report under `runs/validation/comparison-refactor-20261106-2337/final-groups/` reanalyzes those same images as regression evidence, not a newly corrected rendering campaign. Later corrected 64×64 captures were validated separately.

In that report, whole-image error increased for DI in all five views, decreased for GI in all five, and decreased for PT in three while increasing in two. These are historical, within-pair observations. Single seed, fixed views/parameters, transport issues and selection overhead prevent a general benefit claim.

Scores use linear-HDR Rec.709 luminance SMAPE, `100*mean(abs(Y-Yref)/(abs(Y)+abs(Yref)+1e-4))`, shared geometry masks and a common display exposure. Positive improvement means original minus CGNS; PNGs are never metric inputs. Exact author evaluation-pipeline parity is unverified. This study does not measure equal-time quality, repeatability or temporal stability. The correlated 4096→8192 checkpoint change is neither a confidence interval nor proof of reference convergence. Exact-build conformance and full-report verification requirements remain those in the frozen contract.
