# Run

`python scripts/run/rtxdi.py` captures official FullSample on Cornell Box; add `--interactive` to open it. `--config` accepts a complete JSON configuration. See [setup](../../docs/setup.md).

Build scripts (`build_rtxdi_*.py`) compile renderer source and shaders into executable files. Rebuilding means rerunning the relevant build command, usually recompiling only affected parts; it does not regenerate experiment images.

For a [converted scene](../assets/README.md):

```powershell
python scripts/run/build_rtxdi_external.py
python scripts/run/rtxdi_external.py --scene assets/converted/zero-day/measure-one.gltf --camera-position 7.67003 -0.60688 0.0109 --camera-direction -0.98028 0.10079 -0.16997 --exposure-bias 1 --frame 120
```

The build applies [the external-scene patch](rtxdi_external.patch), saves `FullSampleExternal.exe` with its build provenance, and restores the official source/executable. Do not build the official sample concurrently. Rebuild the variant after changing the patch or upstream revision.

The camera above comes from Measure One's animated FBX camera; exposure is a preview adjustment. The runner freezes animation, clears inherited RTXDI overrides, and records explicit `--exposure-bias` / `--emissive-scale` settings. Runs save logs, scene/resource hashes and capture metadata under ignored `runs/`. These are import checks, not paper-equivalent results.

For controlled multi-scene reuse experiments (linear HDR, fixed PNG previews, frame control and GPU timings), see [the experiment](../../experiments/suites/di-reuse.md).

Shared code lives in `experiment/`: `images.py` handles HDR I/O, `runner.py`
executes runs, and `reference_runner.py` manages reference checkpoints.
`config.json` records requested settings, `resolved.json` records renderer
settings, and `manifest.json` records provenance and status. Failed validation
or conversion preserves raw captures; failed build restoration retains its
`experiment-build-*` backup and prints the recovery path.
