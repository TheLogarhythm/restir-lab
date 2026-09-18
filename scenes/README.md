# Scenes

Candidate starting resources:

- RTXDI Assets (Cornell Box and Bistro): https://github.com/NVIDIA-RTX/RTXDI-Assets
- ReSTIR PT demo (Veach Ajar): https://github.com/DQLin/ReSTIR_PT
- Bitterli resources: https://benedikt-bitterli.me/resources/

These are not downloaded or validated assets. `manifest.yaml` contains no registered scenes. It uses JSON syntax, a valid YAML subset, for standard-library validation.

For every registered scene, provide `id`, `source_url`, `source_revision`, `sha256`, `license`, `local_path`, `conversion`, `modifications`, and `backend_configs`. Use relative asset paths. Hash downloaded archives or immutable bundles and state what was hashed. Never substitute a model name for a version or invent license details.

Keep backend camera/material/light settings in `configs/`, including units, coordinates, color spaces, and unsupported features. Store deterministic motion in `trajectories/`. Procedural generators belong in `procedural/`; optional Blender sources in `authoring/`. Keep large binaries out of normal Git history.
