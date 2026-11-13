# Experimental Falcor ReSTIR PT with CGNS

This is a **project-authored, experimental adaptation**, not the authors' Falcor renderer or a formal reproduction. It uses [Compatibility-Guided Neighbor Selection](https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/) by Junkins et al. (2026) and the [author code at `f28d553`](https://github.com/orion-junkins/ReSTIR-CGNS/tree/f28d553f3b2552b1be829feffea6d1abb1945e1d) as references. Falcor 9.0 is pinned separately in [integration.json](../../renderers/falcor/integration.json). The earlier [RTXDI adaptation](cgns.md) is a separate implementation.

## Selector and differences

The [point selector](../../scripts/falcor/cgns_point_selector.slang) uses up to K=32 proposals in a pixel-radius disk and selects up to four valid neighbors by A-ES weighted sampling without replacement. For center world position `x`, neighbor `y`, center distance `d` from the camera, and shading normals `nx`, `ny`, its weight is:

`exp(-distance(x,y) / (d * sqrt(0.05 / pi))) * max(dot(nx,ny),0)^8`.

After four candidates score at least 0.5 the scan stops early. Out-of-bounds, background, center, duplicate, zero-weight and nonfinite candidates are skipped; unused slots contain `(-1,-1)`. The selector uses a dedicated random stream and Falcor's native RG8Snorm disk table; the author code uses an R2/concentric disk construction. The author code's epsilon handling, duplicate/center and empty-slot behavior differ. This is an adaptation, not bitwise author-code parity.

The [overlay](../../scripts/falcor/cgns_shader_overlay.py) modifies a private runtime copy, leaving the pinned upstream source and reference runtime unchanged. It changes candidate coordinates in the point spatial path and retains native geometry rejection, path shifts, reservoir merging and pairwise MIS. The selected list is **recomputed** from the same per-pixel inputs in workload generation, compact retracing and spatial resampling; it is not stored in a shared selection buffer. Cross-stage equality must be checked for each supported configuration; it is not guaranteed merely by source similarity. Recomputing candidate geometry across passes can add substantial overhead.

## Supported experiment scope

The smoke graphs use 1 spp per frame, point reservoirs, four spatial neighbors, radius 32, one spatial iteration, unpaired neighbors, compact retracing, no temporal resampling and no depth-of-field reconnection. The original smoke runner is Classroom-only; the separate six-view driver below targets the frozen reference views. Camera aperture is zero and VBuffer depth of field is off. The overlay itself does not enforce all these settings; **callers must enforce them**, and the [smoke runner](../../scripts/falcor/cgns_pt_smoke.py) checks the resolved graph. Paired/reciprocal patterns, area reservoirs, depth of field, other neighbor counts and other scheduling modes are not validated for this four-neighbor overlay. Do not use them with it.

Both baseline and CGNS use Falcor's `sampleGenerator=0` (TinyUniform). The native PT code saves a 32-bit generator state for path replay; its `getCurrentSeed` does not retain the state of the 128-bit Uniform generator. Changing constructors alone does not make 128-bit replay valid. TinyUniform has limited statistical quality; matching the generator between both methods does not establish independent streams. The conventional reference uses a different generator and must not be treated as seed-paired with these ReSTIR PT outputs.

## Separate one-neighbor Fast configuration

A separate [single-neighbor selector](../../scripts/falcor/cgns_single_selector.slang) uses K=32 candidate proposals, M=1, A-Chao weighted selection and early stopping after the first candidate whose compatibility is at least 0.5. Its [A-Chao arithmetic](../../scripts/falcor/cgns_single_wrs.h) is shared by the CPU numerical test and shader overlay. The same geometry scoring and candidate exclusions described above apply. The intended Fast setting is a 30-pixel radius and one spatial round. [Single-neighbor overlay](../../scripts/falcor/cgns_single_overlay.py) and [runtime preparation](../../scripts/falcor/cgns_single_runtime.py) have their own marker, hashes and receipts. They create new private runtimes from the existing reference or glTF v3 base; they do not modify or replace the previously verified M=4 code, runtimes or receipts. The [diagnostic overlay](../../scripts/falcor/cgns_single_diagnostic.py) is separate and must only be used on a private copy without a production receipt. See the relevant campaign manifest for its GPU preflight and results; M=4 validation below does not automatically validate M=1.

The paper's Fast spatial-selection parameters are M=1, K=32 and R=30. Its results use temporal and spatial reuse with area reservoirs and reservoir splatting, a confidence cap of 20 and 40 warmup frames; its reported costs average ten trials of 2048-frame sequences. The local M=1 experiments include both temporal-on and temporal-off runs, use point reservoirs and unpaired single-frame outputs, and are an independent adaptation rather than a reproduction of the paper's full spatiotemporal setup. The local campaign's frame count, seeds, reference and metrics are specified by its own configuration and records, rather than assumed from the paper.

