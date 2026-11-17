# Data index and retained capabilities

| Path | Contents | Use |
| --- | --- | --- |
| `runs/pt-6-views-spatial-compare/analysis-report.md` | Findings, metrics, protocol and limits | Primary report evidence |
| `.../statistics/summary.csv` | Per-view/method SMAPE, covariance and GPU frame time | Summary charts/tables |
| `.../statistics/quality-seeds.csv` | Per-seed quality statistics | Four-seed variability |
| `.../statistics/quality-frames.csv` | Per-frame quality scores | Captured-window plots |
| `.../statistics/stage-summary.csv` | High-level GPU stages and nested CGNS events | Timing analysis |
| `.../statistics/timing-frames.csv`, `timing-events.csv` | Aligned frames and native profiler events | Timing details; do not double-count nested events |
| `.../data/<view>/arrays.npz` | Unclipped SMAPE/difference/covariance maps | Restyle maps and change display limits |
| `.../data/<view>/presentation-strips.npz` | Retained RGB strips/regions | Visual comparisons; inspect keys before plotting |
| `.../data/<view>/presentation-strip-metrics.json` | Frozen local metrics and coordinates | Local failure/gain examples |
| `.../images/<view>/` | Reference, ordinary temporal on/off, PDF, CGNS; seed0/frame48 | Display/ROI illustration; not linear HDR |
| `.../figures/`, `index.html` | Full PNG/PDF gallery | Figures for report |
| `.../records.zip` | Original manifests, audits, reference/runtime evidence, retirement inventories | Provenance; some paths are historical |
| `writing/final/data/` | Current media selection and derivation receipts | Trace displayed plots and media; selected regenerated receipts may live in `writing/final/build/media-receipts/` |
| `scenes/trajectories/pt-walkthroughs/` | Approved camera routes | Explain demo motion |

The fixed views are Bistro Interior, Bistro Exterior, Classroom, Emerald Square, Veach Ajar and Zero Day Measure Seven. The shared temporal-on comparison is ordinary spatial reuse, PDF Similarity and CGNS. Ordinary temporal-off is a retained ablation. Internal CSV method `temporal-on` denotes ordinary reuse, `pdf` denotes PDF Similarity.

SMAPE uses luminance and no factor of two: 100|Y−Yref|/(|Y|+|Yref|+1e−4). Each frame is scored before averaging. Quality uses four seeds ×16 correlated frames; seed means are the independent units. Reported SD is SD of four seed means. Relative reduction is 100(Eordinary−Emethod)/Eordinary. Difference maps instead show Emethod−Eordinary in percentage points; blue is lower error. Do not confuse the two signs/units.

Covariance is signed relative covariance across seed realizations, not Pearson correlation or bias. Temporal lag is3; spatial disk radius8 includes the center. Four seeds make pixelwise covariance estimates noisy. Temporal RGB strips also contain static texture; they are not covariance heatmaps. Local-strip trends need not match scene-wide means.

GPU timing uses an export-free replay, not MP4 playback speed. Emerald timing is excluded; Veach uses the retained recheck. Single timing replays do not provide independent-run timing uncertainty. Retrace includes path-shift/reconnection work and is not isolated visibility-test time. The method comparisons use matching sampling settings, not equal-time quality.

## Available and unavailable operations

Supported: redraw retained maps; restyle axes/colors/clipping; compute summaries from retained CSVs; inspect frozen ROI metrics and display crops; edit/recompose videos and plot preserved GPU timing. Use `python runs/pt-6-views-spatial-compare/tools/replot.py --output derived-report-figures` for the archive replotter (it writes derived outputs; read its README first).

Unavailable from this bundle: arbitrary new linear-HDR error/covariance estimators, new epsilon/transport/camera quality evaluations, independent reference uncertainty, original path reservoirs, rerendering scenes, and video quality metrics against a trajectory reference. Full method HDR was retired, reference EXRs are not bundled, and no moving reference video exists. H.264 presentation videos have lossy compression and baked display/watermark transforms.
