# Experiment protocol

## Before comparison

State the target claim and implementation origin (author code, port, or independent). Pin code, dependencies, and scenes. Match the integrand: direct-only and full indirect illumination need different references. Validate geometry, cameras, BSDFs, lights, units, animation, bounce limits, and color handling across backends.

## Run records

Each run has a unique ID and a manifest with the actual command, resolved config, code/dependency commits, dirty-state indication, scene hash, GPU/VRAM, driver, OS, compiler, resolution, seeds, and output paths. Preserve failed runs and explain exclusions.

For sequences, record trajectory, frame time, history initialization/reset policy, and warm-up. Evaluate both history start-up/disocclusion and steady state. Repeat with independent seeds; correlated frames are not independent repeats.

## Images and references

Retain scene-linear floating-point radiance before denoising and tone mapping. Generate high-sample reference images or sequences for the same transport target, preferably using a checked conventional estimator. Record reference settings and convergence checks. Do not use a different renderer's image as ground truth without validating transport and material equivalence.

## Performance and quality

Report equal-time quality, sampling settings, GPU pass/total times, memory, and dynamic behavior. Define timing boundaries and separately account for initialization, compilation, and file I/O. Fix resolution and record denoising/upscaling settings. Keep unprocessed outputs even when showing denoised images.

Define error metrics, HDR handling, normalization, masks, and aggregation. For temporal diagnostics, compare against a moving reference rather than treating legitimate motion as flicker. Report variability across independent runs.

## Ablations and records

Vary candidate generation, temporal reuse, spatial reuse, and relevant weighting separately where possible. Register summaries and artifact locations in `results/index.csv`, with config and run IDs supporting each claim. Example configs are not executable benchmark definitions yet.