## Comparison experiment configuration

The shared [experiment configuration](../../experiments/configs/falcor-pt-spatial-comparison/restir-pt-spatial-comparison.json) sets the rendering budget, common graph options, temporal modes, and five CGNS shader parameters. Its defaults match the existing 1920×1080, 40-warmup, 8-capture, M=1/R=30, K=32 Fast-inspired comparison. Scene and camera configuration remains in the six frozen reference records. The loader rejects unsupported area reservoirs, paired or multiple neighbors, multiple samples per frame, and changes to transport settings tied to the frozen reference.

The two campaign entry points read the same JSON, selecting temporal-on or temporal-off respectively. Use a new output directory for each run; changing the config of an existing campaign is rejected. The config SHA-256, normalized settings and shader-variant receipt are recorded with the run. CGNS shader values are injected into a parameter-specific private runtime, identified by the parameters, shader and base-runtime fingerprints; the original runtimes and historical records are not overwritten. The first preparation of a new variant can take time.

New campaign identities and capture manifests use workspace-relative paths; job attempts are relative to the campaign directory, and analysis inputs are relative to their input JSON. Render scripts resolve output paths at runtime. Paths outside the workspace must remain at the same relative location when moving the project, and cross-volume paths cannot be represented. Resume also requires the recorded source code, assets, configuration and runtime fingerprints to match; changing the implementation does not make an older campaign resumable merely by relocating its paths.

New Bistro capture audits record texture paths relative to the workspace, after the renderer's original audit has passed the frozen-reference checks. A future schema-2 reference baseline may nevertheless point to an older audit that contains absolute paths from its original machine. After a workspace move, that older audit cannot always be checked from a workspace-relative baseline alone: retain a validated record of the original workspace root, or prepare a separately verified portable audit and provenance receipt before relying on it. Do not rewrite historical audit files or infer an unverified root from their filenames.

```powershell
& 'build/falcor/verify-env/Scripts/python.exe' -B -m scripts.falcor.cgns_temporal_campaign `
  --experiment-config experiments/configs/falcor-pt-spatial-comparison/restir-pt-spatial-comparison.json `
  --output runs/new-temporal-on-comparison

& 'build/falcor/verify-env/Scripts/python.exe' -B -m scripts.falcor.cgns_paper_campaign `
  --experiment-config experiments/configs/falcor-pt-spatial-comparison/restir-pt-spatial-comparison.json `
  --output runs/new-temporal-off-comparison
```

The config exposes shader compile-time parameters, not mutable per-frame shader uniforms. A different shader configuration requires its own verified runtime. These commands perform full comparisons; use the bounded scout tools for short validation, and do not interpret eight consecutive temporal frames as independent trials.

To prepare new M=1 runtimes, choose unused direct children of `build/` and run while Falcor is idle:

```powershell
& 'build/falcor/verify-env/Scripts/python.exe' -B -m scripts.falcor.cgns_single_runtime `
  --source reference --output build/falcor-cgns-single-reference-local

& 'build/falcor/verify-env/Scripts/python.exe' -B -m scripts.falcor.cgns_single_runtime `
  --source gltf-v3 --output build/falcor-cgns-single-gltf-local
```

The existing M=4 smoke runners below do not accept an M=1 runtime; use a runner that explicitly enforces M=1, radius and the supported point/unpaired/compact settings, and verifies the M=1 receipt. Single-neighbor GPU stage consistency, sampler behavior, transport matching, quality and performance must be validated independently for the chosen campaign.

## Running the bounded smoke test

With the existing validated reference runtime, prepare a private CGNS runtime and run from the repository root in PowerShell. The project Python environment must contain NumPy, OpenEXR and Pillow. Choose new output paths: the runner does not overwrite existing runs. Do not set `FALCOR_DEVMODE=1`.

```powershell
& 'build/falcor/verify-env/Scripts/python.exe' -B -m scripts.falcor.cgns_runtime `
  --source reference --output build/falcor-cgns-pt-local

& 'build/falcor/verify-env/Scripts/python.exe' -B -m scripts.falcor.cgns_pt_smoke `
  --method baseline --runtime build/falcor-reference-runtime/runtime `
  --output runs/falcor-pt-spatial-comparison/cgns-smoke-local/baseline

& 'build/falcor/verify-env/Scripts/python.exe' -B -m scripts.falcor.cgns_pt_smoke `
  --method cgns --runtime build/falcor-cgns-pt-local/runtime `
  --output runs/falcor-pt-spatial-comparison/cgns-smoke-local/cgns
