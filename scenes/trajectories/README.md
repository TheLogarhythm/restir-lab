# PT trajectory previews

These four routes were approved on 2026-11-16 and used for the completed
three-method production below. Preview generation remains a separate bounded
entry point for inspecting routes. No reference video is requested.

| Configuration | Camera movement |
| --- | --- |
| [Bistro interior](pt-walkthroughs/bistro-interior.json) | Diagonal room crossing, looking toward the bar |
| [Bistro exterior](pt-walkthroughs/bistro-exterior.json) | Street dolly, looking toward the cafe entrance |
| [Classroom](pt-walkthroughs/classroom.json) | Two straights joined by a tangent semicircle, looking at the blackboard |
| [Zero Day](pt-walkthroughs/zero-day.json) | Straight corridor dolly |

Each file refers to the existing scene configuration using a workspace-relative
path, but defines its own camera. The fixed-view reference is not reused as a
reference for the moving camera. Cameras have zero aperture and static scene
animation; transport is the existing one-sample ReSTIR PT configuration with
ordinary spatial reuse and temporal reuse enabled.

## Timing and scale

- Render 40 warmup frames at the initial pose; these are not in the video.
- Capture 300 frames at 30 FPS for exactly 10 seconds.
- Hold the pose for the first second, move for eight seconds, and hold the final
  pose for the final second.
- Sample position by arc length, independent of wall-clock render time.
  For captured frame index `k=0..299`, time is `k/30` and travel is
  `clamp(k/30 - 1, 0, 8) * 1.5` scene units.
- Use `fixedSeed = seed_offset + render_frame - 1` across warmup and capture.
  Continuous motion and the two stops do not reset either history.

All paths are 12 scene units long. One unit is provisionally treated as one
metre from architectural scale, so the configured speed is approximately
1.5 m/s. Source assets do not provide a verified metric calibration; the precise
statement is **1.5 scene units/s**. Camera-height cross sections were checked
when selecting routes. This is not a human body or foot-clearance simulation.

The sampler supports arc-length polylines and a compact `rounded_u` shape:
`start`, `turn_entry`, `radius`, turn `side`, and fixed `target`. The last
straight consumes the remaining distance after the first straight and analytic
semicircle. This avoids storing hundreds of generated waypoints.

## Generate an approval preview

Run from the repository root using the existing verification environment:

```powershell
& build/falcor/verify-env/Scripts/python.exe -B -m scripts.falcor.trajectory_preview `
  --trajectory scenes/trajectories/pt-walkthroughs/classroom.json `
  --runtime build/falcor-reference-runtime/runtime `
  --output runs/pt-trajectory-preview-batches/new-classroom-v1
