# DI reuse controls

Adapted RTXDI v3.1 author code; implementation checks, not paper-equivalent results.

## Run

With the [RTXDI environment](../../docs/setup.md) and scene assets installed, from the repository root:

~~~powershell
python -m pip install -r scripts/run/requirements.txt
python scripts/run/build_rtxdi_experiments.py
python scripts/run/rtxdi_reuse.py --scene all --scenario all --check
python scripts/run/rtxdi_reuse.py --scene all --scenario all --diagnostics --output-name di
~~~

Active scenes: cornell-box, arcade, bistro. `--scene all` uses these three;
Zero-Day remains available by explicit ID for later validation. Each
scene/scenario runs initial, temporal, spatial, combined in separate processes.
--mode combined selects one mode; --scenario
static, motion or reset selects one sequence. Defaults: static, all modes,
1920×1080, seed 1. --resolution 640 360 is useful for smoke checks.

Experiments default to headless rendering (no window, UI or swapchain). Add
`--windowed` for manual inspection; keep that window unminimized and do not change
UI settings. Close FullSample before building; avoid concurrent renderer builds/runs.
The build restores official sources, executable and shaders. Re-run the build
command after changing the renderer revision, build script, integration patch,
helper or reference shader; recorded hashes reject stale builds.

## Controls

[Experiment definition](../configs/di-reuse.json): 128 frames; 33 initial candidates:
24 power-sampled local lights (`POWER_RIS`), 8 importance-sampled environment
directions and 1 analytic-sun candidate, with no BRDF candidates. All current scene profiles
provide a procedural environment. Spatial budget: 4 neighbors, radius 32 pixels,
history limit 20.
The four modes differ only in reuse. Initial means initial RIS + final shading.

The local/environment allocation follows [ReSTIR DI §5](https://cs.dartmouth.edu/~wjarosz/publications/bitterli20spatiotemporal.html),
with one extra candidate for the sample's independent directional sun
(`analytic_sun: true`). RTXDI uses a mip-PDF/presampled light pool rather than the
paper's alias table. Material conversion and the remaining algorithm settings
are not paper-matched; each run's saved configuration defines its lighting target.

[Scene profiles](../../scenes/configs/rtxdi/README.md) specify resources, camera/FOV,
motion endpoint, lighting and preview exposure. Cameras are applied every frame;
scene animation is frozen. Bistro uses the full scene wrapper, including its lights
and additional models.

| Scenario | Sequence | Captures |
| --- | --- | --- |
| static | Fixed camera, empty history at frame 1 | 1, 8, 32, 128 |
| motion | Hold 1–32; linear translation to the scene's endpoint over 33–96; hold 97–128 | 1, 32, 33, 64, 96, 97, 128 |
| reset | Fixed camera; clear DI reservoirs and invalidate previous depth before frame 65 | 1, 32, 64, 65, 72, 96, 128 |

Sampling frame = seed × 1048576 + logical frame − 1, independent of wall time.
Reset clears history without restarting the random sequence.

Denoising/input formatting, AA/TAA/DLSS, image accumulation, bloom, tone mapping,
auto exposure, pixel jitter, checkerboard, boiling filtering, visibility shortcuts
and disocclusion sample boosts are disabled/bypassed. Raytraced bias correction,
final visibility, material textures, emission, compositing and transparency remain.

## Outputs

`--output-name di` selects `runs/di/`; omission uses a UTC timestamp.
Names accept 1–64 letters, digits, hyphens or underscores, starting with a letter
or digit; reserved device names and existing directories are rejected.
`runs/<name>/<scene>/<scenario>/<mode>/seed-<n>/` contains:

- config.json, resolved.json, manifest.json, renderer.log: frame trajectory,
  requested/resolved settings, loaded scene, code/build/asset hashes and hardware.
- frame-*.pfm.gz: lossless gzip (level 6) of scene-linear RGB float32 decoded from
  RGBA16_FLOAT after compositing and transparency; source values are preserved.
- frame-*.png: viewing copies using the scene's fixed exposure, per-channel
  Reinhard x/(1+x), then sRGB. No image-dependent normalization; metrics read PFM.
- timings.csv: all upstream GPU sections, one row per logical frame. Synchronous
  timings exclude capture/readback, file I/O, UI and present. Only `--windowed`
  includes a raw display blit. Reset clearing precedes timing. Use the same window
  mode for timing comparisons; these are not real-time FPS measurements.
- captures.json: finite/brightness checks and, with --diagnostics, final reservoir
  M mean/median/p95/max over valid reservoirs and valid fraction over all pixels.
  M is multiplicity, not the candidate budget or independent sample count.
  Requested neighbor budget is recorded; accepted-neighbor counts are not measured.

HDR is compressed directly, without an intermediate PFM file. Successful conversion
removes temporary GPU readbacks; failed runs retain partial outputs.
Records use relative filesystem paths: command/config/output paths are relative
to the run directory; scene source paths and code paths to the repository root,
located by `repository_root`; asset hash keys to the scene's asset root.
Renaming the suite within `runs/` preserves these
paths; `run_id` remains its original identifier. Renderer log mount names such as
`/Assets/Media` are virtual filesystem labels, not host paths.
Equal-time comparisons remain separate work.
