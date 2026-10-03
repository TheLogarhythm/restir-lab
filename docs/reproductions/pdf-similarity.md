# PDF Similarity on RTXDI DI

Independent adaptation of [Tokuyoshi 2023](https://doi.org/10.1145/3585501), Algorithm 2 and Eqs. 9–18, on pinned RTXDI 3.1.0. This is not the author's MiniEngine implementation.

## Use

```powershell
python scripts/run/build_rtxdi_pdf.py
python scripts/run/rtxdi_reuse.py --scene cornell-box --pdf-similarity --scenario all
python scripts/run/rtxdi_pdf_viewer.py --scene cornell-box
```

The extension uses `FullSamplePdf.exe` and separate shaders. For the same build with PDF similarity off, use `--pdf-build --mode spatial` or `--pdf-build --mode combined` without `--pdf-similarity` and with the switch absent/false in the input config. The viewer provides a toggle and history reset under **Direct Lighting > ReSTIR**.

Supports primary DI with unfused spatial/combined reuse, initial visibility, ray-traced spatial correction and no checkerboard. Incompatible viewer settings disable the extension.

## Algorithm and differences

- [Direction state](../../scripts/run/rtxdi_experiments/PdfSimilarity.hlsli): reuse visible initial RIS samples in a separate temporal reservoir; combine direction moments using pairwise MIS weights. No extra visibility rays or spatial direction reuse.
- [Scalar math](../../scripts/run/rtxdi_experiments/PdfSimilarityMath.h): vMF fitting, smoothing and similarity with alpha=100, beta=10, lambda=1000. Initial M is normalized to 1; previous direction M is capped at 20 before adding the current sample.
- [RTXDI adapter](../../scripts/run/rtxdi_pdf.py): blend geometry/material acceptance with PDF similarity; scale neighbor M in both spatial selection and normalization. Retains RTXDI's light/UV representation and multi-neighbor spatial MIS, rather than the paper's pairwise spatial scheme.
- [Viewer adapter](../../scripts/run/rtxdi_pdf_viewer_adapt.py): GUI and interactive lifecycle changes, separate from algorithm integration.
- Nearest-texel reprojection checks geometry/materials; invalid or zero-weight history is discarded. Resets clear both direction banks. Separate RNG preserves the lighting sampler stream.

The two banks cost **64 bytes/pixel** (126.6 MiB at 1080p), even with the switch off. Direction updates are timed in the initial pass. Shared samples and visibility reuse introduce bias; one vMF cannot represent multiple lobes well, and history can lag lighting changes. Eq. 14's uniform-lobe cases use similarity 1 for two uniform lobes and 0 for only one.

## Validation

Recorded checks (2026-10-02–03): Release build, Cornell static/motion/reset and Arcade static smoke runs; finite captures and exact reset/fresh agreement. Extension-off captures matched baseline exactly except combined reuse (at most two FP16 ULPs). GUI smoke runs covered toggles and incompatible settings. These checks establish runtime behavior, not quality or performance gains.

CPU tests execute the shared direction update and adapted RTXDI spatial loops, covering zero-weight history, unequal target PDFs and fractional M. Regression tests pass; the rebuilt variant passes Cornell PDF on/off finite-HDR and reset/fresh checks, plus a bounded viewer run. Conventional reference configs explicitly disable PDF Similarity for new and resumed streams.

[Analysis](../../scripts/analysis/README.md) separates methods in metrics, timings and figures; matched on/off report generation passes synthetic fixtures. Formal evaluation remains pending: the saved three-scene reference index lacks current lighting provenance and cannot be reused until corrected or regenerated. See the [experiment protocol](../../experiments/protocol.md).
