# Controlled CGNS comparison across DI, GI and PT

This is a local adaptation of RTXDI FullSample v3.1.0 (`a6efab966b7c3b272da0461578eb56ac61c7cbff`),
SDK `f12037fa8e97ebc08e9e3edfd2de528ed1772a4b` and Donut
`2c1077673edb0e0d814c202e6ce8e502d245c2da`. Executable, shader and integration
hashes in each build/run manifest identify the actual variant. It is labelled
**corrected FullSample**, not a reproduction of paper-quality results.

## Targets and samples

The user selected at most two surface-scattering events for the shared GI/PT
target: direct illumination plus one indirect bounce. A terminal emitter or
environment hit does not count as another scattering event. PT's native bound
is `maxBounceDepth=3`, including its endpoint; `maxRcVertexLength=4` is the
no-reconnection sentinel, not an extra bounce. GI retains one secondary surface.

The direct reference includes continuous Lambert/GGX direct lighting from the
registered local, environment and analytic-light domains, primary emission and
background, and the historical DI glass composition. Opaque delta reflection is
excluded, matching the saved DI methods, whose BRDF candidate count is zero.
The full reference also includes allowed secondary scattering and sampled mirror
endpoint paths. Indexed continuous emissive endpoints use packed light radiance;
continuous environment endpoints use the packed light's scale/rotation.
Delta/unindexed emission and delta environment endpoints use authored radiance.

Both references are ordinary Monte Carlo paths: no initial/temporal/spatial
reservoir, no CGNS and no RIS light pool. One iteration contributes exactly one
camera-conditioned path sample per pixel, including zero/background outcomes.
Each scattering vertex independently proposes one local light from the power
PDF mipmap, one environment direction when present, and one uniform analytic
light when present. These NEE proposals do not count as additional spp.
Continuation uses a fixed Lambert/GGX mixture, the correct visible-GGX density,
and discrete mirror mass below roughness 0.03. MIS is off with disjoint support:
continuous indexed emitter/environment paths use NEE, and delta/unindexed
endpoints use BSDF tracing. There is no roulette, throughput cutoff or radiance
clamp. Primary rays use pixel centers, without jitter, AA or reconstruction.

Reference seed is 1001, independent of method seed1. Absolute path index i uses
sampling frame `1001*1048576+i`. FP32 lighting/composition/running-mean accumulation
is exported as lossless linear FP32 PFM. The 4096 checkpoint restores this mean
and count; the next sample is index4096, and total completion is8192. It does not
warm up or recount samples. Failed/ambiguous attempts require explicit diagnosis;
completed results are verified and reused. Formal checkpoints are4096 and8192.

The shared legacy glass pass is an explicit transport exception: up to eight
layers, colored/Fresnel attenuation, approximate reflection using emission and
a fixed diffuse ambient term `(0.05,0.045,0.03)`, native cutoff, no refractive path
tracing. Primary material/emission packing, normal encoding, quantized triangle
light geometry and native ray offsets remain. Invalid input environment texels
retain upstream exclusion; environment proposal weights retain the FP16 maximum
65504 and add a positive minimum1/1024 for in-bounds cells only. This bounds
proposal weights, not radiance, and gives filtered environment radiance full
sampling support, including black and underflowed cells.

## Common corrections and CGNS

`scripts/run/rtxdi_transport_fixes.py` applies the same corrections to both
members of each pair in a private SDK/shader tree. Upstream files are restored
after each isolated build. Corrections include GI final-buffer selection,
delta output/terminal delta endpoint, one-sided emission, fixed mixture density,
null-M normalization and independent final MIS terms; PT discrete delta measure,
visible-GGX density, continuous inverse-footprint PDF, indexed emission support,
and colored visibility through initial/replayed paths and reconnections.

GI and PT each use the same original DI pass for their direct-light component.
Their CGNS toggle affects only their respective indirect spatial-reuse pass.
The DI pair retains the historical experiment's own original/CGNS direct pass.
Thus each pair isolates neighbor selection for the algorithm named in that pair.

