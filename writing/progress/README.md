# PDF Similarity progress report

## Experiments

Run the [controlled RTXDI PDF Similarity suite](../../experiments/suites/pdf-similarity.md) with the [campaign configuration](../../experiments/configs/pdf-controlled.json). Compare PDF off and on with the same three seeds across four static views, three camera paths, and one lighting change. Include the Bistro spatial-only ablation and the two Bistro neighbor-count sweeps for the equal-time comparison.

## Build

Use the resulting comparison CSVs, selected display PNGs, and paired 96-frame PNG sequences for the four dynamic conditions. The [source index](data/sources.json) specifies the inputs and hashes. For a new campaign, update the input paths and hashes and revise the tables and figures in the [Marp source](source/progress.md).

From the repository root, run with Python 3.11+ and Node.js installed. The script uses Marp CLI 4.5.1 and generates `progress.html` for the slides and `comparison.html` for the experiment viewer.

```powershell
.\writing\progress\tools\build.ps1
```

The default build uses existing comparison videos. Add `-Media` to encode them with FFmpeg after supplying the paired frames expected by the [media builder](tools/build_media.py). Poppler is required to regenerate the [paper figure](data/paper-figure.json).
