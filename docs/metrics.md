# Shared quality and correlation metrics

[Sequence analysis](../scripts/analysis/sequence_metrics.py) compares saved runs without rendering.
[Pure covariance functions](../scripts/run/experiment/covariance_metrics.py) and the
[streaming API](../scripts/run/experiment/sequence_metrics.py) also accept custom loaders/arrays.
Existing [SMAPE/TRMAE interfaces](../scripts/run/experiment/error_metrics.py) and historical values are unchanged.

## Definitions and aggregation

Input is scene-linear Rec.709 RGB; luminance is `Y = .2126 R + .7152 G + .0722 B`.
Calculations accumulate float64, without clipping, display transforms or motion reprojection.

| Metric | Definition | Output |
| --- | --- | --- |
| SMAPE | `100 * abs(Y-referenceY)/(abs(Y)+abs(referenceY)+1e-4)` per pixel | percent; no factor 2 |
| Relative temporal autocovariance | `sum_n(z[n,t,i] * z[n,t+lag,i])/(N-1)`, lag=3 | signed, dimensionless |
| Average radial relative spatial covariance | `sum_n(z[n,t,i] * z[n,t,j])/(N-1)`, average j in radius=8 disk, then centers | signed, dimensionless |

Here `mu[t,i] = mean_n(Y[n,t,i])` and `z = (Y-mu)/(mu+epsilon)`, epsilon=1e-4.
Independent trials are **runs**, never frames. The high-quality reference is used only for SMAPE.
Covariance epsilon is configurable; SMAPE retains its historical epsilon. Negative covariance is retained.
Finite negative inputs are not clipped; a zero normalization denominator or nonfinite computation is an error.

Local conventions where author analysis is unavailable:

- Spatial covariance uses the **center-inclusive**, closed integer disk `dx²+dy² <= radius²`.
  Clip at image edges and divide each center by its actual neighbor count, including background.
- Masks affect only final aggregation. Spatial neighbors may lie outside the region; temporal pairs use
  the start-frame mask and the same screen pixel at the endpoint.
- First average SMAPE over runs or compute covariance across runs; then average selected pixels per
  frame; overall values equally weight eligible frame means. Changing mask sizes do not reweight frames.
- Reject duplicate/misaligned runs or frames, undeclared gaps, malformed/nonfinite images, N<2,
  invalid lag, and empty requested regions. Temporal pairs never cross resets or segment boundaries.
  The array-only temporal helper assumes a single contiguous segment; the sequence API checks metadata.

Outputs include per-frame/overall metrics, pixel-frame counts, valid temporal frame-pair counts,
pixel-pair counts and run×pixel-pair counts. For 512 continuous measured frames, lag=3 yields
509 frame pairs; no run count or sequence length is hardcoded. No uncertainty model is selected here.

## Shared easy/hard regions

[Classification](../scripts/run/experiment/pixel_regions.py) uses one primary geometry source for all methods/runs.
A neighbor passes when `dot(shading_normal_i, shading_normal_j) >= .5` and
`abs(camera_distance_i-camera_distance_j) < .1*camera_distance_i`. There is no material test.
Camera distance is radial distance, not view-space Z.

The independent classification radius defaults to 30 pixels. Enumerate the full closed integer disk,
exclude self and out-of-image locations; in-bounds invalid/background neighbors count as failures in
the denominator. Only valid surface centers are ranked. Hard is the lowest
`floor(valid_pixels * p/100)` rates, p=10 by default; ties use row-major order.
Easy is the remaining valid surfaces; all includes the entire image, including background.
No-neighbor rates are zero. Classification can return empty masks; requesting their metric mean raises
an explicit error. Default reporting is all/hard when geometry is supplied, otherwise all; easy is optional.

Geometry export is opt-in: `rtxdi_reuse.py --geometry-export` (rebuild the experiment variant first).
It reads existing R32_FLOAT view depth and packed R32_UINT shading normals outside render timers,
without changing sampling. Lossless `.geometry.npz` stores these raw arrays, FOV and schema;
[decoder](../scripts/run/experiment/geometry_io.py) reconstructs radial distances with pixel-center
perspective rays and decodes Donut's octahedral normals. Background uses depth 65504.
Capture records retain hashes. Static masks may be reused when geometry, camera and surface settings
are unchanged, including lighting-only changes; otherwise provide per-frame geometry.

## Author evidence and limits

