# Six-view ReSTIR PT comparison

The completed stage is the immutable local archive at
`runs/pt-6-views-spatial-compare/`. Its `README.md` describes the retained data,
and `manifest.json` defines current paths; original batch IDs and receipts remain
provenance. These generated files are not included in a Git checkout. New captures use
`runs/pt-fixed-view-batches/<id>/`, never the archive as an output/resume directory.

Method details: [CGNS](falcor-cgns-pt.md) and [PDF Similarity](falcor-pdf-pt.md).
Scene assets, reusable views and reference bindings are documented in
[scene preparation](../../experiments/configs/falcor-pt-spatial-comparison/PREPARATION.md).
Implementation decisions and dated validation are in the
[maintenance history](../superpowers/spatial-reuse-comparison.md).

## Configuration and retained data

The [suite](../../experiments/configs/pt-6-views-spatial-compare.json) uses Bistro
interior/exterior, Classroom, Emerald Square, Veach Ajar and Zero Day Measure Seven.
The [base experiment](../../experiments/configs/falcor-pt-spatial-comparison/restir-pt-spatial-comparison.json)
sets 1920x1080, 1 spp, 10-bounce transport, point/unpaired reservoirs, one spatial
iteration/neighbor, radius 30 and native temporal history 20. Existing matched
16384-spp references are reused.

| Label | Spatial method | Temporal |
| --- | --- | --- |
| `temporal-off` | Ordinary | Off |
| `temporal-on` | Ordinary | On |
| `cgns` | Cached CGNS | On |
| `pdf` | First-hop PDF Similarity | On |

| Collection | Seeds | Warmup | Saved/measured frames | Total |
| --- | --- | --- | --- | --- |
| Quality | 0, 100000, 200000, 300000 | 1–40 | Originally FLOAT32 EXRs 41–56 | 96 captures, 1536 per-frame statistic rows |
| Timing | 0 | 1–40 | GPU frames 41–104; render 105 drains the profiler | 24 captures, no EXRs |

Each job starts a fresh process/history. Path seed is `offset+frame-1`; reuse
seed is zero on frame 1 and `offset+frame-2` afterward. The first temporal pass
is skipped. All quality jobs precede timing; method order rotates by view and
is frozen in the resolved config. Diagnostics, accumulation, denoising and
trajectories are disabled.

The archive now consolidates measurements and presentation outputs. It retains
CSV/JSON statistics, unclipped NPZ maps, selected strip samples, five display PNGs
per view, current plots and original capture/runtime/timing provenance. The 1536
method EXRs and six obsolete 8192-spp reference checkpoints were retired after
hash verification. Six final 16384-spp references remain under `assets/references/`.

Veach timing uses the latest recheck; Emerald's four timings remain excluded from
performance aggregates. `statistics/stage-summary.csv` and `timing-events.csv`
contain the current summaries; original timing records and exclusions are in
`records/`. Original manifests contain historical paths; the root manifest and
`records/provenance/relocations.json` describe current locations. The retired HDR
inventory preserves hashes but does not imply recoverability.

## Read and verify the archive

These commands do not render or build runtimes:

```powershell
$py = 'build/falcor/verify-env/Scripts/python.exe'
& $py -B scripts/analysis/pt_stage_archive.py --inspect
& $py -B scripts/analysis/pt_stage_archive.py
& $py -B -m scripts.falcor.fixed_view_suite --check
```

`--inspect` lists selection metadata; the default archive verifier hashes the
full inventory and checks references, schedules and timing selection. The suite
check validates current scene/reference inputs. Neither recomputes quality metrics.

