# Falcor PT walkthroughs

| Route | Camera movement |
| --- | --- |
| [Bistro Interior](pt-walkthroughs/bistro-interior.json) | Diagonal crossing toward the bar |
| [Bistro Exterior](pt-walkthroughs/bistro-exterior.json) | Street dolly toward the cafe entrance |
| [Classroom](pt-walkthroughs/classroom.json) | Two straight segments joined by a semicircle, looking toward the blackboard |
| [Zero-Day Measure Seven](pt-walkthroughs/zero-day.json) | Straight corridor dolly |

At 30 fps, each 300-frame clip holds the opening pose for one second, moves for eight seconds, and holds the final pose for one second. The path is sampled by arc length at 1.5 scene units/s. The renderer warms up for 40 frames before capture. The three methods share camera poses, one sample per pixel, temporal reuse, and `fixedSeed = render_frame - 1` starting at the first warm-up frame. Continuous motion preserves history. The videos are single-seed descriptive comparisons without a moving reference.

## Preview

Use PowerShell at the repository root after [preparing the scene assets and runtime](../../experiments/configs/falcor-pt-spatial-comparison/PREPARATION.md). Use the Falcor verification environment and a new output path.

~~~powershell
$py = 'build/falcor/verify-env/Scripts/python.exe'
$route = 'scenes/trajectories/pt-walkthroughs/classroom.json'
$runtime = 'build/falcor-reference-runtime/runtime'
& $py -B -m scripts.falcor.trajectory_preview --trajectory $route --runtime $runtime --output runs/my-classroom-preview
~~~

The preview uses ordinary spatial reuse at up to 640×360 with the same 340-frame schedule. Add `--contact-only` to export seven representative frames. For Bistro Interior, use `build/falcor-gltf-composite-runtime-v3/runtime`. Display exposure is fixed for each route. Bistro Interior uses ACES at +7 EV, Zero Day uses Reinhard at +6 EV, and the remaining routes use Reinhard at 0 EV.

## Capture, time, and encode

Production renders 1920×1080 and checks the route paths and hashes in the [approval receipt](pt-walkthroughs/approved-routes.json). Run the three phases for each route and method with a fresh output path. Use `baseline`, `pdf-similarity`, or `cgns` with the [matching runtime](../../docs/reproductions/pt-6-views-spatial-compare.md).

~~~powershell
$method = 'baseline'
$job = "runs/my-classroom-walkthrough/$method"
& $py -B -m scripts.falcor.trajectory_capture --trajectory $route --runtime $runtime --method $method --phase capture --output "$job/capture"
& $py -B -m scripts.falcor.trajectory_capture --trajectory $route --runtime $runtime --method $method --phase timing --output "$job/timing"
& $py -B -m scripts.falcor.trajectory_capture --trajectory $route --method $method --phase encode --capture-output "$job/capture" --timing-output "$job/timing" --output "$job/encode"
~~~

Capture writes 300 linear FLOAT32 EXRs. Timing replays the 340 frames without image export, then adds one final-pose frame to retrieve the last GPU timestamp. The watermark computes GPU FPS from the trailing 15 captured frames of `/onFrameRender/gpu_time`, using the available frames at the start. Encoding produces a ten-second H.264 MP4 with 30 fps playback.
