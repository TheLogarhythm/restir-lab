# Run

`python scripts/run/rtxdi.py` captures official FullSample on Cornell Box; add `--interactive` to open it. `--config` accepts a complete JSON configuration. See [setup](../../docs/setup.md).

Build scripts (`build_rtxdi_*.py`) compile renderer source and shaders into executable files. Rebuilding means rerunning the relevant build command, usually recompiling only affected parts; it does not regenerate experiment images.

For a [converted scene](../assets/README.md):

```powershell
python scripts/run/build_rtxdi_external.py
python scripts/run/rtxdi_external.py --scene assets/converted/zero-day/measure-one.gltf --camera-position 7.67003 -0.60688 0.0109 --camera-direction -0.98028 0.10079 -0.16997 --exposure-bias 1 --frame 120
```

The build applies [the external-scene patch](rtxdi_external.patch), saves `FullSampleExternal.exe` with its build provenance, and restores the official source, executable and shaders. Do not build the official sample concurrently. The launcher rejects stale builds after changes to the patch, emission adapter, build helpers or upstream revision.

The camera above comes from Measure One's animated FBX camera; exposure is a preview adjustment. The runner freezes animation, clears inherited RTXDI overrides, and records explicit `--exposure-bias` / `--emissive-scale` settings. Runs save logs, scene/resource hashes and capture metadata under ignored `runs/`. These are import checks, not paper-equivalent results.

For controlled multi-scene reuse experiments (linear HDR, fixed PNG previews, frame control and GPU timings), see [the experiment](../../experiments/suites/di-reuse.md).

Build fingerprints and recovery live in `rtxdi_build.py`. Experiment code lives in `experiment/`: `images.py` handles HDR I/O, `runner.py`
executes runs, and `reference_runner.py` manages reference checkpoints.
`config.json` records requested settings, `resolved.json` records renderer
settings, and `manifest.json` records provenance and status. Failed validation
or conversion preserves raw captures; failed build restoration retains its
`experiment-build-*` / `external-build-*` backup and prints the recovery path.

For a single registered-scene import preview, use the existing experiment backend
(`build_rtxdi_experiments.py` if it has not been built):

```powershell
python scripts/run/rtxdi_preview.py --scene san-miguel --average-frames 32
python scripts/run/rtxdi_preview.py --scene classroom --average-frames 32
```

This captures one static view with the profile camera, lighting and exposure,
then averages the last 32 linear HDR frames into `preview.png` and
`preview.pfm.gz`. `preview.json` records inputs and settings. It runs no comparison
suite or reference generation. Use `--check` for resource validation only.

Classroom's interactive viewer must load the native scene wrapper to include its
source area lights (1920×1080):

```powershell
python scripts/run/rtxdi_external.py --scene assets/converted/classroom/classroom.scene.json --camera-position 2.576395 1.094476 4.465751 --camera-direction -0.252050 0.011199 -0.967649 --width 1920 --height 1080 --exposure-bias 1 --interactive
```

Both local build variants temporarily enable `KHR_materials_emissive_strength`
in pinned Donut, then restore its source. Rebuild them after changing this adapter.
Builds require a clean renderer and dependencies. Reference generation and analysis
require matching shared lighting provenance; regenerate runs whose build records
lack the importer or emission-adapter hashes.
