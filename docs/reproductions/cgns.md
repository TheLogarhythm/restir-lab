# CGNS on ReSTIR DI

Independent DI adaptation of [Junkins et al. (2026)](https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/), Eqs. 14–15 and Algorithm 1, using [author code `f28d553`](https://github.com/orion-junkins/ReSTIR-CGNS/tree/f28d553f3b2552b1be829feffea6d1abb1945e1d) as an algorithm reference. The paper evaluates PT; this implementation retains RTXDI 3.1's DI estimator and ray-traced normalization.

## Run

```powershell
python scripts/run/build_rtxdi_cgns.py
python scripts/run/rtxdi_reuse.py --scene cornell-box --mode combined --cgns --diagnostics
```

Use `--cgns-build` with `cgns` absent/false for an off run in the same executable; `--windowed` displays the controlled sequence. Baseline and PDF commands remain available. The build restores upstream source/binaries and publishes `FullSampleCgns.exe` with separate shaders and fingerprints.

Config: `cgns` (false), `cgns_candidates` (32, range 1–32), `cgns_early_stopping` (true). Existing `spatial_neighbors` (1–4, no greater than K) and `spatial_radius` apply; defaults are 4 and 32 pixels. Supports unfused spatial/combined DI with initial visibility, ray-traced correction and no checkerboard. PDF + CGNS is not enabled together.

## Implementation

- [Shared core](../../scripts/run/rtxdi_experiments/CgnsMath.h): position × normal score, Ω=0.05, β=8; camera distance sets world-space scale. A-Chao selects one neighbor; A-ES selects multiple with log-domain priorities for very small positive scores.
- [Selection pass](../../scripts/run/rtxdi_experiments/CgnsSelectNeighbors.hlsl): current G-buffer, precomputed 8192 R2/concentric offsets, separate RNG and unique rounded candidate pixels. Empty selections retain the center reservoir.
- [DI adapter](../../scripts/run/rtxdi_cgns.py): both merging and normalization read the same stored neighbor list; reservoir M is unchanged. Continuous scoring replaces spatial normal/depth/material rejection, while surface validity, target evaluation and visibility checks remain.
- Differences from the reference: zero scores are rejected rather than floored to epsilon; background/self/duplicate candidates are skipped; offsets use float32 instead of signed-byte quantization. Early stopping follows author code (`score >= 0.5`, count `>= N`), whereas the paper prose says `> N`.

`neighbor_selection_ms` measures the new pass; `gpu_ms` includes it. The existing four-slot PT neighbor buffer is reused. Extra allocation is 4 bytes/pixel for counters plus 64 KiB for offsets, also allocated when off. With `--diagnostics`, captures retain `.cgns` counters and their summaries/hashes in `captures.json` (tried/scored/selected, averaged over active surface pixels).

The shared experiment patch also corrects RTXDI's emitter geometry lookup: decode the local 12-bit index before adding the global geometry base. This fixes incorrect lighting on the two Zero-Day scenes, which exceed 4096 geometries. Controlled builds use isolated shaders; the changed lighting fingerprint requires rebuilding other variants and generating matching references before new comparisons.

## Validation

Checked 2026-10-25: baseline/CGNS Release builds, 445 portable CPU tests, 11 native tests, and 40 short GPU runs across all 10 configured scenes at 1280×720 (16 frames). CGNS-off matched the baseline exactly at frames 1 and 16 in every scene. Single/four-neighbor runs passed finite/nonnegative HDR, counter, timing and initial/spatial reservoir M checks; full control/RNG schedules also matched. Temporary details are under `tmp/cgns-review/all-scenes-final/`; these are functional checks, not quality or performance results.

CPU tests execute the shared scoring/WRS functions and actual adapted DI loops, including normalization, visibility, empty selections and off-path equivalence. Run `python scripts/check_tests.py` and `python scripts/check_tests.py --suite native` (MSVC).

Formal quality/performance evaluation remains a separate step. CGNS may increase spatial covariance at fixed radius; lower image error alone does not establish better temporal stability.
