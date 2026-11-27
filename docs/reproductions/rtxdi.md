# RTXDI spatial-reuse experiments

Build the pinned RTXDI backend on Windows first. The Cornell smoke commands below exercise project adaptations with matched same-executable controls. [Setup](../setup.md#rtxdi) · [RTXDI runners](../../scripts/run/README.md)

## PDF Similarity

The direct-lighting implementation fits a vMF lobe to reprojected direction statistics and scales the donor reservoir's effective count. Use unfused spatial or combined reuse, initial visibility and ray-traced spatial correction. The supported configuration disables checkerboard.

~~~powershell
python -B scripts/run/build_rtxdi_pdf.py
python -B scripts/run/rtxdi_reuse.py --scene cornell-box --mode combined --pdf-similarity
python -B scripts/run/rtxdi_reuse.py --scene cornell-box --mode combined --pdf-build
~~~

The second render keeps the PDF executable and disables the method. The controlled three-seed suite used sparse references. Five Cornell/Arcade states passed the original precision policy and ten Bistro states used a fixed sample budget with unevaluated reference precision. Published tables retain the measured outcomes and their limits. Rebuilding videos and recomputing pixel metrics require matching source images. [Suite](../../experiments/suites/pdf-similarity.md) · [Results](../../results/summaries/pdf-similarity/README.md) · [Artifact availability](../../results/summaries/pdf-similarity/artifact-availability.json)

## CGNS

The DI adapter samples compatible neighbors by position and shading-normal agreement before native rejection. Its defaults are 32 proposals, four retained neighbors and radius 32 pixels. Merge and normalization use the same accepted list. Selection time is part of total GPU time.

~~~powershell
python -B scripts/run/build_rtxdi_cgns.py
python -B scripts/run/rtxdi_reuse.py --scene cornell-box --mode combined --cgns --diagnostics
python -B scripts/run/rtxdi_reuse.py --scene cornell-box --mode combined --cgns-build
~~~

The final command is the same-executable off control. [DI adapter](../../scripts/run/rtxdi_cgns.py) · [Falcor PT adaptation](falcor-pt.md#cgns)

## Fixed-view DI, GI and PT comparison

The RTXDI batch CLI supports static fixed-camera acquisition. Use `plan` to inspect the schedule. `prepare` binds settings, build conformance, camera verification, assets and references. Use a new output directory and supply the matching preview and conformance records. The historical six-method configuration reuses existing DI captures. The DI example shows a configuration that requests fresh rendering. [Six-method config](../../experiments/configs/cgns-di-gi-pt-static.json) · [DI example](../../experiments/configs/di-comparison-static.json)

~~~powershell
$spec = 'experiments/configs/di-comparison-static.json'
python -B scripts/run/rtxdi_comparison.py plan --config $spec
python -B scripts/run/rtxdi_comparison.py prepare --config $spec --root runs/new-batch --preview-check PREVIEWS.json --conformance CONFORMANCE.json
python -B scripts/run/rtxdi_comparison.py start --root runs/new-batch
python -B scripts/run/rtxdi_comparison.py status --root runs/new-batch
~~~

Use `analyze`, `report` and `verify` to process saved batches without rendering. Use new output directories for derived files. See `rtxdi_comparison.py --help` for the inputs to each action. Historical verification checks the original evidence path and SHA-256. Keep the [frozen evidence contract](cgns-di-gi-pt.md) intact.

The historical five-view run used one method seed and fixed budgets. In the retained reanalysis, whole-image SMAPE increased for DI in five views, decreased for GI in five, and decreased for PT in three of five. These observations came from captures before the latest transport fixes. The 8,192-path GI/PT references and the 4,096-path continuation checkpoint do not establish reference convergence. Equal-time quality and temporal stability were outside this comparison. [Results index](../../results/index.csv) · [Metrics](../metrics.md)
