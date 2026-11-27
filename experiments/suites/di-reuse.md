# RTXDI direct-lighting reuse controls

The suite compares initial sampling, temporal reuse, spatial reuse and combined reuse in Cornell Box, Arcade and Bistro on RTXDI v3.1.0. It uses 1920×1080, seed 1 and 128 frames. All modes share 24 local, 8 environment and 1 analytic sun candidate, with no BRDF candidates. Spatial reuse uses four neighbors at radius 32 pixels and temporal history is capped at 20. Denoising, antialiasing, accumulation, tone mapping and visibility shortcuts are disabled. Ray-traced bias correction and final visibility are enabled. [Configuration](../configs/di-reuse.json) · [Scene profiles](../../scenes/configs/rtxdi/README.md)

| Scenario | Camera and history | Saved frames |
| --- | --- | --- |
| Static | Fixed camera, empty initial history | 1, 8, 32, 128 |
| Motion | Hold 1–32, linear translation 33–96, hold 97–128 | 1, 32, 33, 64, 96, 97, 128 |
| Reset | Fixed camera, clear reservoirs and previous depth before frame 65 | 1, 32, 64, 65, 72, 96, 128 |

The sample index is `seed * 1048576 + logical_frame - 1`. Reset clears history while leaving the RNG schedule in place. The runs use fixed scene time and camera settings.

## Run

Use PowerShell at the repository root after preparing the RTXDI build and scene assets. Use an unused output name. [Setup](../../docs/setup.md#rtxdi)

~~~powershell
python -m pip install -r scripts/run/requirements.txt
python -B scripts/run/build_rtxdi_experiments.py
python -B scripts/run/rtxdi_reuse.py --scene all --scenario all --check
python -B scripts/run/rtxdi_reuse.py --scene all --scenario all --diagnostics --output-name di
~~~

`--scene all` selects the three baseline scenes. Use `--mode combined` or `--scenario static` to narrow a run, and `--resolution 640 360` for a smoke test. Headless is the default. Use `--windowed` for inspection and compare timings in the same window mode. Each run records resolved settings, hardware, HDR `.pfm.gz` captures, fixed-exposure PNG previews and per-frame GPU timings. Timings exclude export, UI and present.

## References and analysis

Build the conventional reference variant, validate it against the baseline, then render and analyze. A reference matches the baseline's camera, resolution, lighting and asset hashes. Identical physical targets share a reference. The independent streams use the same fixed camera and sample the lighting with upstream BSDF and visibility in FP32. [Reference code](../../scripts/run/rtxdi_reference.py)

~~~powershell
python -B scripts/run/build_rtxdi_experiments.py --reference
python -B scripts/run/rtxdi_reference.py --baseline runs/di --output-name di-reference --check
python -B scripts/run/rtxdi_reference.py --baseline runs/di --output-name di-reference
python -B scripts/analysis/di_reuse.py --baseline runs/di --references runs/di-reference
~~~

The default streams are seeds 1001 and 2001, with 16 samples per batch per light class per stream. Checkpoints are 256, 512, 1024, 2048 and 4096 samples per class per stream per pixel. Average the two streams for the reference, with a default cap of 8192 samples per class across both. The published references used 2,048 samples per class per stream for Cornell Box, 8,192 for Arcade and 262,144 for Bistro. The acceptance ratio was 0.1 for Cornell Box and Arcade and 0.3 for Bistro. [Published settings and results](../../results/summaries/di-baseline/README.md)

### Convergence and resume

Let `R_n` be the mean of the two reference streams at checkpoint `n`, and `E_n` the lowest baseline full-image RGB RMAE against that mean for the same target. A checkpoint passes when both half-stream disagreement and the change from `R_(n/2)` are at most `alpha * E_n`. Require two successive passing checkpoints. The default `alpha` is 0.1. Record overrides from `--noise-ratio` or `--scene-noise-ratio`. Targets that reach their cap without passing remain unconverged. This test measures empirical stability and agreement.

~~~powershell
python -B scripts/run/rtxdi_reference.py --baseline runs/di --resume runs/di-reference
python -B scripts/run/rtxdi_reference.py --baseline runs/di --resume runs/di-reference --reassess-only
~~~

Resume with the original seeds, sample allocation and batch size. A higher cap requires approval and an extension of the original doubling checkpoints. The runner verifies target, build, image hashes and sampling lineage before reusing completed work. `--reassess-only` checks saved reference pairs without rendering.

### Analysis outputs

Analysis writes new metrics and timing CSVs, endpoint images, error trajectories and a summary. It computes RMAE and NRMSE on scene-linear RGB, checks capture and reference coverage, and marks insufficient reference precision as provisional. GPU cost uses frames 33–128 for static views and the full sequence for other scenarios. These are matched-setting measurements with one independent seed. [Analysis commands](../../scripts/analysis/README.md) · [Baseline data](../../results/summaries/di-baseline/README.md)
