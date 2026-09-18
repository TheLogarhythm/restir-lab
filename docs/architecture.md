# Architecture

Source scenes and optional Blender authoring feed backend-specific scene configurations. Experiment configurations select the backend, method, scene, trajectory, seeds, and measurement settings. Future run adapters produce a common manifest, linear images, timings, and diagnostics. Analysis generates small summaries and report figures.

RTXDI and Falcor remain independent builds with their native layouts and pinned versions. Share evaluation conventions rather than combining incompatible renderer trees. Interactive and batch modes should use the same parameter definitions within each backend.

Establish one scene and one repeatable run before adding general infrastructure. Record the fully resolved config and actual execution command. Validate cameras, units, materials, lights, animation, and color conventions when comparing backends; matching model names alone does not establish equivalence.
