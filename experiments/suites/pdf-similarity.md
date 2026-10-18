# PDF Similarity controlled comparison

Approved plan, revised 2026-10-18. Evaluate the [RTXDI adaptation](../../docs/reproductions/pdf-similarity.md) under the [experiment protocol](../protocol.md). Complete technical pilot checks, then all method renders and direct comparison products, then references within the total 30-hour budget. Reference acceptance gates quantitative error analysis and reference-based products. See [the runner](../../scripts/run/rtxdi_pdf_controlled.py) and [setup](../../docs/setup.md#controlled-pdf-comparison).

## Questions and controls

Where does PDF-based spatial reuse help or hurt image error, GPU cost and temporal behavior? Separate camera motion from changing lighting; improvements are not assumed.

Compare PDF off/on in the same `FullSamplePdf` build, using combined reuse and seeds 1/2/3. Match resolved scene/camera/light states, candidate generation, visibility, initialization and exposure. Keep `pdf_history_mode=0`, alpha/beta/lambda=100/10/1000, 24/8/1 local/environment/sun candidates, four spatial neighbors and lighting history 20. Disable denoising, AA, jitter and bloom; measure linear HDR before tone mapping. Fix the display transform/exposure per condition. Reset light and direction histories only at sequence start.

## Bounded comparison matrix

| Condition | Purpose | Resolution |
| --- | --- | --- |
| Cornell static | Simple control | 1920x1080 |
| Arcade static | Detailed emissive/material control | 1920x1080 |
| Bistro interior static | Shadow boundaries, glossy surfaces and fine geometry | 1920x1080 |
| Bistro exterior static | Outdoor geometry/illumination; start from the native `Outside` camera | 1920x1080 |
| Arcade translation | Camera-motion control | 1920x1080 |
| Bistro interior translation/turn | Disocclusion and changing glossy highlights | 1920x1080 |
| Bistro exterior translation/turn | Outdoor visibility and shadow changes | 1920x1080 |
| Bistro changing light, fixed camera | Isolate adaptation to lighting changes | 1920x1080 |

Eight conditions give 48 method runs (24 off/on pairs), excluding pilots/ablations/equal-time sweeps; Bistro accounts for five conditions. Preview and freeze poses, paths, lighting and diagnostic regions before inspecting method differences. Keep outdoor coverage and report scenes separately. All formal renders and references use 1920x1080 with spatial radius 32 px.

Static runs use 128 frames: capture frames 1/20/40/128, evaluate final-frame quality across seeds, and average steady GPU times over frames 41-128. Temporal clips use **96 consecutive frames at a fixed logical 30 FPS**: frames 1-32 stationary, 33-64 moving/changing, 65-96 stopped. Interpolate camera position and orientation over 32 increments from the held starting pose. Record every resolved pose/light state. GPU execution/export speed must not advance scene time. Export every temporal HDR frame for all seeds, plus synchronized 30 FPS comparison/reference videos for seed 1. Report start-up, motion/change and recovery separately; 30 FPS is the logical/playback rate, not a performance claim.

## Measurements

- **SMAPE, primary spatial metric:** `100 * mean(abs(Y(I)-Y(R)) / (abs(Y(I))+abs(Y(R))+1e-4))`, where `Y` uses linear RGB weights (0.2126, 0.7152, 0.0722). Report percent, without a factor of two. PDF Similarity uses SMAPE but does not fully specify its convention; we explicitly adopt a luminance version with the normalization/epsilon reported by [CGNS, footnote 3](https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/). Retain linear RGB RMAE for continuity and NRMSE/selected ROI error as diagnostics. Absolute scores are not reproductions of the paper's figures.
- **TRMAE, primary temporal metric:** adopt [Işık et al. 2021, Section 5.1.1, Eq. 16](https://techmatt.github.io/pdfs/interactiveMonteCarloDenoising.pdf): `mean(||delta(I)-delta(R)||_1 / (||delta(R)||_1+0.01)) / 3`, with RGB L1 norms and adjacent-frame differences `delta(I)_t=I_t-I_(t-1)`. Use linear radiance, unchanged radiance units/frame interval, no warping or division by seconds. Average pixels/frame pairs within each phase and seed before summarizing independent seeds. This established rendering-video metric is adopted for raw ReSTIR; it is not a complete perceptual test. Inspect synchronized video/per-frame SMAPE as well: constant bias can have small temporal error.
- **GPU cost:** initial, spatial and total times, including all direction updates and light preparation/PDF rebuilding/presampling. Record timing boundaries and exclude export/I/O. Both PDF off/on allocate direction banks; disclose their 126.6 MiB at 1080p relative to ordinary DI.

Assign each temporal pair to its later frame: motion includes 32->33, recovery includes 64->65. Keep one quantitative temporal metric initially. CGNS's lag-three relative autocovariance measures persistence across independent static sequences; reserve it for the later CGNS study, since it does not directly measure flicker. Correlated frames are not independent repeats.

## Error visualization

Generate maps after reference acceptance, directly from aligned linear HDR inputs:

- **Error magnitude:** map the per-pixel SMAPE term above to `magma`, with one fixed 0-100% scale. The dark-to-bright palette follows the [FLIP tool's error-map presentation](https://github.com/NVlabs/flip/blob/main/src/cpp/FLIP.h); label these maps SMAPE, since the palette does not change the metric.
- **Signed residual:** show `100 * (Y(I)-Y(R)) / (abs(Y(R))+1e-4)` with a zero-centered blue-white-red scale, blue for darker and red for brighter than reference. Use a shared -50% to +50% display range, inspired by [PDF Similarity, Figs. 10-11](https://doi.org/10.1145/3585501). This explicit normalization is our diagnostic convention. Clip only the display, record the clipped-pixel fraction, and retain unclipped values. A single-frame residual is not evidence of bias by itself.
- **Temporal localization:** for the preselected boundary/recovery frames 32/33/64/65/96, visualize the per-pixel TRMAE term before spatial averaging. Freeze its display scale from the pilot, share it across methods/frames, and state the range and clipping. Label each map with both frames of its difference.

For seed 1, export static frame-128 panels with Reference / PDF off / PDF on, corresponding error maps, and identical preselected ROI crops. Export a 30 FPS SMAPE heatmap video for each temporal pair alongside the rendered/reference videos. Use shared colorbars, units and scales across methods, frames and crops; never normalize each image independently. Save figure inputs/settings and use full-image, all-seed metrics for conclusions.

## Changing lighting

[ReSTIR DI](https://research.nvidia.com/labs/rtr/publication/bitterli2020spatiotemporal/) supports dynamic lighting. Pinned RTXDI updates light data and [current/previous index mappings](https://github.com/NVIDIA-RTX/RTXDI/blob/a6efab966b7c3b272da0461578eb56ac61c7cbff/Doc/Integration.md); its Bistro scene already includes emissive-material animation. The controlled runner freezes unrelated animation and records per-frame material updates and light correspondence.

Use one existing Bistro emissive group, initially the named pink string-light material, with fixed camera/geometry. Verify it affects the selected receivers before freezing the view. Modulate its original intensity positively **1 -> 2 -> 1** over frames 33-64 using 16 cosine-ramp increments and their mirrored return; then hold. This needs only 17 distinct lighting states. Keep other emitters/environment unchanged and preserve light identities. Do not reset history during the change. Global scaling of all lights can leave their relative distribution unchanged.

Apply absolute intensity from the saved original value before material-buffer upload/light preparation. Validate current/previous correspondence and refreshed sampling PDFs; leave unrelated Bistro animations off. Moving emitters, light birth/death, abrupt steps and sky-texture changes remain later extensions. This test targets PDF-history adaptation without adding geometry animation.

## References and budget

Generate conventional direct-light images **and complete frame-aligned reference sequences**, shared across methods/seeds. Freeze each target's exact camera, lighting and scene state throughout accumulation; advance only sampling RNG. Include resolved per-frame lighting in reference identity/provenance. Reuse references only for identical states, never interpolate between poses. A 32-step camera clip has 33 unique targets despite its 96 output frames; static holds reuse the corresponding image.

Audit build/lighting provenance and DI's geometric-hemisphere support before reusing old references; regenerate references from the earlier estimator that omitted this support gate. Preserve the five retained DI/Zero-Day directories. Old RMAE acceptance alone does not validate SMAPE or temporal gradients. Check independent half-stream agreement and checkpoint stability for SMAPE/RMAE, interpreted regions and consecutive-reference differences, including their effect on reported TRMAE and its normalization. Require two accepted checkpoints, targeting reference uncertainty below 10% of the best method's corresponding error. Check reported method differences against reference-stream/checkpoint changes; otherwise report them as inconclusive. Do not inherit the historical Bistro ratio of 0.3 automatically.

Reference batches request 64/8/4 local/environment/infinite samples. Preserve validated 64/64/64 checkpoints and continue their equally weighted full-target batch means. Record each segment's allocation and cumulative requested counts separately per stream; absent light classes execute no samples. Checkpoint progress counts local samples (64 per batch), not equal samples in every class. Keep all precision gates above unchanged.

The reference maximum remains 1,048,576 local samples per stream. Stop at the first two consecutive passing checkpoints; changing the maximum or precision requires prior explicit user approval.

The total budget is **30 hours including prior work**, conservatively counted as elapsed wall time from the suite's earliest render. Persist the deadline across restarts; stop rendering when exhausted. Save all 78 method runs (48 main, 6 spatial-only, 24 new equal-time) and seed-1 direct comparison images/videos before generating further references. Use the remaining budget for the 116 distinct reference states, prioritizing static comparisons and one Bistro camera clip. Preserve valid checkpoints and report incomplete coverage. Without accepted references, direct comparisons remain visual observations; do not produce error metrics, heatmaps or reference videos. Keep HDR references and fixed-exposure display copies; calculate metrics from HDR.

## Order and cleanup

1. Implement metrics/error-map export, deterministic orientation/time/light controls, continuous capture and frozen-state references. Validate binaries/reference target keys. No additional baseline-only campaign is needed.
2. Run a small technical pilot: Cornell sanity plus Bistro interior/exterior and representative motion/light states. Check finite HDR, replay, exact frame alignment/reset behavior and build/state provenance. Freeze the matrix; reference precision and measured light influence are validated later.
3. Capture all method runs: static pairs, both Bistro camera clips, Arcade control, isolated Bistro lighting, then the ablation/equal-time runs below. Save labeled reference-free comparison panels/videos before resuming reference generation. Validate reference precision and lighting influence before error panels, reference videos and quantitative conclusions; keep neutral/unfavorable findings.
4. Limit the spatial-only ablation to one preselected Bistro view. For equal time, sweep neighbor budgets 2/4/8 on the two Bistro static views; compare only overlapping measured GPU-time ranges and confirm selected pairs with three seeds. Keep separate from fixed-setting reports; accumulation is not equal-time real-time work.
5. Once a pilot passes and no formal result/reference depends on its artifacts, keep a compact validation record (configs, source/build/asset hashes, checks, cost and outcome), then delete bulky outputs/logs. Preserve unresolved failure diagnostics and formal artifacts; leave the five retained run directories untouched.

For Oct 25, prioritize verified static pairs and one Bistro camera comparison with a matched reference video; label unfinished conditions. Complete remaining conditions/equal-time work alongside final evaluation without delaying CGNS integration. Staff feedback is addressed through challenging views, temporal evaluation, trustworthy references and clear explanations of when PDF reuse helps or struggles. Exploratory work remains on local branch `research/restir-limits` (`fc4c5c3`).
