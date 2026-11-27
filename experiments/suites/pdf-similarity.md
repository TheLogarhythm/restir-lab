# RTXDI PDF Similarity suite

The controlled comparison pairs PDF off and on in the same FullSamplePdf build at 1920×1080, using independent method seeds 1, 2 and 3. It uses combined reuse, `pdf_history_mode=0`, vMF parameters 100/10/1000, candidate counts 24/8/1 for local/environment/sun, four neighbors at radius 32 pixels, and lighting history 20. Match the camera, lights, visibility, initialization and exposure for each pair. Disable denoising, antialiasing, jitter and bloom. [Configuration](../configs/pdf-controlled.json) · [Implementation and setup](../../docs/reproductions/rtxdi.md#pdf-similarity)

## Conditions and measurements

| Condition | Schedule |
| --- | --- |
| Cornell Box, Arcade, Bistro Interior and Bistro Exterior static | 128 frames. Save 1, 20, 40 and 128. Score frame 128 and average GPU time over frames 41–128. |
| Arcade, Bistro Interior and Bistro Exterior camera motion | 96 frames at logical 30 FPS. Hold 1–32, move over 33–64, then hold 65–96. |
| Bistro lighting change | Same 96-frame schedule and fixed camera. The selected emissive group follows a mirrored cosine ramp from 1× to 2× to 1× over frames 33–64. |

The main matrix has 48 method runs. The Bistro Interior spatial-only ablation adds six. The two Bistro static views add 24 method runs at two and eight neighbors. Equal-time estimates also use the measured four-neighbor points and interpolate only within overlapping GPU-time ranges.

Score full-image and selected-region scene-linear luminance SMAPE, with RGB RMAE and NRMSE as diagnostics. Dynamic spatial scores use only frames 32, 48 and 96. Local TRMAE uses pairs 31→32, 47→48 and 95→96. Average GPU time separately over each 32-frame phase and include all direction updates. The logical 30 FPS rate sets the frame schedule. [Metric definitions](../../docs/metrics.md) · [Results](../../results/summaries/pdf-similarity/README.md)

## Reference targets and budget

The fixed union contains 15 distinct physical states. Use matched camera, scene, lighting and corrected direct-light transport for each reference. Static scores use frame 128. Dynamic references cover the three scored frames and their adjacent support frames. Deduplicate identical physical states.

| States | Reference rule |
| --- | --- |
| Cornell and Arcade, five states | Independent seeds 1001 and 2001. Allocate 64/8/4 local/environment/infinite samples per batch. Require two consecutive passing checkpoints with a 0.1 uncertainty ratio, covering full-image and selected-region SMAPE/RMAE, local gradients and sensitivity of paired differences. The cap is 1,048,576 local samples per stream. The reported references passed at 16,384 local samples per stream. |
| Bistro, ten states | Seed 1001 only, exactly 262,144 cumulative local samples, with the same 64/8/4 allocation. Validate exact identity, sample count and restart lineage. Independent-stream precision, checkpoint stability, gradients and sensitivity are recorded as `not_evaluated`. |

The original suite used a 30-hour wall-clock budget. The completed sparse reference and analysis phase used a separately approved 15-hour window. Record a new approval before changing budgets or precision criteria.

## Commands

With the RTXDI assets ready, build the two variants and use a fresh suite name for a technical pilot. The pilot checks finite captures, replay, resets and scene alignment.

~~~powershell
python -B scripts/run/build_rtxdi_pdf.py
python -B scripts/run/build_rtxdi_experiments.py --reference
$suite = 'pdf-controlled-reproduction'
python -B scripts/run/rtxdi_pdf_controlled.py --output-name $suite --pilot-only
~~~

For sparse evaluation with all 78 matching method captures, first validate the prepared inputs and reference policy. Then use a pinned launch plan and its matching approved window. Replace the three JSON filenames with the corresponding records for the prepared suite.

~~~powershell
python -B scripts/run/rtxdi_pdf_controlled.py --output-name $suite --references-only --validate-only --reference-window REFERENCE_WINDOW.json --reference-policy BISTRO_POLICY.json
python -B scripts/run/rtxdi_pdf_controlled.py --output-name $suite --references-only --reference-window REFERENCE_WINDOW.json --launch-plan LAUNCH_PLAN.json
~~~

The first command in this block verifies inputs without rendering. The second renders the authorized reference targets and analyzes them. The default worker without `--references-only` applies the original reference policy. [Runner details](../../scripts/run/README.md#controlled-campaign-maintenance)