```

[cgns_runtime.py](../../scripts/falcor/cgns_runtime.py) checks the source receipt and full non-transient inventory, requires a new destination under `build/`, takes the Falcor operation lock and checks that the renderer is idle. It creates a copied runtime plus `receipt.json`; the smoke runner verifies the receipt and runtime inventory before and after execution. A `gltf-v3` source is also supported for preparation, but this Classroom-only smoke runner requires `--source reference`; use the six-view driver below for the other views.

The runner defaults to 320×180 and four frames, enforces at most 640×360 and 16 frames, checks runtime fingerprints and scene inputs, and captures the final frame. `fixedSeed=frame-1`; the captured final frame is not an accumulated four-spp image. Each output records its actual command, resolved graph, camera, EXR, preview and manifest. This bounded smoke test is not a production or six-view comparison runner.

## Running the six frozen views

[cgns_pt_six_view_smoke.py](../../scripts/falcor/cgns_pt_six_view_smoke.py) accepts one frozen view per invocation. It loads the view, reusable scene profile and inventories from the checked-in [scene lock](../../experiments/configs/falcor-pt-spatial-comparison/scene-inputs-v2.json). Each smoke render checks scene state and camera, captures the final frame and uses the recorded display recipe for its preview. Historical extension and baseline records are needed only for the optional migration audit.

To inspect the six exact config paths from the checked baseline, run from the repository root:

```powershell
& 'build/falcor/verify-env/Scripts/python.exe' -B -c "from scripts.falcor.cgns_pt_six_view_smoke import frozen_views; [print(k, v['config_path']) for k, v in frozen_views().items()]"
```

The [Bistro interior view](../../experiments/views/falcor-pt-spatial-comparison/bistro-interior.json) selects a reusable glTF scene profile with its runtime, materials and lighting. The camera, including the interior near plane, belongs to the view. Both method capture and the adapted reference runner load the same scene with `SceneBuilderFlags.DontOptimizeMaterials`. The independent reference catalog binds its existing EXR to the qualified camera and transport settings. The other five views, including Bistro exterior, use the reference runtime family. See the [six-scene preparation guide](../../experiments/configs/falcor-pt-spatial-comparison/PREPARATION.md) for assets, plugins and checks.

For Emerald Square, the active converted scene script is
`scenes/configs/falcor/emerald-square-converted-reference.pyscene`. It was
renamed from `emerald-square-converted-scout.pyscene` without changing the scene
content. Historical Emerald script and config snapshots remain under
`runs/falcor-pt-spatial-comparison/provenance/relocations/`; the separate ORCA
`emerald-square-reference.pyscene` is not the scene used for this comparison.

| View | Baseline runtime | CGNS runtime source |
| --- | --- | --- |
| Bistro indoor | `build/falcor-gltf-composite-runtime-v3/runtime` | a private runtime prepared with `--source gltf-v3` |
| Bistro outdoor, Classroom, Emerald Square, Veach Ajar, Zero-day | `build/falcor-reference-runtime/runtime` | a private runtime prepared with `--source reference` |

For example, prepare a **new** Bistro CGNS runtime, then run its baseline and CGNS smoke tests in separate new output directories:

```powershell
& 'build/falcor/verify-env/Scripts/python.exe' -B -m scripts.falcor.cgns_runtime `
  --source gltf-v3 --output build/falcor-cgns-pt-gltf-local

& 'build/falcor/verify-env/Scripts/python.exe' -B -m scripts.falcor.cgns_pt_six_view_smoke `
  --method baseline --runtime build/falcor-gltf-composite-runtime-v3/runtime `
  --config experiments/views/falcor-pt-spatial-comparison/bistro-interior.json `
  --output runs/falcor-pt-spatial-comparison/cgns-six-smoke-local/bistro-indoor-baseline

& 'build/falcor/verify-env/Scripts/python.exe' -B -m scripts.falcor.cgns_pt_six_view_smoke `
  --method cgns --runtime build/falcor-cgns-pt-gltf-local/runtime `
  --config experiments/views/falcor-pt-spatial-comparison/bistro-interior.json `
  --output runs/falcor-pt-spatial-comparison/cgns-six-smoke-local/bistro-indoor-cgns
```

For another view, pass its exact printed `--config`, use the reference-family runtime from the table, and select a new `--output`. The default is 320×180, four frames; the maximum is 640×360, 16 frames. Runtime provenance, camera, lights, inputs and the resolved graph are checked per run; the adapted Bistro path additionally verifies material/texture audit and source inventory. These are smoke tests. All six views have completed an initial bounded functional pass as described below; they have not been completely validated. Check individual manifests before drawing conclusions.

## Validation status and limits

The diagnostic folders below contain historical records. Manifests, summaries, generated scripts and logs record the original runs. Any diagnostic EXR/PNG outputs omitted during migration cannot be used for image-level checks; their original manifest paths and hashes describe the runs at that time.

