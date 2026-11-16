# Analysis

For shared SMAPE, temporal/spatial covariance and geometry-based easy/hard regions,
see [quality metrics](../../docs/metrics.md) and `sequence_metrics.py`.

`di_reuse.py` validates saved HDR captures and pose-matched references, then writes
CSV measurements and a concise academic report. `di_reuse_report.py` contains
presentation code: one endpoint error/cost table, consolidated error trajectories,
a linked image comparison and explicit reference precision limits.

```powershell
python scripts/analysis/di_reuse.py --baseline runs/di --references runs/di-reference --output runs/di-analysis
```

The command requires complete HDR runs and references. The [historical DI baseline](../../results/summaries/di-baseline/README.md) retains records and CSVs for reporting; PNG/HDR inputs are unavailable locally. Pixel-error recalculation requires restored inputs or new renders.

For PDF on/off, pass both suite directories after `--baseline` and an explicit
`--output`. Use the same PDF-enabled build for both runs. CSVs, plots and timings
separate methods; other settings, seeds, capture frames and targets must match.

Outputs include `summary.md`, complete metric/phase-timing CSVs, pixel-tail
diagnostics and input/code hashes in `analysis.json`. Existing output directories
are never overwritten. See [the protocol](../../experiments/suites/di-reuse.md#analysis-outputs).

For a versioned result, retain a report, its figures, the CSV rows it uses and
provenance under `results/summaries/<experiment>/`. Keep raw HDR, logs and caches
in ignored `runs/`; avoid duplicating per-seed aggregates for a single-seed report.

## Archived PDF campaign

The local PDF archive at `runs/pdf-similarity-archive/` retains all formal CSVs and timing rows, full video-source PNG and selected HDR. Run `python -B scripts/analysis/pdf_archive.py verify --decode` to check stored hashes, PNGs and timing coverage. Run `python -B scripts/analysis/pdf_archive.py numerical` to recompute all 13 conditions and check maps against pre-deletion verified array hashes. Neither command launches a renderer.

CSV plots can be redrawn directly. Sparse pixel/ROI/local-TRMAE analysis uses archive-inputs.json and retained HDR; original receipts keep historical paths. Full-sequence HDR analysis and full reference convergence/resumption require new renders. Old MP4s and NPZ are intentionally absent. The archive script's prepare/source-gate actions belong to the completed migration, not ordinary reanalysis.

## Compact PT stage archive

`python -B scripts/analysis/pt_stage_archive.py` verifies the view-based archive
without rendering or writing outputs. Current paths are in its manifest;
original batch manifests are provenance, not resumable batches. See the
[six-view guide](../../docs/reproductions/pt-6-views-spatial-compare.md).

For selected captures, use `backends.falcor.archive.read_archive()` and its
`quality_records()`, `quality_runs()` and `timing_records()` methods. The
[shared analysis guide](../../docs/shared-analysis.md#fixed-view-pt-archive)
shows four-seed loading and independent-sequence validation. This reads saved
results only; new batches belong in `runs/pt-fixed-view-batches/` and new reports
must be outside the immutable stage archive.

The obsolete `falcor_three_methods` report and its `spatial_three_methods` /
`spatial_reuse_audit` collectors were retired after stage archival. Historical
reports remain unchanged; their original commands require their matching source
snapshot and original inputs.
