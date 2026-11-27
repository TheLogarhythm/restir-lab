# Falcor PT spatial reuse

We compare ordinary spatial reuse, PDF Similarity and cached CGNS at 1920×1080 and 1 spp, with temporal reuse enabled. Each view uses four matched seeds, quality frames 41–56 after warm-up, and a 16,384-spp reference. GPU times average 64 measured frames from a separate run at seed 0 on an RTX 4060 Laptop GPU. [Benchmark protocol](../../../docs/reproductions/pt-6-views-spatial-compare.md)

| View | Ordinary SMAPE (%) | PDF SMAPE (%) | CGNS SMAPE (%) | Ordinary GPU (ms) | PDF GPU (ms) | CGNS GPU (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bistro Interior | 28.04 | 28.04 | 25.30 | 37.28 | 41.33 | 38.85 |
| Bistro Exterior | 16.67 | 16.32 | 15.12 | 40.50 | 44.38 | 42.90 |
| Classroom | 17.33 | 17.19 | 16.03 | 32.13 | 40.78 | 33.85 |
| Emerald Square | 25.55 | 26.99 | 19.74 | — | — | — |
| Veach Ajar | 16.75 | 16.78 | 15.89 | 22.53 | 27.22 | 23.42 |
| Zero Day Measure Seven | 19.09 | 18.74 | 18.34 | 69.71 | 75.40 | 72.55 |

CGNS reduces mean SMAPE by **3.9–22.7%**, with lower SMAPE than ordinary reuse in all 24 paired view–seed comparisons. Its GPU overhead is 4.0–5.9% in the five eligible timing views. Across the six views, CGNS lowers temporal covariance by 8.8–40.4% and raises spatial covariance by 1.7–24.9%.

PDF Similarity is nearly tied with ordinary reuse in Bistro Interior. It reduces mean SMAPE by 2.1% in Bistro Exterior and increases it by 5.6% in Emerald Square. Emerald Square's GPU timings were excluded after inconsistent repeated measurements. The GPU table compares fixed sampling settings and one timing seed. Equal-time PT quality and between-run timing variability remain unmeasured.

[Aggregate metrics and temporal-off control](summary.csv) · [Per-seed quality](quality-seeds.csv) · [Per-frame quality](quality-frames.csv) · [GPU stage timings](stage-summary.csv)

[Emerald Square comparison](../../figures/emerald-square-comparison.png) · [Bistro Interior comparison](../../figures/bistro-interior-comparison.png)

The [early single-seed results](historical-single-seed.csv) describe a separate experiment. That experiment scored quality over frames 41–48 and GPU time over frames 41–47.
