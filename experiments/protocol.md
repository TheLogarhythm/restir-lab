# Experiment protocol

## Before comparison

State the claim and identify author code, adaptations and independent implementations. Pin code, dependencies, scenes, camera, rendering controls and reference targets. Match the transport integrand, including direct versus indirect lighting, geometry, materials, lights, bounce limits and color conventions. Set the GPU budget, sample caps and reference precision criteria before running. Changes require explicit approval.

## Run records

Record a unique run ID, exact command, resolved settings, code and dependency revisions, asset hashes, dirty state, OS, compiler, GPU and VRAM, driver, resolution, seeds and output paths. Preserve failed attempts and explain exclusions. For sequences, record frame time, trajectory, warm-up, resets and disocclusion. Treat independent seeds as replicates and consecutive history-sharing frames as repeated measurements within each run.

## Images and references

Retain scene-linear HDR before denoising and display transforms. Use a high-sample reference with matched camera, scene and transport, and record precision checks. Cross-renderer comparisons require validated material and transport equivalence. Compact retired outputs only with explicit approval and retain measurements, settings, display evidence and a hash inventory. Record whether recalculation needs new renders.

## Performance and quality

Report metric definitions, normalization, masks and aggregation. For moving cameras, compare temporal errors against matched moving references. Report GPU pass and frame timing boundaries, separating initialization, export and file I/O. Distinguish matched settings from equal time. Include equal-time quality and memory for the final method evaluation, and report timing variability across independent runs. Record sampling, denoising and upscaling settings.

## Ablations and records

Vary candidate generation, temporal reuse, spatial reuse and weighting independently where possible. Register results by config and run ID in the [results index](../results/index.csv). [Suite guides](suites/README.md)