```

Bistro interior uses `build/falcor-gltf-composite-runtime-v3/runtime`; the
other three use the reference runtime above. The default size is 640x360,
with a hard preview limit of 640x360 and 340 rendered frames. The entry point
only selects ordinary spatial reuse. `--contact-only` renders the same bounded
sequence but exports seven representative frames instead of all 300.
`--exposure-ev` changes only display images; raw linear EXRs remain unchanged. By default, use the existing scene display recipes:
Bistro interior ACES at +7 EV, Zero Day Reinhard at +6 EV, and the other two
Reinhard at 0 EV. Exposure is fixed throughout each route.

Each new output directory contains:

- The trajectory and requested/actual camera and seed records.
- Linear HDR captures, source/runtime hashes, renderer log, and manifest.
- A contact sheet, display PNGs, and a ten-second H.264 MP4 for a full preview.
- A summary distinguishing playback rate from rendering performance.

The preview watermark uses ASCII `|` separators. It labels playback FPS and
time, not measured GPU FPS. Formal videos, after approval, should reuse the
same sampled poses for ordinary spatial reuse, PDF Similarity, and CGNS;
measure GPU frame time separately from image export and encoding before adding
the rendering-FPS watermark.

## PDF history under camera motion

The PDF integration validates reprojected direction history against the actual
previous camera matrix. Geometry checks, decay, confidence, and effective-M
rules remain unchanged. Continuous movement retains valid history. An explicit
cut can call `tracer.reset()` to clear direction statistics; a fresh graph is
required to reset both direction and native lighting reservoirs in pinned
Falcor. Each preview starts with a newly constructed graph.

See [PDF PT implementation and validation](../../docs/reproductions/falcor-pdf-pt.md)
for the mathematical scope and motion diagnostic. Motion support is not a proof
of unbiasedness or a temporal image-quality measurement.

## Archived approval artifacts

Approved route records are consolidated under
`runs/pt-4-trajectories-spatial-compare/previews/`. The original
`approval-preview.json` is a historical pre-approval snapshot: its pending status
and preview-video paths are not current availability claims. Production was
subsequently approved and completed. JPG contact sheets, configuration and logs
remain; preview EXRs, PNG sequences and MP4s have been retired.

Selected takes were Bistro Interior v1 presentation (ACES +7 EV), Bistro Exterior
v2, Classroom v2 and Zero Day v1. Classroom v2 widens vertical FOV to 65 degrees.
Exterior v1 crossed a building after a survey using the wrong geometry source;
v2 corrects the route in the standalone FBX coordinate system. These route
previews are not method comparisons or GPU performance measurements.

## Approved 1080p production

The four routes above were approved on 2026-11-16 for ordinary spatial reuse,
PDF Similarity, and CGNS with temporal reuse enabled. The production root is
`runs/pt-4-trajectories-spatial-compare`. Its manifest tracks the
12 jobs and their capture, timing, and encode phases. Each output directory
must be new. The archived production now retains final videos, complete timing
data and capture metadata; production EXRs and encoding PNG sequences were retired.

The formal entry point is `python -m scripts.falcor.trajectory_capture`:

```powershell
$py = 'build/falcor/verify-env/Scripts/python.exe'
$route = 'scenes/trajectories/pt-walkthroughs/classroom.json'
$runtime = 'build/falcor-reference-runtime/runtime'
$job = 'runs/new-approved-production/classroom/baseline'
& $py -B -m scripts.falcor.trajectory_capture --trajectory $route --runtime $runtime --method baseline --phase capture --output "$job/capture"
& $py -B -m scripts.falcor.trajectory_capture --trajectory $route --runtime $runtime --method baseline --phase timing --output "$job/timing"
& $py -B -m scripts.falcor.trajectory_capture --trajectory $route --method baseline --phase encode --capture-output "$job/capture" --timing-output "$job/timing" --output "$job/encode"
```

Production requires the approved trajectory hashes in the tracked
[approval receipt](pt-walkthroughs/approved-routes.json). This records only the
four hashes already approved on 2026-11-16, copied from and verified against the
original production preflight. Route edits do not acquire approval automatically.
The optional local `build/pt-trajectory-production/preflight.json` remains runtime
provenance and is not the approval authority. Method variants use the
matching current private runtime: PDF profile `normal`, or cached single-neighbor
CGNS. The dimensions are fixed at 1920x1080. Seeds, transport and all 340
trajectory poses match between methods. The preview and formal entry points
keep their own budget checks and share `scripts/falcor/trajectory_render_script.py`
for script generation and actual-camera evidence verification. Formal production
does not import the preview CLI. Capture writes 300 linear FLOAT32 EXRs.
Timing repeats the 340 frames without image export, followed by one final-pose
render solely to retrieve frame340's delayed GPU timestamps.

The watermark is postprocessed, using ASCII `|`:
`CGNS | GPU 24.60 ms | 40.65 GPU FPS | Playback 30 FPS`.
It uses the exact profiler parent `/onFrameRender/gpu_time`, never a sum of
nested events or CPU wall time. GPU FPS is 1000 divided by the trailing15
captured-frame mean GPU milliseconds; the initial windows use the available
captured frames. It excludes image export and encoding and comes from a
separate deterministic replay. Per-frame raw timings and all GPU stages remain
available in `timing/timings.json` and `timing/gpu-frame-timings.json`.

Each final `encode/video.mp4` is verified as H.264, yuv420p,1920x1080,
300frames,30FPS and10seconds. Single-seed videos are descriptive comparisons;
correlated frames are not independent repeats. No moving reference is generated.

## Compact archive availability

`archive-manifest.json` defines current files and capabilities. Original
`manifest.json` files are historical records and may reference deleted or moved
files; they cannot be used to resume or re-encode the archived captures.
`validation/` retains all four camera-motion diagnostic trials, including their
560 EXRs and the failed low-resolution Bistro case. The old standalone preview
and motion-validation folders were consolidated here.

```powershell
python -B scripts/analysis/pt_trajectory_archive.py
python -B scripts/analysis/pt_trajectory_archive.py --decode
```

The verifier hashes retained files, checks timing alignment and original manifest
bindings, and optionally probes/decodes all twelve videos. It does not render.
