# Experimental Falcor ReSTIR PT with CGNS

This is a **project-authored experimental adaptation**, not the authors' renderer or a formal reproduction. Algorithm references are [Junkins et al. (2026)](https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/) and [author code `f28d553`](https://github.com/orion-junkins/ReSTIR-CGNS/tree/f28d553f3b2552b1be829feffea6d1abb1945e1d); Falcor 9.0 is pinned in [integration.json](../../renderers/falcor/integration.json). The [RTXDI DI adaptation](cgns.md) and [PDF-guided PT method](falcor-pdf-pt.md) are separate implementations.

The [six-view comparison record](pt-6-views-spatial-compare.md) owns the completed four-method, four-seed archive, current configuration, preparation/capture commands and verification workflow. This page records CGNS implementation details and historical validation. The November 16, 2026 cleanup did not rerun GPU tests or recompute the measurements below. Retired validation locations identify provenance, not available EXR/PNG evidence; their method images have been removed.

## Selection and supported variants

With default position scale/exponent, center position `x`, neighbor `y`, center camera distance `d`, and shading normals `nx`, `ny`, the compatibility score is:

`exp(-distance(x,y) / (d * sqrt(0.05 / pi))) * max(dot(nx,ny),0)^8`.

Both variants propose up to K=32 candidates in a pixel-radius disk, use a dedicated random stream and Falcor's native RG8Snorm disk table, and skip out-of-bounds, background, self, duplicate, zero-weight and nonfinite candidates. The author implementation uses R2/concentric offsets and differs in epsilon handling, duplicate/self rejection and empty-slot behavior; there is no bitwise author-code parity claim.

| Variant | Selection | Qualified configuration |
| --- | --- | --- |
| Historical four-neighbor (M=4) | [A-ES without replacement](../../scripts/falcor/cgns_point_selector.slang); stop after four scores reach 0.5; unused slots `(-1,-1)` | 1 spp, point reservoirs, four neighbors, radius 32, one spatial round, unpaired, compact retracing, temporal off, aperture zero and VBuffer depth of field off |
| Fast-inspired one-neighbor (M=1) | [A-Chao](../../scripts/falcor/cgns_single_selector.slang); stop after the first score reaches 0.5; [shared CPU/shader arithmetic](../../scripts/falcor/cgns_single_wrs.h) | K=32, radius 30, one spatial round; point/unpaired/compact; temporal-on and temporal-off campaigns |

The [M=4 overlay](../../scripts/falcor/cgns_shader_overlay.py) changes candidate coordinates in a private runtime copy while retaining native geometry rejection, path shifts, reservoir merging and pairwise MIS. It recomputes the list in workload generation, compact retracing and spatial resampling. Equality across stages must be checked for each configuration; source similarity does not establish it. Repeated selection/geometry reads can be costly.

The M=4 overlay does not enforce every graph restriction; callers must enforce them. Paired/reciprocal patterns, area reservoirs, depth of field, other neighbor counts and scheduling modes are unvalidated and unsupported for this overlay. M=4 validation does not validate M=1. The [M=1 overlay](../../scripts/falcor/cgns_single_overlay.py) and [runtime preparation](../../scripts/falcor/cgns_single_runtime.py) have separate markers, hashes and receipts; its [diagnostic overlay](../../scripts/falcor/cgns_single_diagnostic.py) belongs only on a private copy without a production receipt. Historical M=4 runtimes/receipts are not replaced.

The paper's Fast setting also uses M=1/K=32/R=30, but combines temporal/spatial reuse with area reservoirs and reservoir splatting, confidence cap 20 and 40 warmup frames. Its costs average ten trials of 2048-frame sequences. Local point-reservoir, unpaired outputs follow their own campaign schedules and references; matching these three selection parameters does not reproduce the full paper setup.

Both baseline and CGNS use `sampleGenerator=0` (TinyUniform). Native PT replay saves only 32 bits; `getCurrentSeed` cannot retain the 128-bit Uniform generator state, and changing constructors alone does not fix replay. TinyUniform has limited statistical quality; using it for both methods does not establish independent streams. The conventional reference uses a different generator and is not seed-paired with these PT outputs.

