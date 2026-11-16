# PDF Similarity on Falcor ReSTIR PT

This independent adaptation uses [Tokuyoshi 2023](https://doi.org/10.1145/3585501)
vMF fitting and similarity with Falcor's weighted [GRIS](https://research.nvidia.com/labs/rtr/publication/lin2022generalized/)
spatial merge. Three project-specific choices distinguish it from the paper's
single-bounce estimator: a first-hop summary of multi-bounce contributions,
cross-frame direction moments, and effective PT reservoir confidence. It is
neither a multi-hop paper reproduction nor a proven unbiased estimator.

The [RTXDI DI implementation](pdf-similarity.md) has different history and MIS.
Use the [six-view guide](pt-6-views-spatial-compare.md) for production collection,
runtime verification and archive access.

## Candidate weights and directions

The [shader composer](../../scripts/falcor/pdf_pt_shader.py) observes every valid
initial RIS candidate, including candidates that lose selection. It records the
finite positive scalar actually passed to initial RIS:
`w = PathRISState::toScalar(pathContribution)`. It adds no proposals, visibility
rays or draws from the PT sampler.

| Candidate entering initial RIS | Direction leaving the primary surface |
| --- | --- |
| Primary-surface NEE | Actual light-connection direction `wi` |
| NEE after scattering | Saved first actual BSDF-scattered `path.dir` |
| BSDF hit on emitter or environment | The same first-scatter direction, including reflection/transmission |
| Primary emission/background routed to `pathL0` | Excluded: no reusable initial candidate/direction |

Native NEE supplies `path.thp * Lr / pdfWarpFactor`; emissive BSDF hits supply
`path.thp * misWeight * emission`; environment hits supply
`path.thp * misWeight * Le`. Moments use these exact inputs to `addPSSSample`,
before the selected integrand's `sourcePdf` multiplication. No second luminance
weight, PDF division or reservoir weight is applied. Deep light-connection and
reconnection directions cannot replace the first segment.

The [shared helper](../../scripts/falcor/pdf_pt_direction.h) normalizes directions
and accumulates `a = sum(w * omega)`, `b = sum(w)`. Per-pixel `labMoment=(A,B)`
and `labCount=n` remain independent of the selected lighting reservoir; they are
not spatially propagated with its winner. Native reflected buffer types carry
the fields through passes and bank exchange, without a hardcoded host stride.

## History and similarity

The [history shader](../../scripts/falcor/pdf_pt_history.slang) merges the nearest
valid reprojected pixel:

```text
(A, B) = (a, b) + history_decay * (A_previous, B_previous)
n = min(history_limit, indicator(b > 0) + history_decay * n_previous)
c = clamp((min(n_center, n_neighbor) - 1) / (history_limit - 1), 0, 1)
h = (1 - c) + c * vMF_similarity
```

| Parameter | Default | Meaning |
| --- | --- | --- |
| `history_limit` | 20 | Decayed evidence-count cap; integer 1–100 |
| `history_decay` | 0.95 | Retention in [0,1]; positive float32-subnormal values rejected |
| DI-shared fitting constants | alpha=100, beta=10 | Concentration smoothing and similarity exponent |

At decay 0.95, sustained evidence approaches count 20 and old weight halves in
about 13.5 frames. This is evidence mass, not independent observations or lighting
reservoir `M`. The cap also applies at decay 1. Native `maxHistoryLength` is a
separate lighting-history setting. With limit 1, define `c=0`.

History requires valid hits with matching type, instance, primitive, material
and front-facing state; face-normal agreement >=0.95; and position error <=1%
of camera distance with a 0.001 floor. Out-of-bounds/nonfinite reprojection,
invalid previous evidence or nonfinite sums are rejected. Non-jittered camera
matrix and resolution stamps must match. First use, frame-zero reset, camera
changes and resizing discard history; decay 0 uses current evidence only.

`B=0` means no direction evidence and falls back to `h=1`. Positive `B` with
near-zero `|A/B|` represents cancelling directions and is fitted as uniform:
similarity is 1 for two uniform lobes and 0 when only one is uniform. The scalar
formula is shared with [DI math](../../scripts/run/rtxdi_experiments/PdfSimilarityMath.h);
PT does not use DI's direction reservoir, lambda=1000 angular retention or
view-lobe history heuristic.

Statistics merge inside native temporal resampling. With temporal off, `n<=1`,
so normal/observe profiles give `c=0`, `h=1`: this is a history-off control.
Same-material parameter edits and moving lights have no independent invalidation
rule; stale evidence persists until rejection, decay or reset.

## Effective M and normalization

For the supported one-neighbor, unpaired point-reservoir path, the
[MIS overlay](../../scripts/falcor/pdf_pt_mis.py) computes `h` once after native
geometry acceptance and caches `N = h * M_neighbor`. It preserves the ordinary
proposal and radius, native reconnection, Jacobian and visibility evaluation.

The [effective-M helper](../../scripts/falcor/pdf_pt_mis.h) rejects nonpositive
or nonfinite confidence and nonfinite `h`, clamps finite `h` to [0,1], and
rejects zero effective confidence. Workload `cSum`, reverse canonical MIS,
forward shift/MIS, merging and output `M` all consume the same cached `N`.
The neighbor is a local copy; its source reservoir and stored contribution
weight stay unchanged.

Let `Mc` and `Mi` be original confidences, `pc` and `pi` the original targets,
and `qrev`/`qfwd` shifted targets including their respective Jacobians:

```text
N = h * Mi; S = Mc + N
mc = Mc/S + (N/S) * (1 - qrev*N / (qrev*N + pc*Mc))
mi = (N/S) * (pi*N / (pi*N + qfwd*Mc))
Mout = Mc + N
```

Native finalization divides merged weight by selected `pHat`; no extra division
by `M` or multiplication by `h` follows. Failed shifts retain native confidence
handling. Zero `qrev` makes the subtracted fraction zero; zero `S` or forward
denominator gives weight zero. Both MIS sides read `N` directly rather than
recovering it as `S-Mc`, which can cancel small fractional values.

For `Mc=2, Mi=4, h=0.5, pc=3, pi=5, qrev=2, qfwd=3`, `N=2, S=4, mc=0.8,
mi=5/16, Mout=4`. These MIS weights concern different samples/domains and need
not sum to one.

## Configuration and diagnostics

The [experiment config](../../experiments/configs/falcor-pt-spatial-comparison/restir-pt-spatial-comparison.json)
exposes `methods.pdf-similarity.shader`. Qualified operation uses 1 spp,
TinyUniform, MinimalPayload, one unpaired spatial neighbor/iteration, radius 30,
point reservoirs, compact retracing and no DoF reconnection. Other graph variants
are rejected. Bistro interior requires the `gltf-v3` runtime; other frozen views
use `reference`. [Preparation](../../scripts/falcor/pdf_pt_runtime.py) preserves
base material patches/plugins and gives each variant independent files/cache,
identified by source receipt, parameters, profile and implementation.

From the repository root, this example creates a new eight-frame diagnostic:

```powershell
$py = 'build/falcor/verify-env/Scripts/python.exe'
$runtime = (& $py -B -m scripts.falcor.pdf_pt_runtime --source reference --profile observe |
  Select-Object -Last 1)
& $py -B -m scripts.falcor.spatial_capture --method pdf-similarity --pdf-profile observe `
  --runtime $runtime --config experiments/views/falcor-pt-spatial-comparison/classroom.json `
  --output runs/pdf-pt-new/classroom-observe --scout --width 320 --height 180 --warmup 4 --count 4 --seed-offset 0
```

Use a fresh output path and leave `FALCOR_DEVMODE` unset. Scouts are bounded to
640x360 and 64 total frames. Non-normal profiles require a scout and matching
runtime. Seed offsets also support formal independent realizations; see the
six-view guide for their path/reuse schedule. Temporal-off uses the compatibility
entry point `scripts.falcor.cgns_paper_capture` with the same PDF flags.

| Profile | Behavior |
| --- | --- |
| `normal` / `observe` | Production similarity; observe adds diagnostic outputs |
| `one` / `zero` | Force h=1 / h=0 |
| `center` | Independent center-only merge/finalize, without neighbor mask/confidence reads |
| `native` | Original estimator with native M/weight/target readback |

| Diagnostic AOV | RGBA contents |
| --- | --- |
| `nrdEmission` | M, weight, pHat, n (native profile uses zero in channel 4) |
| `nrdDiffuseRadianceHitDist` | A.xyz, B |
| `nrdSpecularRadianceHitDist` | h, effective neighbor M, cSum, center M |
| `nrdResidualRadianceHitDist` | Initial weights: primary NEE, deep NEE, BSDF hits, total evidence |

The native profile exposes only the first readout. These repurposed channels
are not denoiser inputs. Retain RGBA diagnostics;
diagnostic-export timings do not measure normal-profile cost. Capture manifests
bind seeds, graph, camera, parameters, runtime receipts and source/output hashes.

[Preset scouts](../../scripts/falcor/pdf_pt_scouts.py) use 96x64: 12 Classroom
frames, three Bistro frames and paired Classroom seeds 0/64/128/192. Repeated
`--case scene-profile-seed` selects cases; omission requests the whole preset.
The [reset check](../../scripts/falcor/pdf_pt_reset_check.py) takes 11 frames at
160x90, or 19 with `--camera-cut`. It requires an observe runtime.

```powershell
$results = 'runs/pdf-pt-new/scouts'
& $py -B -m scripts.falcor.pdf_pt_scouts $results
& $py -B -m scripts.falcor.pdf_pt_pair_check "$results/cases/classroom-observe-0"
& $py -B -m scripts.falcor.pdf_pt_validation_results $results --plan scouts --output "$results/strict.json"
```

The analyzer preserves missing/excluded attempts and defaults to exact equality.
`--aov-atol 1e-6` is available for the documented cross-output-specialization HDR
check below; matched-diagnostic controls still require exact agreement. The
two-method campaign selects PDF with `--compare-method pdf-similarity`; its
default remains CGNS. Production four-method commands belong in the six-view guide.

## Historical GPU validation

These are earlier recorded findings, not fresh measurements. Raw artifacts under
`runs/falcor-pdf-pt-validation-20261114` were removed; they cannot be rechecked
from those paths. The completed six-view archive is separate. Validation used
D3D12, RTX 4060 Laptop GPU, driver 560.94, temporal on, 1 spp and matched camera,
transport and ordinary spatial proposal.

Fourteen scouts completed with 159 HDR frames. Classroom comparisons used 96x64,
12 frames, seeds 0–11 and no warmup; Bistro interior's glTF runtime completed
three frames at seeds 0–2 with scene audit.

| Classroom comparison | Mismatching pixel-frames | Maximum absolute HDR error |
| --- | ---: | ---: |
| Forced one vs native, matched diagnostics | 0 | 0 |
| Forced zero vs independent center-only | 0 | 0 |
| Native diagnostic vs color-only; forced one vs color-only; normal PDF diagnostic vs color-only | 13/73,728 in each comparison | 5.96046448e-8 |

Matched controls also agreed on reservoir M/weight/target; zero/center agreed on
all four RGBA readbacks. The largest color-only difference was blue at frame 3,
pixel (6,18): 0.5236045122 versus 0.5236044526. Native readback alone reproduced
it when NRD outputs specialized the graph; the exact compiler instruction was
not isolated. The historical strict analyzer flagged it; the separate tolerance
report allowed 1e-6 only across that output switch.

A 160x90, 19-frame reset/cut sequence reached count 5.298162 after six warmup
frames. Counter reset at seed 6 and a one-metre camera translation at seed 106
matched fresh A/B/count bitwise across 14,400 pixels; new count was at most one,
with 2,876 and 3,962 evidence pixels. Native `tracer.reset()` leaves lighting
history, so full HDR equality required replacing the graph. At seed 8, new graphs
matched HDR, M/W/target and direction statistics exactly. Resolution changes,
disocclusion, zero energy and nonfinite reprojection were tested in native CPU
history code; the GPU reset suite kept resolution fixed within each graph.

Independent process pairs, each averaged over 12 frames and all pixels using
Rec.709 luminance, gave:

| First path seed | Ordinary | PDF |
| ---: | ---: | ---: |
| 0 | 0.351808094 | 0.351805666 |
| 64 | 0.383901574 | 0.383886610 |
| 128 | 0.370396767 | 0.370385739 |
| 192 | 0.347976141 | 0.347958912 |

The paired mean difference was -1.14123e-5 (-0.00314%; standard error 3.25702e-6).
All four differences were negative; one view and four short blocks against
ordinary PT cannot establish absolute bias, converged quality or performance.

[Pair reconstruction](../../scripts/falcor/pdf_pt_pair_check.py) found 10,461
positive-confidence proposals, 2,059 downweighted, h in [0.6163001,1], and maximum
history count 9.192797. Primary/deep NEE and BSDF hits supplied evidence in
5,025/6,150/4,723 pixel-frames, with overlap. Independent h evaluation differed by
at most 4.292e-6 (frame 12, pixel (10,40)), within float32 tolerance 1e-5.
Recorded h times independently read pre-spatial M reproduced effective M exactly,
and every observed output M matched workload cSum.

## Tests and limits

[CPU/source/native groups](../../tests/README.md) cover candidate direction,
history, fractional confidence, zero/failed shifts and runtime/capture contracts.
Native tests execute composed production arithmetic and reject seven corrupted
normalization variants, including stale M, missing MIS confidence, double h and
extra M division. They do not launch a renderer.

One vMF cannot represent multiple transport lobes or later path topology. Shared
initial samples correlate the heuristic with lighting estimates; motion rejects
history conservatively, while lighting/material edits may leave stale evidence.
Added reflected state costs memory/bandwidth. Multiple/paired neighbors, area
reservoirs, DoF, dynamic scenes, other samplers and transport targets remain
outside the qualified scope. Follow the [protocol](../../experiments/protocol.md)
for references, independent trials and timing.
