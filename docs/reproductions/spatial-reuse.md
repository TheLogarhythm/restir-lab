# Spatial-reuse comparison with CGNS

Compare original spatial neighbor selection against CGNS within ReSTIR DI,
GI and PT. Each pair shares an executable, sampling budget, history, depth and
reuse settings. GI/PT retain the original DI direct-light pass; their CGNS
toggle affects only the respective indirect spatial pass.

The local corrected FullSample variant uses RTXDI v3.1.0 (`a6efab9`), SDK
`f12037f` and Donut `2c10776`. Build/run manifests record full revisions,
shader hashes and integration changes.

## Fixed experiment

| Setting | Value |
| --- | --- |
| Views | Cornell Box, Bistro interior/exterior, Emerald Square, Sun Temple |
| Resolution / method seed | 1920×1080 / 1 |
| Acquisition | Fixed camera; 40 warmup frames; capture frame 41 |
| Reuse | Temporal + spatial; history 20; four neighbors; radius 32 pixels |
| CGNS | K=32; early stopping; position scale 0.05; normal exponent 8 |
| Postprocessing | Denoiser, AA, pixel jitter and checkerboard off |

The [configuration](../../experiments/configs/cgns-di-gi-pt-static.json) explicitly
reuses the November 3 DI pair. Geometry/material rejection remains after CGNS
preselection, without replenishment. The SDK already provides PT CGNS integration;
this study substitutes the DI selection policy and adds a separate GI adapter.
Each algorithm retains its own shift, Jacobian, weight and normalization logic.

## References and transport

- **DI:** direct local/environment/analytic illumination, primary emission,
  background and legacy DI glass composition. Opaque delta reflection is
  excluded, matching saved DI methods with zero BRDF candidates.
- **GI/PT:** direct plus one indirect bounce, at most two surface scatterings.
  Terminal emitter/environment hits are endpoints. PT uses `maxBounceDepth=3`
  with its native endpoint convention; GI retains one secondary surface.

Each conventional PT reference has exactly 8192 camera-conditioned paths per
pixel, including black/background outcomes. One iteration adds one path; NEE
proposals are not extra spp. Seed 1001 is independent of method seed 1. The 4096
checkpoint restores the FP32 running mean and continues at absolute index 4096.
Output is lossless linear FP32 PFM, optionally gzip-compressed.

The reference uses local power-PDF, environment and analytic-light proposals,
Lambert/GGX continuation and discrete mirrors below roughness 0.03. MIS is off
with disjoint support: indexed continuous endpoints use NEE, delta/unindexed
endpoints use BSDF tracing. Roulette, throughput cutoff and radiance clamping
are off. See [path_reference.py](../../scripts/run/experiment/path_reference.py)
and [PathReference.hlsl](../../scripts/run/rtxdi_experiments/PathReference.hlsl).

Common transport corrections apply to both methods in each pair. Secondary
materials retain authored settings without a roughness floor. Remaining limits
include GI's view-independent/packed secondary radiance and bounded Jacobians,
PT cached suffixes and quantized lights. Legacy glass approximates layered
transmission/reflection rather than full dielectric paths. These approximations
limit target fidelity; unbiasedness is not established.

## Retained results and interpretation

`runs/cgns-di-gi-pt-20261106` completed 30 method entries (10 reused DI) and
10 reference outputs. It predates the latest transport debug fixes. The report
under `runs/validation/comparison-refactor-20261106-2337/final-groups/` reanalyzes
those same images as regression evidence, not a new corrected rendering campaign.
Later corrected 64×64 captures were validated separately.

In the retained report, whole-image error increases for DI in all five views;
GI decreases in all five; PT decreases in three and increases in two. These
observations concern the historical captures only. Single seed, fixed parameters,
transport issues and selection overhead prevent a general benefit claim.

The [comparison guide](../comparison.md) defines linear-HDR luminance SMAPE,
shared masks and display exposure. Exact author evaluation-pipeline parity is
unverified. This study does not measure equal-time quality, repeatability or
temporal stability. The correlated 4096→8192 checkpoint change is not a confidence
interval or proof of reference convergence.
