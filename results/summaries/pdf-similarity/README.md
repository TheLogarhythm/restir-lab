# RTXDI PDF Similarity

PDF off and on were compared at matched 1920×1080 settings across three paired seeds. Static quality is measured at frame 128, with GPU time averaged over frames 41–128. Five Cornell and Arcade reference states passed the precision criterion. The ten Bistro references use a single stream of 262,144 local samples with unevaluated precision. [Experiment suite](../../../experiments/suites/pdf-similarity.md)

| Static view | Full-image SMAPE (%), off → on | Mean GPU time (ms), off → on |
| --- | ---: | ---: |
| Cornell Box | 7.98 → 6.89 | 8.90 → 9.60 |
| Arcade | 17.04 → 14.99 | 13.78 → 15.65 |
| Bistro Interior | 28.46 → 27.94 | 29.44 → 32.58 |
| Bistro Exterior | 42.24 → 34.48 | 27.62 → 32.36 |

PDF Similarity reduces static full-image SMAPE in all four views at higher GPU cost. In Bistro Interior, full-image RMAE and NRMSE increase despite the small SMAPE reduction. With spatial reuse alone in that view, full-image SMAPE rises from 72.17% to 73.08%, and both evaluated regions worsen across all three spatial metrics and all three seeds.

During motion and lighting changes, some full-image gains reverse within the selected regions. Temporal measurements cover only adjacent pairs 31→32, 47→48 and 95→96. Arcade's moving pair shows mixed TRMAE changes across seeds.

At the shared-time interpolation points, PDF reduces mean SMAPE by 0.92 percentage points at 33.49 ms in Bistro Interior and 8.81 points at 31.06 ms in Bistro Exterior. These estimates interpolate measured two-, four- and eight-neighbor settings. The measured two-neighbor PDF-off point in Bistro Interior has lower mean error and GPU time than every measured PDF-on point, limiting the equal-time conclusion.

[Aggregate results](data/main/summary.csv) · [Paired-seed results](data/main/paired-seed-differences.csv) · [Spatial-only ablation](data/bistro-interior-static-spatial-only/summary.csv) · [Measured budget points](data/equal-time-comparison/measured-points.csv) · [Equal-time estimates](data/equal-time-comparison/paired-differences.csv)
