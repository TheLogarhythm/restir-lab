# Falcor ReSTIR PT spatial comparison

`restir-pt-spatial-comparison.json` is the shared configuration for ordinary spatial reuse and the independent CGNS adaptation. Its defaults match the existing comparison: 1920×1080, 40 warmup frames, 8 single-frame captures, temporal reuse on, one spatial neighbor, radius 30, and a maximum temporal history of 20.

The CGNS shader settings are `candidate_count`, `position_scale`, `normal_exponent`, `early_stop_score`, and `early_stop_count`. They generate compile-time constants in a private, fingerprinted shader runtime. A different parameter set or shader source creates a different runtime; existing runtimes are never overwritten.

The supported comparison uses point reservoirs, unpaired spatial reuse, M=1, TinyUniform and one sample per frame. The loader rejects settings that this implementation does not support. The bounce limits and other transport settings must match the frozen reference; the full comparison also requires the reference and output resolutions to match.

From the repository root, run a new campaign with an unused output directory:

```powershell
& 'build/falcor/verify-env/Scripts/python.exe' -B -m scripts.falcor.spatial_campaign `
  --experiment-config experiments/configs/falcor-pt-spatial-comparison/restir-pt-spatial-comparison.json `
  --output runs/my-spatial-comparison
```

The default renders all six views with temporal reuse enabled for both ordinary spatial reuse and CGNS. Each method receives the same warmup, static clock, camera, graph settings and frame seeds. The output contains per-frame and per-view SMAPE, CSV files and labeled previews. These correlated frames are descriptive samples, not independent repeats.

For a controlled ordinary-spatial temporal on/off contrast, select exactly one view:

```powershell
& 'build/falcor/verify-env/Scripts/python.exe' -B -m scripts.falcor.spatial_campaign `
  --output runs/my-classroom-temporal-contrast `
  --temporal-contrast --view classroom/view-a
```

This option renders only ordinary spatial reuse for the selected view, once with temporal reuse on and once off. It does not prepare or verify a CGNS runtime. A contrast requires `--view SCENE/VIEW`; a view selector cannot narrow the normal six-view comparison. The two jobs share resolution, transport, warmup, capture frames, path seeds, static clock, camera, scene and baseline runtime. Temporal history and reuse seeds follow the recorded temporal mode.

The legacy `scripts.falcor.cgns_temporal_campaign` and `scripts.falcor.cgns_paper_campaign` commands remain available for six-view temporal-on and temporal-off ordinary/CGNS comparisons. All three commands use the shared campaign and capture implementation. Existing records remain usable for offline analysis; changed implementation hashes prevent silently treating old captures as new captures.

The config hash, normalized settings, source identity and runtime receipt are recorded in campaign and job manifests. Completed jobs and report files are revalidated on resume. Failed jobs and interrupted analyses remain intact; `--retry-failed` creates a new numbered attempt. Campaign status records capture or analysis failures, and validated completed jobs are reused without relaunching.

`scene-inputs-v2.json` selects six view presets from `experiments/views/falcor-pt-spatial-comparison/`. Each preset selects a reusable scene profile and a camera; scene profiles and their resource inventories live under `experiments/scenes/falcor-pt-spatial-comparison/`. Method, temporal-mode and render-budget settings belong to `restir-pt-spatial-comparison.json`. The old `scene-inputs.json` and monolithic `*-reference.json` files remain historical compatibility inputs. The independent reference catalog is
`experiments/references/falcor-pt-spatial-comparison-16384.json`. Capture requires
scene inputs and catalog metadata; EXRs are validated when analysis starts.
Prepare the Bistro sky with `python -m scripts.falcor.prepare_bistro_sky_asset`
and obtain other assets and reference images as described in the reference guide.
The optional historical check `python -m scripts.falcor.verify_scene_inputs_migration`
uses preserved old records; starting a new render does not require them.

The legacy `emerald-square-reference.json` uses the converted scene script
`scenes/configs/falcor/emerald-square-converted-reference.pyscene`. This is a
path-only rename of the former converted scout, with unchanged scene-script
content; the earlier ORCA scene file `emerald-square-reference.pyscene` is a
different scene and remains unused by the current comparison. Historical
Emerald script and configuration snapshots are stored under
`runs/falcor-pt-spatial-comparison/provenance/relocations/`.

See [the six-view preparation guide](PREPARATION.md) for exact source versions,
commands for both Bistro variants, conversion recipes, runtime/plugin builds,
no-render checks and reference capture entry points.
