# Six-view ReSTIR PT comparison

The suite uses Bistro Interior, Bistro Exterior, Classroom, Emerald Square, Veach Ajar and Zero Day Measure Seven. All three methods use the same fixed cameras, 1920×1080, 1 spp, a ten-bounce limit, one unpaired spatial neighbor, one round, radius 30 and a lighting-history limit of 20. The three-way comparison enables temporal reuse and uses matched 16,384-spp Falcor references. A separate ordinary temporal-off control isolates the effect of temporal reuse. Image accumulation, denoising and diagnostics are disabled during collection. [Suite](../../experiments/configs/pt-6-views-spatial-compare.json) · [Method settings](../../experiments/configs/falcor-pt-spatial-comparison/restir-pt-spatial-comparison.json) · [Falcor methods](falcor-pt.md)

| Collection | Seed offsets | Warm-up | Scored frames |
| --- | --- | --- | --- |
| Quality | 0, 100000, 200000, 300000 | 1–40 | 41–56, scene-linear FP32 EXR |
| GPU timing | 0 | 1–40 | 41–104, with an extra profiler drain frame and no image export |

Each job starts a fresh process and history. For frame `t`, the path seed is `offset+t-1` and the reuse seed is `offset+t-2` after frame one. Frame one uses reuse seed zero and skips temporal reuse. Whole-view SMAPE is calculated per frame, then averaged within seed and across seeds. See [metric definitions](../metrics.md).

## Run the suite

Prepare the pinned code, runtime dependencies, camera profiles, scene assets and reference bindings before capture. Use Python 3.11+ with the [Falcor requirements](../../scripts/falcor/requirements.txt). Keep `FALCOR_DEVMODE` unset and avoid competing GPU work during timing. [Scene and runtime preparation](../../experiments/configs/falcor-pt-spatial-comparison/PREPARATION.md)

From PowerShell at the repository root, use a fresh output directory. `--plan` prints the schedule.

~~~powershell
$batch = Join-Path 'runs/pt-fixed-view-batches' (Get-Date -Format 'yyyyMMdd-HHmmss')

python -B -m scripts.falcor.fixed_view_suite --check
if ($LASTEXITCODE -ne 0) { throw 'Input check failed' }
python -B -m scripts.falcor.fixed_view_suite --prepare --output $batch
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed' }
python -B -m scripts.falcor.fixed_view_suite --run --output $batch
~~~

Retry failures with `--run --retry-failed --output $batch` on the same prepared inputs. Use a new batch after changing code, assets or configuration. The batch manifest records resolved settings, reference hashes, runtime receipts and all attempts.

## Timing and retained evidence

Whole-frame GPU time comes from `/onFrameRender/gpu_time`. CGNS attribute and selection timings are nested inside the spatial pass. The Emerald Square timings were excluded after instability across runs, while its quality measurements were retained. Veach Ajar uses the selected recheck. One timing run per eligible view and method supports a fixed-settings cost comparison. Equal-time PT quality and between-run timing uncertainty remain unmeasured.

The optional statistics archive retains per-frame and per-seed CSVs, unclipped maps, selected display PNGs, timings and provenance. The original method HDR frames were retired. A checkout provides the source, configurations and selected result figures. Archive inspection and replotting require the separately supplied statistics archive. New pixel-level metrics require the original linear HDR inputs or new renders. [Results](../../results/summaries/falcor-pt-spatial-reuse/README.md) · [Archive inspection](../metrics.md#fixed-view-pt-archive)