## Cached one-neighbor implementation

The current M=1 path extracts attributes once per frame, selects neighbors once per spatial round, then runs native workload generation, retracing and spatial merge. [Overlay generation](../../scripts/falcor/cgns_cached_overlay.py), [attribute extraction](../../scripts/falcor/cgns_cached_attributes.cs.slang), [selection](../../scripts/falcor/cgns_cached_select.cs.slang), [GPU oracle](../../scripts/falcor/cgns_cached_verify.cs.slang) and [host dispatch](../../scripts/falcor/cgns_cached_dispatch.inl) implement it.

- Attribute extraction calls the original V-buffer `getPixelShadingData()` and writes FP32 world position, validity, shading normal and camera distance. Attributes are rewritten every frame from the current scene/camera; textures follow the current resolution.
- Selection writes one linear neighbor ID per pixel/round, or `0xffffffff` when empty. All three consumers read by center pixel; both compact-retrace directions use the same ID. Candidate order, K, radius, RNG, A-Chao scoring and early stopping match the original selector. Native geometry checks, shifts, Jacobians, MIS and reservoir updates still run.
- After building the native offset table, the host finds the minimum L-infinity distance between offsets separated by 1–31 entries across all cyclic windows. If radius times this lower bound exceeds 1.25 pixels, two proposals cannot round to the same pixel; a separate entry point omits the duplicate array. The threshold includes an FP32 margin. Other radii retain explicit duplicate rejection.
- This entry point stores linear pixel IDs in WRS; the numeric handle is not part of probability arithmetic. The GPU oracle still uses the original V-buffer selector.
- Two RGBA32F attribute textures and one R32Uint ID texture add 36 bytes/pixel, about 71.2 MiB at 1080p. GPU events `cgnsCacheAttributes` and `cgnsSelectNeighbors` are children of spatial time and are already included in full-frame time; do not add them again.

A private PathTracer plugin allocates and binds the resources. PathTracer and ReSTIRPathTracing translation units compile against the same modified header to preserve object layout. [Runtime preparation/verification](../../scripts/falcor/cgns_cached_runtime.py) fingerprints the source receipt, implementation, generated shader, plugin and link inputs. Campaign preparation produces cached runtimes; [spatial_capture](../../scripts/falcor/spatial_capture.py) accepts them for `--method cgns`, while the older CGNS verification branch still supports historical receipts. [Regression coverage](../../tests/backends/test_falcor_cgns_cached.py) is separate from GPU evidence.

Diagnostics default off. `RESTIR_LAB_CGNS_VERIFY_IDS=1` enables the full-pixel oracle and synchronized counters; capture/measurement entry points restrict this to scout runs. Timing must use diagnostics off. Historical reference/glTF runtimes were `build/falcor-cgns-cached-reference-1a31ba7337d1c0bf/runtime` and `build/falcor-cgns-cached-gltf-v3-3db15d992c4c3c73/runtime`; changed source produces new fingerprints, so these paths are not a substitute for current verification.

## Configuration and provenance

The shared [spatial comparison configuration](../../experiments/configs/falcor-pt-spatial-comparison/restir-pt-spatial-comparison.json) supplies rendering budget, graph/temporal options and five CGNS shader parameters. Its earlier campaign defaults are 1920×1080, 40 warmup frames and 8 captures with M=1/R=30/K=32; the completed four-seed experiment uses the schedule in the six-view record. The loader rejects area reservoirs, paired/multiple neighbors, multiple spp and transport changes incompatible with the frozen reference. Shader settings are compile-time parameters; each variant needs a separately verified private runtime, identified by parameter, shader and base-runtime fingerprints.

The temporal-on/off campaign entry points read this same configuration and record its SHA-256, normalized settings and variant receipt. New runs need new output directories; changing an existing campaign's configuration is rejected. Campaign identities/captures use workspace-relative paths, attempts are campaign-relative and analysis inputs are relative to their input JSON. External paths must retain their relative location after a move; cross-volume paths cannot be represented. Resume also requires matching source, assets, configuration and runtime fingerprints, not merely relocated paths.