Checked 2026-10-26 against [CGNS paper](https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/),
§7, Appendix A, and author commit
[`f28d553f3b2552b1be829feffea6d1abb1945e1d`](https://github.com/orion-junkins/ReSTIR-CGNS/tree/f28d553f3b2552b1be829feffea6d1abb1945e1d).

- **Paper:** §6 footnote 3 specifies SMAPE scale100/epsilon1e-4; Appendix A Eqs.16–17 specify across-run
  sample means, N−1, epsilon1e-4, lag3 and radius8. Despite introductory “ground truth” wording,
  the equations explicitly normalize covariance by sample means. §7 ranks the hardest10% at radius30.
- **Code confirms:** [resolve](https://github.com/orion-junkins/ReSTIR-CGNS/blob/f28d553f3b2552b1be829feffea6d1abb1945e1d/Source/RenderPasses/CGNS/ResolveReSTIR.cs.slang#L54-L62)
  writes linear `integrand * UCW`. [Graph](https://github.com/orion-junkins/ReSTIR-CGNS/blob/f28d553f3b2552b1be829feffea6d1abb1945e1d/scripts/CGNS.py#L27-L41)
  disables accumulation and has no denoiser, but exposes **both** a linear accumulation-pass output and
  a ToneMapper→FrameDumper branch.
  [Disabled accumulation](https://github.com/orion-junkins/ReSTIR-CGNS/blob/f28d553f3b2552b1be829feffea6d1abb1945e1d/Source/RenderPasses/AccumulatePass/AccumulatePass.cpp#L208-L212)
  blits. [FrameDumper](https://github.com/orion-junkins/ReSTIR-CGNS/blob/f28d553f3b2552b1be829feffea6d1abb1945e1d/Source/RenderPasses/FrameDumper/FrameDumper.cpp#L111-L158)
  exports its tone-mapped input when enabled; defaults permit exposure, ACES/clamping and sRGB/8-bit conversion.
  [Mogwai capture](https://github.com/orion-junkins/ReSTIR-CGNS/blob/f28d553f3b2552b1be829feffea6d1abb1945e1d/Source/Mogwai/Extensions/Capture/FrameCapture.cpp#L244-L251)
  can instead export marked floating-point outputs as EXR without an added display transform.
  A source float32 texture does not by itself establish encoded EXR precision.
- **Code confirms geometry:** [traditional test](https://github.com/orion-junkins/ReSTIR-CGNS/blob/f28d553f3b2552b1be829feffea6d1abb1945e1d/Source/RenderPasses/CGNS/SpatialResampling.rt.slang#L123-L136)
  and [G-buffer construction](https://github.com/orion-junkins/ReSTIR-CGNS/blob/f28d553f3b2552b1be829feffea6d1abb1945e1d/Source/RenderPasses/CGNS/GenerateCGNSGBuffer.cs.slang#L34-L39)
  establish the thresholds, shading normals and radial distance above.
- **Unverified:** no paper-specific offline metric/mask script or export→metric invocation was found in
  the inspected public repository. Thus the actual paper metric input, offline processing, file precision,
  luminance coefficients, disk center/boundaries, ranking ties and region support remain unknown.
  Generic Falcor/Jeri image-test losses are different formulas and are not evidence of paper analysis.
  Rec.709, `abs(Y(I)-Y(G))` rather than `Y(abs(I-G))`, and the discrete policies above are explicit local choices.

Our input chain is independently verified:
[controlled renderer patch](../scripts/run/rtxdi_experiments.patch) →
[raw HDR staging copy](../scripts/run/rtxdi_experiments/LabExperiment.h) →
[lossless half-to-float32/PFM export](../scripts/run/experiment/artifacts.py) →
[PFM reader](../scripts/run/experiment/images.py).
Method images are not image-accumulated or denoised; no exposure/pre-exposure, tone mapping, gamma or
extra clipping is applied on this metric path. References intentionally use accumulated float32.
Method HDR retains half precision and renderer behavior, including transparent overlays and the upstream
compositor's NaN-to-blue fallback; finite checks cannot recover NaNs already replaced there.
PNG previews separately apply exposure, Reinhard, sRGB and clamping and are never metric inputs.

## Use

Provide a small JSON input description, with paths relative to that file:

```json
{
  "methods": {"baseline": ["run-a", "run-b"], "cgns": ["run-c", "run-d"]},
  "frames": [41, 42, 43, 44],
  "references": "matched-reference.pfm.gz",
  "geometry": {"run": "run-a", "static_frame": 41},
  "lag": 3,
  "radius": 8,
  "classification_radius": 30,
  "hard_percent": 10,
  "regions": ["all", "hard"]
}
```

```powershell
python scripts/analysis/sequence_metrics.py --inputs inputs.json --output tmp/quality-check
python scripts/check_tests.py
```

Runs must be completed controlled-run directories with original config/manifest/capture hashes.
The adapter checks full history schedules, targets, shared lighting implementation, independent RNG
streams, matched seed coverage across methods and identical repeat settings within a method.
`references` may instead map frame IDs to paths, or be omitted for covariance-only analysis;
reference target/convergence quality remains the caller's responsibility.
Omit `static_frame` for per-frame geometry. Masks are generated once and reused across methods;
their hashes and counts are saved with the results. Outputs are `analysis.json`,
`frame-metrics.csv`, `summary.csv` and shared region archives; existing outputs are not overwritten.

The library `analyze_sequence([SequenceRun(id, [Frame(index, image, reset, segment), ...]), ...])`
supports explicit discontinuous segments and static/per-frame/callable masks. It loads at most two
frames across runs into luminance stacks and computes spatial maps in row blocks with halo.
The CLI intentionally requires one continuous measurement interval; do not bridge sparse captures.

Validation: hand-computed covariance/lag/negative/zero cases, disk boundaries, ties, streaming versus
direct calculations, invalid histories/inputs and unchanged legacy SMAPE. A short Cornell Box check
(3 runs × 4 frames, 64×48) verified identical geometry across seeds, exact HDR equality with export
on/off, and the complete all/hard analysis path. This is functional validation, not a quality campaign.
