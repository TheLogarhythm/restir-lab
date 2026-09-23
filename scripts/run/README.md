# Run

`python scripts/run/rtxdi.py` captures official FullSample on Cornell Box; add `--interactive` to open it. `--config` accepts a complete JSON configuration. See [setup](../../docs/setup.md).

For a [converted scene](../assets/README.md):

```powershell
python scripts/run/build_rtxdi_external.py
python scripts/run/rtxdi_external.py --scene assets/converted/zero-day/measure-one.gltf --camera-position 7.67003 -0.60688 0.0109 --camera-direction -0.98028 0.10079 -0.16997 --exposure-bias 1 --frame 120
```

The build applies [the external-scene patch](rtxdi_external.patch), saves `FullSampleExternal.exe` with its build provenance, and restores the official source/executable. Do not build the official sample concurrently. Rebuild the variant after changing the patch or upstream revision.

The camera above comes from Measure One's animated FBX camera; exposure is a preview adjustment. The runner freezes animation, clears inherited RTXDI overrides, and records explicit `--exposure-bias` / `--emissive-scale` settings. Runs save logs, scene/resource hashes and capture metadata under ignored `runs/`. These are import checks, not paper-equivalent results.