The [scene lock](../../experiments/configs/falcor-pt-spatial-comparison/scene-inputs-v2.json), independent reference catalog and [scene preparation guide](../../experiments/configs/falcor-pt-spatial-comparison/PREPARATION.md) own the frozen camera, scene and transport inputs. Bistro interior uses the `gltf-v3` runtime family; the other five views use the reference family. Both Bistro method capture and adapted reference load `SceneBuilderFlags.DontOptimizeMaterials`; materials/lighting come from its reusable scene profile, while the view owns the camera and interior near plane. The catalog binds the existing reference EXR to these settings.

New Bistro texture audits become workspace-relative only after the renderer's audit passes frozen-reference checks. Older audits referenced by a future schema-2 baseline may contain machine-absolute paths: retain a validated original workspace root or a separately verified portable audit/provenance receipt. Do not rewrite historical audits or infer their root from filenames.

Emerald Square uses `scenes/configs/falcor/emerald-square-converted-reference.pyscene`, renamed from `emerald-square-converted-scout.pyscene` without a content change. The separate ORCA `emerald-square-reference.pyscene` is not this comparison scene. Historical snapshots originally lived under `runs/falcor-pt-spatial-comparison/provenance/relocations/`.

For bounded functional checks, [cgns_pt_smoke](../../scripts/falcor/cgns_pt_smoke.py) is Classroom/reference-only; [cgns_pt_six_view_smoke](../../scripts/falcor/cgns_pt_six_view_smoke.py) accepts one frozen view per invocation, including the adapted Bistro path. Both default to 320×180/four frames, enforce at most 640×360/16 frames, and save only the final frame (`fixedSeed=frame-1`), not an accumulated image. They check resolved graph/camera/input/runtime state; Bistro additionally checks source/material/texture/lighting audits. M=4 runners reject M=1 runtimes. Use NumPy/OpenEXR/Pillow, new outputs and `FALCOR_DEVMODE` disabled. [M=4 runtime preparation](../../scripts/falcor/cgns_runtime.py) requires a new destination under `build/`, source receipt/full non-transient inventory, the Falcor operation lock and an idle renderer; runtime inventory is checked before/after capture. These checks establish bounded operation, not production quality or estimator correctness.

## Historical M=4 validation

The following results are historical, without fresh image-level validation after archive cleanup. Locations below were under `runs/falcor-pt-spatial-comparison/provenance/validation/`; the diagnostic EXR/PNG outputs are retired. Old recorded paths/hashes do not establish current availability.

- `cgns-pt-smoke-20261111`: Classroom `baseline-03`/`cgns-01` completed 320×180/four-frame runs with matching graph settings. The earlier `baseline` failed with unsupported 128-bit replay. Later `baseline-final`/`cgns-final` completed 160×90/two-frame checks of settings, camera and runtime inventory; both EXRs were finite. These establish capture operation only.
- `cgns-pt-six-view-smoke-20261111`: both methods completed Bistro interior at 160×90/two frames and Bistro exterior, Classroom, Emerald Square, Veach Ajar and Zero-day Measure Seven at 64×36/one frame. The retired attempt names are `{view}-baseline-01`/`{view}-cgns-01`, where `{view}` is `bistro`, `bistro-exterior`, `classroom`, `emerald-square`, `veach-ajar` or `zero-day`; each recorded its `manifest.json`. All reported completed and passed frozen-input/scene/camera checks; Bistro interior passed the glTF audit. These tiny runs establish no quality, performance, convergence or unbiasedness result.
- `cgns-pt-stage-diagnostic-20261111/summary.json`: all four slots matched across selector consumers for four Classroom frames at 160×90. An injected slot-0 fault produced 180, 192, 190 and 207 sentinel pixels, confirming fault detection. Retrace coverage includes only dispatched work; the result is not universal stage equality.
- `cgns-pt-empty-neighbor-20261111/summary.json`: a 1×1 empty-neighbor case stayed finite and differed from spatial disabled by at most 5.96e-8 over four frames.

These results do not complete M=4 estimator validation. An effective CGNS-off control, receiver-dependent/nonuniform selection's interaction with pairwise-MIS normalization and native rejection, and repeated-seed regional comparisons against a reference with uncertainty remain necessary. Author and Falcor reservoir/normalization implementations differ. No author-code equivalence or unbiasedness is established.

