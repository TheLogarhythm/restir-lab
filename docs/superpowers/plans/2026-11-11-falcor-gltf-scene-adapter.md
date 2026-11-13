# Falcor glTF Scene Adapter Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkboxes.

**Goal:** Reuse the Bistro glTF through a generally applicable Falcor scene/material adapter and produce a verified 1920×1080 eight-seed ×1024-spp PathTracer reference.

**Architecture:** Preserve the original glTF, referenced assets and Falcor upstream. Resolve actual glTF resource extensions and create an auditable material plan, adapt explicit scene.json settings with fail-closed handling of unsupported features, and isolate shader modifications and runtime fingerprints. The same frozen scene and settings must be reusable by future ReSTIR PT comparisons.

**Tech Stack:** Python, Falcor 9, Slang, glTF 2, DDS, EXR, Windows D3D12.

**Spec:** User-approved task and four-step design in conversation (2026-11-11).

## Global Constraints

- No main-branch commit without explicit user request; do not overwrite old artifacts.
- Formal reference: 1920×1080; eight independent seed sequences, 1024 samples each; average linear HDR; no convergence-driven early stop.
- Probe renders are bounded and labeled diagnostics; unknown semantics fail closed; RTXDI threshold BLEND is a documented approximation, not glTF exact blending.
- Preserve input, shader, runtime, GPU, seed, asset and scene provenance. Do not claim renderer or transport equivalence without tests.
- User will inspect completed reference before the ReSTIR PT baseline phase.

## Review Focus

- Missing fallback images with valid MSFT DDS: verify selected texture exists and is fingerprinted.
- SpecGloss, emissive factors, glass, alpha masking and shadows: validate controlled input/output at material and rendering levels.
- Mixed native-Falcor and adapted glTF materials: ensure shader changes do not silently alter unrelated materials.
- Source scene transforms, lights, sky and IES: account for every input and explicitly report unsupported or approximated behavior.
- Resume/interruption: preserve previous outputs, verify provenance, and do not count repeated seeds or reset accumulation.

## Tasks

- [ ] Implement and test reusable glTF DDS/material mapping, extension validation, transmission and explicit alpha policy.
- [ ] Implement and test isolated material-factor runtime with consistent direct emission and light sampling; maintain non-glTF material behavior.
- [ ] Implement and test generic scene.json parsing, hierarchy/transforms and explicitly selected light/environment mappings.
- [ ] Add a scene wrapper and reusable runner/provenance inventory; preserve existing reference code and frozen results.
- [ ] Run controlled GPU fixtures, validate per-frame accumulation and random sequences, and compare a bounded Bistro scout against the original view.
- [ ] Render and verify eight 1024-spp 1080p seeds; compute and check their linear EXR average and generate a display preview.
- [ ] Run relevant tests/scaffold, report scene deviations and deliver images for user inspection.
