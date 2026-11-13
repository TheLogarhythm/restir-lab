# Falcor ReSTIR PT CGNS implementation plan

**Goal:** Implement and validate compatibility-guided spatial neighbor selection for the pinned Falcor ReSTIR PT, referencing ReSTIR-CGNS and the existing independent RTXDI adaptation.

**Architecture:** Preserve the pinned Falcor source and existing references. Build a separately fingerprinted shader-runtime overlay and reuse the same selected neighbors in every spatial-reuse stage. Start with point reservoirs and unpaired spatial reuse; unsupported configurations must not silently run. Both ordinary and CGNS comparisons use identical Falcor settings, except neighbor selection. Implement an isolated reproducible smoke runner using the frozen Classroom scene and camera.

**Algorithms:** geometric compatibility with position and normal; bounded K candidates and weighted selection without replacement; separate random stream; retain native rejection and shift/merge/normalization. Document divergences from the author's Falcor 8 code including candidate deduplication/background handling. Clamp experiments do not affect the reference.

- [ ] Establish baseline Git state, pinned Falcor/runtime inputs, CGNS reference code and current tests.
- [ ] Add tests that fail before implementation for selector scores, deterministic and valid distinct neighbors, missing candidates, parameter limits, runtime patch integrity, and consistency across spatial stages.
- [ ] Implement CGNS selector and runtime patch without modifying pinned upstream; preserve original RNG and native sampling for ordinary mode.
- [ ] Implement configuration and smoke runner for matching native and CGNS modes; verify actual resolved settings, camera and reproducibility.
- [ ] Compile shaders and run GPU checks for both modes: disabled control, repeatability, edge/background/empty neighborhoods and actual selection use; validate finite outputs and camera/settings.
- [ ] Run relevant native/unit tests and scaffold checks, document changes, provenance, limits and measurements; do not claim quality gains without a controlled image comparison.