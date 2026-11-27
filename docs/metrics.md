# Metrics and saved-result analysis

Use scene-linear Rec.709 RGB with luminance `Y = .2126R + .7152G + .0722B`. Compute quality metrics before exposure, denoising or tone mapping. Match the reference's camera and transport target.

| Metric | Definition |
| --- | --- |
| SMAPE (%) | `100 * abs(Y - Yref) / (abs(Y) + abs(Yref) + 1e-4)` per pixel, with no factor of two. |
| TRMAE | `L1(deltaRGB - deltaReference) / (L1(deltaReference) + .01) / 3`, using adjacent frames and matching linear RGB references. |
| Temporal relative covariance | Sample covariance across runs between the same screen pixel at frames `t` and `t+3`. |
| Spatial relative covariance | Same-frame covariance averaged over the clipped radius-eight disk around each pixel, including its center. |

Covariance uses `r_s = (Y_s - mean_s(Y)) / (mean_s(Y) + 1e-4)` across aligned independent runs. Average valid pixels and frames after computing per-pixel error or covariance. Values are signed and dimensionless. Warmed-up consecutive frames within a run share history. Temporal pairs must stay within a continuous segment. GPU comparisons use the documented profiler boundary. Nested child events already contribute to parent times. [Metric code](../src/metrics) · [Sequence analysis](../scripts/analysis/sequence_metrics.py)

The whole-image region includes background. For region analysis, shared primary geometry ranks valid surface pixels by geometric-neighbor acceptance. The hardest 10% under the default radius-30 classification form the hard mask. Use the same masks for all methods. Report SMAPE differences in percentage points and relative changes against a named baseline. [Region classification](../src/metrics/pixel_regions.py)

## Inspect saved runs

Install the analysis package in a Python 3.11+ environment. Pass an RTXDI or Falcor saved run and a new output directory.

~~~powershell
python -m pip install -e ".[exr]"
python -B scripts/analyze_run.py --run path/to/saved-run --output path/to/new-inspection
~~~

Add `--reference-image path/to/reference.exr` for per-capture SMAPE against a supplied linear HDR reference. Image validation checks metadata and bytes. Reference transport and convergence require their own evidence. Sequence covariance requires independent seeds with matching recorded capture controls. Older smoke captures may lack that metadata. [Saved-run reader](../src/analysis/saved_runs.py) · [Analysis entry points](../scripts/analysis/README.md)

## Fixed-view PT archive

With the separately supplied six-view archive and references in place, run `python -B scripts/analysis/pt_stage_archive.py --inspect` for coverage and `python -B scripts/analysis/pt_stage_archive.py` to verify the inventory. The archive's replot tool uses retained tables, maps and strip samples. New pixel-level metrics require the original HDR frames. The [benchmark guide](reproductions/pt-6-views-spatial-compare.md) describes capture and timing.
