# Analysis

`di_reuse.py` validates saved HDR captures and pose-matched references, then writes
CSV measurements and a concise academic report. `di_reuse_report.py` contains
presentation code: one endpoint error/cost table, consolidated error trajectories,
a linked image comparison and explicit reference precision limits.

```powershell
python scripts/analysis/di_reuse.py --baseline runs/di-3scenes-seed1 --references runs/di-3scenes-reference --output runs/di-3scenes-analysis
```

Outputs include `summary.md`, complete metric/phase-timing CSVs, pixel-tail
diagnostics and input/code hashes in `analysis.json`. Existing output directories
are never overwritten. See [the protocol](../../experiments/suites/di-reuse.md#analysis-outputs).

For a versioned result, retain a report, its figures, the CSV rows it uses and
provenance under `results/summaries/<experiment>/`. Keep raw HDR, logs and caches
in ignored `runs/`; avoid duplicating per-seed aggregates for a single-seed report.