PT endpoint MIS uses a fixed sample-count partition: indexed continuous NEE has
weight n/(n+1), BSDF hits1/(n+1); analytic NEE and delta/unindexed endpoints retain
weight1. The count includes unsuccessful proposals. This removes a native cached
donor MIS factor that was inconsistent with receiver-dependent NEE MIS after a
shift. It changes estimator variance, is recorded explicitly, and is identical
for original/CGNS. The reference uses its separate disjoint-support estimator of
the same target. The BSDF PDF follows [Heitz2018](https://jcgt.org/published/0007/04/01/).

Native GI still approximates view-dependent secondary outgoing radiance by a
view-independent sample, packs secondary materials/radiance, uses a secondary
geometry normal rather than PT's normal mapping, rejects/clamps Jacobians and
uses roughened final MIS. Native PT reconnection also caches direction-dependent
suffix information. These are estimator approximations, not changes silently
made to the reference. This comparison does not establish unbiasedness.

This SDK already has official PT CGNS. Its selector is replaced with the existing
DI policy for this experiment; the PT reservoir/hybrid-shift consumers are reused.
GI receives its own adapter. All pairs use four neighbors, radius32, K32, early
stopping, position scale0.05 and normal exponent8. Lists are reused across both
normalization rounds. Native geometry/material rejection remains; rejected
neighbors are not replenished. Selection does not change proposal PDFs,
Jacobians or reservoir weighting. Native-off control builds retain the same
common transport corrections and pristine spatial consumers.

## Metrics and source checks

All three groups use scene-linear luminance SMAPE
`100*mean(abs(Y-Yref)/(abs(Y)+abs(Yref)+1e-4))`, Rec.709 luminance coefficients,
without a factor2. Whole-image and hard-region scores share masks derived from
the historical DI primary geometry. Positive reported improvement is original
minus CGNS. PNGs use the same EV0 Reinhard+sRGB display transform; they are never
inputs to error metrics. Selection time is a separately reported part of total
GPU time. Merged-neighbor counts include accepted zero-weight streams, not only
positive contributors.

The [CGNS paper](https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/)
footnote3 specifies100, luminance, epsilon1e-4 and no factor2. Exact author
evaluation-script reduction/absolute-value ordering is not verified. The pinned
[author ErrorMeasurer shader](https://github.com/orion-junkins/ReSTIR-CGNS/blob/f28d553f3b2552b1be829feffea6d1abb1945e1d/Source/RenderPasses/ErrorMeasurePass/ErrorMeasurer.cs.slang)
implements RGB absolute or squared difference with optional channel averaging;
it does not establish the paper's SMAPE evaluation path. A repository search
did not locate that evaluator. We do not claim bit-exact author metric parity.

The [ReSTIR GI paper](https://research.nvidia.com/publication/2021-06_restir-gi-path-resampling-real-time-path-tracing)
reports MSE. Its complete publication evaluation pipeline and channel/foreground
settings have not been verified. The [GRIS/ReSTIR PT paper](https://research.nvidia.com/labs/rtr/publication/lin2022generalized/)
reports MAPE on HDR; footnote13 uses grayscale-reference normalization with a
stabilizer0.01 times mean reference grayscale. This is a different metric from
our SMAPE. Exact author executable metric settings remain unverified. Current
RTXDI FullSample is also a later implementation than those papers.

## Release gate and interpretation

The grouped launcher requires an exact-build conformance receipt: CPU/native/
scaffold checks, CGNS-off pixel equivalence, transport edge fixtures, reference
resume/convergence and independent final review. A successful build or nonblack
image cannot satisfy it. Full report verification regenerates masks, reference
comparisons, timing/neighbor summaries and previews in scratch storage and binds
the HTML to those results. Historical DI timing/config/reference-index inputs
are frozen as well as their image/build hashes.

Single seed, five fixed views and fixed parameters support within-pair descriptive
comparisons. This is not an equal-time, multi-seed or temporal-stability study.
4096→8192 measures correlated checkpoint change, not a confidence interval or
proof of reference convergence. Conclusions must reflect this limitation.
