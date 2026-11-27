# RTXDI direct-lighting baseline

The fixed-setting ablation compares initial sampling, temporal reuse, spatial reuse and combined reuse. It uses 36 runs across Cornell Box, Arcade and Bistro with one seed, 1920×1080 and matched sampling settings. The static endpoint table reports scene-linear RGB RMAE at frame 128 and mean GPU time over frames 33–128. [Experiment settings](../../../experiments/configs/di-reuse.json)

| Scene | Initial RMAE / ms | Temporal RMAE / ms | Spatial RMAE / ms | Combined RMAE / ms |
| --- | ---: | ---: | ---: | ---: |
| Arcade | 0.4296 / 8.01 | 0.1231 / 9.55 | 0.2878 / 11.95 | 0.2246 / 13.32 |
| Bistro | 0.3015 / 15.08 | 0.1774 / 18.36 | 0.2779 / 20.15 | 0.1573 / 28.46 |
| Cornell Box | 0.1608 / 6.40 | 0.0400 / 6.62 | 0.0895 / 7.80 | 0.0674 / 8.33 |

Temporal reuse has the lowest endpoint RMAE in Arcade and Cornell Box, 71.4% and 75.1% below initial sampling. Combined reuse gives the lowest RMAE in Bistro, 47.8% below initial sampling. Bistro's NRMSE favors spatial reuse, and the highest-error 1% of pixels accounts for 99.98% of squared error with combined reuse. At the history reset, temporal-only RMAE rises by 1.90×–4.02× relative to the preceding capture.

The one-seed design supports descriptive comparisons at matched settings. These scores predate the geometric-normal correction in the reference renderer.

[Error trajectories](error-trajectories.png) · [Endpoint images](representative-images.png) · [Quality metrics](metrics.csv) · [Phase timings](timings.csv) · [Regional metrics](metrics-quadrants.csv) · [Tail diagnostics](tail-diagnostics.csv)
