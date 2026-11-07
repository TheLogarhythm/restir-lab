# CGNS spatial neighbor selection

Local adaptation of Junkins et al. (2026), using
[author code f28d553](https://github.com/orion-junkins/ReSTIR-CGNS/tree/f28d553f3b2552b1be829feffea6d1abb1945e1d)
as an algorithm reference. The [spatial-reuse study](spatial-reuse.md) compares
original and CGNS neighbor selection within DI, GI and PT.

## Implementation

- [CgnsMath.h](../../scripts/run/rtxdi_experiments/CgnsMath.h) scores position and
  normal compatibility with position scale 0.05 and normal exponent 8; camera
  distance sets world-space scale. A-Chao selects one slot, A-ES multiple slots.
- [CgnsSelectNeighbors.hlsl](../../scripts/run/rtxdi_experiments/CgnsSelectNeighbors.hlsl)
  uses 8192 R2/concentric offsets, separate RNG and distinct rounded pixels.
  Background, self, duplicate and zero-score candidates are skipped. Offsets use
  float32; early stopping follows the pinned author code.
- The [DI adapter](../../scripts/run/rtxdi_cgns.py) preserves geometry and optional
  material rejection after preselection. Rejected neighbors are not replaced.
  Merge and normalization use the same list; an empty list retains the center
  reservoir. Resolved settings record `cgns_rejection_policy: upstream`.

Defaults: K=32, four neighbors, radius 32 pixels, early stopping enabled. DI
supports unfused spatial/combined reuse with initial visibility and ray-traced
correction, without checkerboard or simultaneous PDF Similarity.

## Run and diagnostics

```powershell
python scripts/run/build_rtxdi_cgns.py
python scripts/run/rtxdi_reuse.py --scene cornell-box --mode combined --cgns --diagnostics
```

Use `--cgns-build` without `--cgns` for the same-executable off control.
`neighbor_selection_ms` is included in total GPU time. Counter/offset storage
adds 8 bytes/pixel plus 64 KiB; the existing neighbor buffer is reused.
Merged-neighbor counts include zero-weight streams and repeated coordinates.
See the [comparison guide](../comparison.md) for collection and analysis.
The shared build also corrects packed emitter-geometry indexing; comparisons
require matching lighting/build fingerprints.

The October 28 DI campaign bypassed rejection; the November 3 campaign preserved
it. Keep their results distinct. Native tests cover rejection, normalization
and CGNS-off equivalence. Functional checks alone establish neither a quality
gain nor temporal stability.