The initial Classroom `baseline-03` and `cgns-01` smoke attempts under `runs/falcor-pt-spatial-comparison/provenance/validation/cgns-pt-smoke-20261111/` both report successful 320×180 four-frame runs with matching requested graph settings. The earlier `baseline` attempt failed because it used the unsupported 128-bit replay sampler; the failed record is retained. These attempts establish that those variants produced captures, not that neighbor selection or estimator behavior is correct. Later changes to runners or validation must be assessed from their own manifests.

The final runner also completed the `baseline-final` and `cgns-final` Classroom runs at 160×90 for two frames, checking resolved settings, camera and runtime inventory. Both captured EXRs were finite. The runs demonstrate operation, not image-quality improvement.

The first bounded functional coverage across all six views has completed for both native spatial reuse and CGNS:

| View | Resolution and frames | Evidence |
| --- | --- | --- |
| Bistro indoor | 160×90, 2 frames | [baseline](../../runs/falcor-pt-spatial-comparison/provenance/validation/cgns-pt-six-view-smoke-20261111/bistro-baseline-01/manifest.json), [CGNS](../../runs/falcor-pt-spatial-comparison/provenance/validation/cgns-pt-six-view-smoke-20261111/bistro-cgns-01/manifest.json) |
| Bistro outdoor | 64×36, 1 frame | [baseline](../../runs/falcor-pt-spatial-comparison/provenance/validation/cgns-pt-six-view-smoke-20261111/bistro-exterior-baseline-01/manifest.json), [CGNS](../../runs/falcor-pt-spatial-comparison/provenance/validation/cgns-pt-six-view-smoke-20261111/bistro-exterior-cgns-01/manifest.json) |
| Classroom | 64×36, 1 frame | [baseline](../../runs/falcor-pt-spatial-comparison/provenance/validation/cgns-pt-six-view-smoke-20261111/classroom-baseline-01/manifest.json), [CGNS](../../runs/falcor-pt-spatial-comparison/provenance/validation/cgns-pt-six-view-smoke-20261111/classroom-cgns-01/manifest.json) |
| Emerald Square | 64×36, 1 frame | [baseline](../../runs/falcor-pt-spatial-comparison/provenance/validation/cgns-pt-six-view-smoke-20261111/emerald-square-baseline-01/manifest.json), [CGNS](../../runs/falcor-pt-spatial-comparison/provenance/validation/cgns-pt-six-view-smoke-20261111/emerald-square-cgns-01/manifest.json) |
| Veach Ajar | 64×36, 1 frame | [baseline](../../runs/falcor-pt-spatial-comparison/provenance/validation/cgns-pt-six-view-smoke-20261111/veach-ajar-baseline-01/manifest.json), [CGNS](../../runs/falcor-pt-spatial-comparison/provenance/validation/cgns-pt-six-view-smoke-20261111/veach-ajar-cgns-01/manifest.json) |
| Zero-day Measure Seven | 64×36, 1 frame | [baseline](../../runs/falcor-pt-spatial-comparison/provenance/validation/cgns-pt-six-view-smoke-20261111/zero-day-baseline-01/manifest.json), [CGNS](../../runs/falcor-pt-spatial-comparison/provenance/validation/cgns-pt-six-view-smoke-20261111/zero-day-cgns-01/manifest.json) |

All six pairs were run with the six-view driver and passed its frozen input, scene-state and camera checks; Bistro indoor also passed its glTF material/texture and lighting audit. Every manifest reports `completed`. These tiny, short runs test functionality only; their images cannot establish comparative quality, performance, convergence, or unbiasedness.

A [GPU stage diagnostic](../../runs/falcor-pt-spatial-comparison/provenance/validation/cgns-pt-stage-diagnostic-20261111/summary.json) compared each of four selected slots across the selector consumers for four Classroom frames at 160×90: zero mismatches were signaled. An injected slot-0 error produced 180, 192, 190 and 207 sentinel pixels, respectively, confirming that the diagnostic detected this fault. The retrace check covers work items actually dispatched; this result does not prove equality for every scene, frame or configuration. A separate [1×1 empty-neighbor check](../../runs/falcor-pt-spatial-comparison/provenance/validation/cgns-pt-empty-neighbor-20261111/summary.json) produced finite output and differed from spatial reuse disabled by at most 5.96e-8 over four frames.

An effective CGNS-off control and estimator validation remain necessary before comparison use. Native pairwise-MIS normalization, geometry rejection and the estimator's response to nonuniform, receiver-dependent neighbor selection need empirical scrutiny; the author and Falcor use different reservoir/normalization implementations. Compare repeated seeds and relevant scene regions against a reference with its own uncertainty. No unbiasedness, author-code equivalence, quality improvement, or completed formal comparison is claimed by these results.