## Historical cache correctness and performance

The following November 14 cache tests used an NVIDIA GeForce RTX 4060 Laptop GPU, driver 560.94, D3D12, temporal on, 1 spp and a fixed camera. Path seeds were `frame-1`; reuse seeds were `max(0,frame-2)`. Their former `runs/cgns-cache-validation-20261114` directory, including EXRs, timing/oracle summaries, manifests, scripts, camera/graph records and GPU samples, has been removed. The measurements are retained observations and cannot be rechecked from those old paths.

| Scene | Resolution | Warmup | HDR frame IDs | Timed GPU frame IDs | Old/new HDR |
| --- | --- | ---: | --- | --- | --- |
| Emerald Square | 640×360 | 32 | 33–40 | 33–39 | 8 frames bitwise equal |
| Emerald Square | 640×360 | 8 | 9–20 | 9–19 | 12 frames bitwise equal |
| Emerald Square | 320×180 | 32 | 33–44 | 33–43 | 12 frames bitwise equal |
| Bistro interior glTF | 320×180 | 20 | 21–28 | 21–27 | 8 frames bitwise equal |

Across all 40 frames, every RGB float32 channel was bitwise equal, maximum absolute difference 0, with no differing positions; all images were finite. Both runtime families also ran a 97×65/six-frame full-pixel oracle. Another Emerald test used radius 1/two spatial rounds, resized 97×65 → 103×67 → 97×65 in one process, and changed camera position/target at frame 5. Together these checked 153,704 pixel/round combinations with zero ID mismatches, covering empty sentinels, duplicate fallback, per-round RNG, resize and camera updates.

The table gives GPU milliseconds averaged with diagnostics off, using profiler `value`. The one-frame profiler delay leaves the final HDR without returned timing, hence one fewer timed frame in each group.

| Scene / resolution | Old frame | Cached frame | Old spatial | Cached spatial | Attributes | Selection |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bistro interior 320×180 | 4.0499 | 3.3131 | 1.7171 | 0.6393 | 0.0095 | 0.0712 |
| Emerald 320×180 | 10.4862 | 10.6397 | 3.2971 | 2.2547 | 0.0709 | 0.1092 |
| Emerald 640×360, 32 warmup, adjacent runs | 27.2679 | 23.4208 | 9.1140 | 6.2167 | 0.2123 | 0.2442 |
| Emerald 640×360, 8 warmup, earlier runs | 48.3858 | 118.8035 | 23.7166 | 20.4979 | 1.0345 | 0.2432 |

Bistro frame/spatial time fell about 18.2%/62.8%; adjacent 640×360 Emerald runs fell 14.1%/31.8% (initial sampling 9.15→8.99 ms, temporal 6.02→5.83 ms). At 320×180 Emerald spatial fell 31.6%, but frame time rose 1.5%. The earlier 640×360 slowdown included initial sampling 13.17→61.86 ms and temporal 7.30→23.44 ms, although the new shaders are spatial and HDR was bitwise equal. Its cause is unresolved. Total GPU memory approached the 8 GiB capacity and clocks varied; residency, other load and power state were hypotheses, not established causes.

The initial cache retained a general duplicate array: Emerald 320×180 standalone selection cost about 4.25 ms. The offset-table proof and separate entry point reduced the measured step to about 0.11 ms. Those early artifacts are also retired.

These short, single acquisitions contain correlated frames and did not control competing processes or GPU clocks. They support the measured stage savings and removal of repeated selection/geometry reads, not a general six-view frame-time gain or the paper's 2–5% overhead range. Current archive performance eligibility and quality analysis belong to the six-view record.

## Retired workflow boundary

`spatial_reuse_audit`, `spatial_three_methods` and `falcor_three_methods` were removed from active source; their pre-refactor source is locally archived in `build/pt-maintenance-20261116/source-before.zip`. Historical reports/receipts remain unchanged. `cgns_temporal_diagnostics` and `cgns_single_diagnostic_run` describe the retired loose layout. Use the current six-view workflow for new capture and archive verification; historical paths and test counts are not current validation.
