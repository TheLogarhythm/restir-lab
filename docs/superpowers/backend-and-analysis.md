# Backend and shared-analysis decisions

These decisions consolidate the scaffold, Falcor integration, shared-analysis,
glTF, script-maintenance and research-map notes. Maintained usage lives in
[shared analysis](../shared-analysis.md), the
[Falcor guide](../../renderers/falcor/README.md) and the linked specialist guides.

## Repository and backend isolation

The [accepted layout](../decisions/0001-project-layout.md) keeps RTXDI and Falcor
as separate renderer integrations with shared scene/experiment records and course
writing sources. Preserve course originals, upstream layouts and unrelated work;
keep large assets and generated output ignored. Geometry work supports preparation,
with no Blender renderer plugin in scope. Dependencies, results, authors and
license selection must not be fabricated.

Falcor 9.0 is pinned to `759aad033ff610fb0d82c74f7e0a508d0096d5f2` in
[integration.json](../../renderers/falcor/integration.json). The selected environment
is Windows x64, VS2022, D3D12 Release, with a local preset using SDK 10.0.22621.0.
Use pinned upstream dependencies and the embedded Python; host-side Python launches
Mogwai as a subprocess. Do not substitute the separate RTXDI checkout's packaged
components. Paper-specific Falcor forks require their own pin and build.

The initial integration scope was graph/process adaptation and bounded conventional
PathTracer/ReSTIR PT smoke checks. It did not authorize custom algorithm ports,
quality campaigns, converged references or cross-renderer equivalence. Later
project-authored adaptations have their own reproduction notes and provenance.
Successful smoke captures establish environment operation, not equivalent lighting,
independent trials or GPU performance.

Falcor integration was deliberately placed outside the then-frozen RTXDI campaign
globs: Python under `scripts/run/`, top-level `scripts/analysis/` Python and
`scenes/configs/` JSON. Preserve frozen input identities and campaign state;
never edit a plan to hide drift. Saved running/paused status is not proof of
current renderer ownership or GPU availability.

## Capture and shared-analysis contracts

Capture raw linear `PathTracer.color` separately from display previews. Inspect
decoded EXR channel types and values: FLOAT32 export does not establish the
precision of every renderer intermediate. Smoke methods use separate processes
and advancing RNG streams, with accumulation, denoising and upscaling disabled.
Wall time including startup, compilation and export must not be called GPU time.

Every run uses a new directory and retains requested/resolved settings, graph,
camera, control/RNG schedule, source/build/asset/output hashes, environment and
failure evidence. Timeout cleanup targets the owned process tree. Historical
records without retained metadata remain limited; readers must not manufacture
independence or equivalence.

Shared packages live directly under `src/`: `metrics`, `image_io`, `records`,
`analysis` and `backends`. Pure metrics do not import renderer/process code.
Backend readers normalize immutable saved captures and expose provenance and
capability limits; legacy schema handling belongs at the reader boundary.
Historical compatibility imports do not justify a second analysis implementation.

Tests are organized into core, backends, workflows, assets and fixtures, with
CPU/native/Windows/media groups. Registration and filtering must preserve discovery
and import failures and required integration checks.

## glTF adapter decisions

The November 11 adapter plan required preservation of original glTF resources and
pinned Falcor sources, an auditable material plan, explicit scene settings, and
isolated shader/runtime fingerprints. Its unchecked implementation tasks were
proposals, not a validation record.

Resolve actual resource extensions, including valid MSFT DDS resources when fallback
images are absent, and fingerprint the selected files. Unsupported semantics fail
closed. Record approximations such as threshold treatment of glTF BLEND; do not
present them as exact blending or RTXDI equivalence. Material-factor changes must
keep direct emission and light sampling consistent and preserve unrelated native
Falcor materials. Scene transforms, lights, sky and IES inputs need explicit handling.

The plan's reference target was eight independent 1024-spp sequences at 1920×1080,
averaged in linear HDR without convergence-driven early stopping. That historical
budget is not evidence that the plan completed or the budget of today's references.
It also required bounded, labelled probes, seed/accumulation-safe resume and user
inspection before the next baseline phase. Current frozen reference bindings and
known scene deviations belong to the
[six-view guide](../reproductions/pt-6-views-spatial-compare.md) and
[scene preparation guide](../../experiments/configs/falcor-pt-spatial-comparison/PREPARATION.md).

## Script maintenance history

The October 24 maintenance design kept command names as thin entry points, moved
gallery implementation/templates into `scripts/gallery/`, and separated output
data with an output-directory option while preserving the legacy shim and hashes.
Reusable test fixtures and controlled-experiment orchestration were consolidated;
the fixed matrix moved to JSON without changing resolved configurations.

Build variants use shared transactions: verify original-file restoration and
failure recovery before publishing variants. Preserve scene settings, seeds,
reference policies, capture frames, timing definitions and saved reports. The
original cleanup required a byte-verified recovery stash for exactly five retired
files, and containment/link/active-user checks before clearing disposable
`tmp/`. Progress generators and `scripts/analysis/pdf_archive.py` were excluded.

The historical note reported 417 unittest checks, two Blender fixtures, four
rebuilt variants with byte-identical restoration and all 288 configuration
fingerprints matched. A follow-up corrected filtering that could conceal
discovery/import errors and reported 420 full-suite tests without skips, plus
406 CPU tests in a source copy without local render outputs. Hosted CI and new
GPU rendering were not run. The recorded log/recovery location,
`build/script-maintenance-20261024/`, is absent from the current checkout;
these are historical reported outcomes, not newly verified evidence.

## Research-map decisions

The [research collection](../literature/restir-map/README.md) owns
`papers.json` and `relations.json`; the reading matrix is a synchronized
bibliographic projection that preserves reading/reproduction state. Publication
evidence and relationship evidence are separate. Verify lineage from full text
and citations from references; uncertain relations stay pending. Similarity links
and duplicate records from a visual reference are not scholarly evidence.

The [explorer](../../web/restir-map/README.md) builds static data without a runtime
literature API, Zotero or local-PDF dependency. Native SVG suits the curated graph
and keyboard interaction. Layout coordinates remain independent of paper metadata;
directions and roles are editorial categories, not quality scores. Search, filters,
selection, detail panels and shareable hashes must stay coordinated, including
keyboard, narrow-screen and reduced-motion behavior.

Data validation covers identifiers/versions, edge endpoints and direction,
evidence, reading-matrix drift, public links and independent layout. Browser checks
are still needed for interaction and deployment subpaths. The original scope
allowed branch publication only after a later explicit authorization; GitHub Pages
was separate and opt-in. This history grants no new publication authorization.