[Shared analysis](../shared-analysis.md#fixed-view-pt-archive) describes the
statistics-only archive. To change axes, colors or layout without raw HDR:

```powershell
& $py -B runs/pt-6-views-spatial-compare/tools/replot.py --output build/pt-six-view-replot-new
```

This uses saved numerical maps and strip samples, with NumPy, Pillow and Matplotlib.
It does not recompute metrics. Arbitrary new metrics, covariance lags/radii and new
temporal strip locations require the retired method HDR or new renders. The old
raw-HDR adapter remains usable with older full-image archives, not this compact one.

## New batches

Run from the repository root using the environment with OpenEXR and NumPy.
Keep the checkout, configs, assets and runtime fixed through a batch. Leave
`FALCOR_DEVMODE` unset and avoid competing GPU workloads during collection.

```powershell
$py = 'build/falcor/verify-env/Scripts/python.exe'
$config = 'experiments/configs/pt-6-views-spatial-compare.json'
$batch = Join-Path 'runs/pt-fixed-view-batches' (Get-Date -Format 'yyyyMMdd-HHmmss')

& $py -B -m scripts.falcor.fixed_view_suite --config $config --check
if ($LASTEXITCODE -ne 0) { throw 'Input check failed' }

# Builds/verifies private runtimes and freezes inputs; no rendering.
& $py -B -m scripts.falcor.fixed_view_suite --config $config --prepare --output $batch
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed' }

# Launches all quality and timing jobs.
& $py -B -m scripts.falcor.fixed_view_suite --config $config --run --output $batch
if ($LASTEXITCODE -ne 0) { throw "Inspect $batch/manifest.json" }
```

To retry, reuse the exact existing `$batch` path and append `--retry-failed` to
the run command. Completed attempts are verified; failed/incomplete attempts are
retained and a new numbered directory is created. Changed inputs/code/runtime
require a new batch. `--plan` only prints the schedule.

Batch metadata includes resolved config, reference paths/hashes, runtime receipts
and before/after environment records. Captures live at:

```text
jobs/<view>/<label>/quality/seed-000000/attempt-001/
jobs/<view>/<label>/quality/seed-100000/attempt-001/
jobs/<view>/<label>/quality/seed-200000/attempt-001/
jobs/<view>/<label>/quality/seed-300000/attempt-001/
jobs/<view>/<label>/timing/attempt-001/
```

Each attempt retains manifest, collector/resolved graph, camera, scene state and
renderer log; Bistro interior also retains its adapted scene audit. Quality uses
native `capture.PathTracer.color.<frame>[.RGBA].exr` names. Timing retains raw
`timings.json`, `timing-validation.json` and aligned `frames.csv`. GPU/driver,
temperature, clocks, power and VRAM snapshots before each job are not continuous
telemetry or peak-memory measurements.

## Metrics and timing boundaries

| Metric | Required evidence |
| --- | --- |
| SMAPE | Linear HDR and matched reference |
| GPU frame/pass time | Native profiler events; repeated runs for repeatability |
| Spatial relative covariance | At least two independent aligned quality realizations |
| Temporal relative covariance | The same, plus consecutive aligned frames |
| Separate visibility-test time | Unavailable in current instrumentation |

GPU frame time is `/onFrameRender/gpu_time`. Initial sampling, temporal/spatial
workload/retrace/merge and CGNS cache/selection times are retained when exposed.
Parent events include children: do not add nested cache/selection times to spatial
time again. Missing events are unavailable, not zero. CPU wall time is matched
to the same frame ID despite one-frame-delayed GPU readback.

[Relative covariance](../../src/metrics/covariance_metrics.py) uses linear
luminance `Y_s(p,t)`, its across-run mean `mu`, and
`r_s=(Y_s-mu)/(mu+1e-4)`. Pair covariance is
`sum_s r_s(a)*r_s(b)/(N-1)`: signed and dimensionless, neither Pearson
correlation nor reference error. Spatial covariance averages a cropped radius-8
disk including the center variance term. Temporal covariance uses the same pixel
at lag 3 by default, giving 13 pairs from 16 frames. Compute across independent
runs before averaging pair/frame maps; consecutive temporal-on frames are not
independent trials. Four seeds can still give noisy pixelwise estimates, and
timing remains single-seed.

## Capture and runtime maintenance

| Module under `scripts/falcor/` | Responsibility |
| --- | --- |
| `capture_lifecycle.py` | Atomic state, numbered attempts, failure receipts and deployment-shader guard |
| `spatial_inputs.py` | Reference bindings, capture artifacts and runtime preparation/verification |
| `fixed_view_suite.py` / `spatial_campaign.py` | Four-method suite / retained two-method and temporal-contrast interfaces |
| `spatial_capture.py` / `spatial_measure.py` | Quality export / timing with optional HDR and explicit drain |
| `runtime_common.py` | Shared path, inventory and frozen-baseline checks |

Current runtime identities include shared implementation code. CGNS verifies
retained generated host sources; recorded link hashes describe the build without
requiring the original compiler libraries at deployment.

`verify_prepared()` checks the current implementation. Historical
`verify_snapshot()` requires an externally trusted receipt hash and the frozen
baseline; it checks recorded bytes and cannot authorize rendering with current
code. Never refresh a historical receipt to bypass a mismatch.

The retired single-seed scripts `spatial_reuse_audit.py`,
`spatial_three_methods.py` and `falcor_three_methods.py` are backed up in
`build/pt-maintenance-20261116/source-before.zip`, with `retired-sources.json`
beside it. Compatibility wrappers, glTF patches, mathematical oracles and
selector diagnostics remain. Use the [test groups](../../tests/README.md) for
CPU/source/native checks; their results do not substitute for a new GPU run.
