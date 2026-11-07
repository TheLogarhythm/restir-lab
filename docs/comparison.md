# Comparison workflow

One configuration and CLI serve DI, GI, PT or selected groups. The supported
acquisition protocol is static: fixed camera, warmup, then one capture frame.

## Configuration and execution

The [six-method config](../experiments/configs/cgns-di-gi-pt-static.json) selects
five views at 1920×1080, seed 1, 40 warmup frames, frame 41, history 20, four
neighbors, radius 32 and CGNS K=32 with early stopping. DI explicitly reuses the
November 3 captures. The [DI example](../experiments/configs/di-comparison-static.json)
requests rendering. Retain the desired groups, methods and reference entries to
configure a subset; each method source explicitly selects reuse or rendering.

Schema 3 separates algorithm, reuse mode, acquisition, view, seed, capture frame,
reference target/budget and display. Generic config validation allows smaller
fixtures; formal preparation separately enforces the approved experiment budget.
GI/PT support spatial or combined reuse. Sequence requests fail explicitly.

```powershell
python -B scripts/run/rtxdi_comparison.py plan --config experiments/configs/cgns-di-gi-pt-static.json
python -B scripts/run/rtxdi_comparison.py prepare --root runs/NEW --preview-check PREVIEWS.json --conformance CONFORMANCE.json
python -B scripts/run/rtxdi_comparison.py start --root runs/NEW
python -B scripts/run/rtxdi_comparison.py status --root runs/NEW
python -B scripts/run/rtxdi_comparison.py resume --root runs/NEW --reason "Diagnosed failure"
```

Preparation requires matching build/source conformance and camera checks. It
freezes config, builds, assets, reused inputs and code. Detached workers preserve
exclusive locks, PID identity and ownership. Completed tasks/checkpoints are
validated before reuse; failed or ambiguous attempts require diagnosis.
`status` is read-only unless `--save-status` is supplied. Numerical completion
reaches `awaiting_ui`; `confirm-ui --root runs/NEW --reason "..."` records actual
inspection separately.

## Analysis and display

Choose new output directories; analysis and report generation never render.

```powershell
python -B scripts/run/rtxdi_comparison.py analyze --root runs/OLD --output runs/derived/analysis
python -B scripts/run/rtxdi_comparison.py report --analysis runs/derived/analysis/analysis.json --output runs/derived/report
python -B scripts/run/rtxdi_comparison.py verify --root runs/OLD --analysis runs/derived/analysis/analysis.json --report runs/derived/report/report.json
```

Analysis indexes view / capture frame / algorithm / method / seed. Compute each
seed's scene-linear luminance SMAPE first, then average errors within that frame:
`100*abs(Y-Yref)/(abs(Y)+abs(Yref)+1e-4)`, Rec.709 luminance, float64, no factor 2.
Positive improvement is original minus CGNS in percentage points; relative
improvement is 100 times that difference divided by original error. Legacy DI
used mean(pixel differences) for the displayed improvement; standardizing to the
grouped difference-of-means changes rounding by at most 1.98e-14 pp in regression.
Method SMAPE and pixel error/delta arrays remain exact.

Groups share validated primary geometry. Whole-image metrics include background;
hard masks retain radius 30 and the hardest 10% of valid surface pixels. Seeds
and frames are separate dimensions. Merged-neighbor counts include zero-weight
streams and repeated coordinates. Capture GPU time, run mean and CGNS selection
time have separate fields; timing excludes startup, export, present and UI.

Radiance previews use Reinhard+sRGB with +5 EV for Bistro interior, +3 exterior,
+6 Emerald Square and 0 otherwise. All methods and references in a view/frame
share exposure. Error maps and metrics do not receive exposure. Historical
adapters default to EV0; `report --display DISPLAY.json` applies the preferences
without recomputing metrics. Display JSON supplies `exposure_ev` for each view
and `delta_range_pp`. Every derived PNG binds its source hash and transform.

HTML supports group/view/frame/seed selection, synchronized zoom/pan, error maps,
color scales and PNG export. Verification independently recomputes analysis,
checks image pixels and reconstructs HTML; it does not certify UI interaction.

## Historical data and boundaries

See the [spatial-reuse study](reproductions/spatial-reuse.md) for transport targets,
reference samples and retained-result limits. Explicit schema-1/2 readers retain
fixed-budget and paired-precision reference checks; missing/incompatible inputs
fail. `fixed_reference.py` remains in use by reference tools and tests.

Historical artifact validation checks original receipts. Reanalysis writes new
provenance. Current-code rendering/resume requires a new schema-3 plan matching
current code, builds and conformance; old plans are never rewritten.
`--source-archive ARCHIVE.zip` is limited to historical analysis/verification and
checks every original source/evidence hash. Non-source evidence must still match
its original path. The local `cgns-di-gi-pt.md` is one such bound document and
must retain its original bytes. The old `rtxdi_static_batch.py` forwards recorded
worker/status commands; remove it after those callers migrate.

Sequence rendering still needs trajectories, scene time/animation state,
capture/reset schedules, per-frame references and masks, and independent temporal
statistics. Moving objects invalidate static masks even with identical asset
hashes and cameras. Existing sequence analysis remains separate.
