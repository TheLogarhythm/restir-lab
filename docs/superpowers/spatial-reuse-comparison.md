# Spatial-reuse comparison decisions

This note preserves comparison choices and dated validation provenance.
Method mathematics and operating commands belong to the maintained
[RTXDI spatial-reuse study](../reproductions/spatial-reuse.md),
[RTXDI CGNS](../reproductions/cgns.md),
[RTXDI PDF Similarity](../reproductions/pdf-similarity.md),
[Falcor CGNS](../reproductions/falcor-cgns-pt.md),
[Falcor PDF-guided PT](../reproductions/falcor-pdf-pt.md) and
[six-view guide](../reproductions/pt-6-views-spatial-compare.md).

## RTXDI comparison decisions

Compare original versus CGNS within DI/GI/PT using one build per pair.
GI/PT's CGNS toggle changes only indirect spatial selection; retain native
rejection and do not replenish rejected neighbors. Reuse verified historical
DI inputs explicitly rather than silently treating them as fresh captures.

The historical DI reference matched its direct-lighting target; GI/PT shared
direct plus one indirect bounce. The selected ordinary-PT reference budget was
8192 paths/pixel, seed 1001, with 4096/8192 checkpoints. These RTXDI choices do
not describe Falcor's later references.

One configuration schema separates algorithm, reuse, static protocol, view,
frame, seed, reference and input reuse. Configuration validity and approved-budget
authorization are distinct. Configuration/collection, process lifecycle, numerical
analysis, display and verification have separate responsibilities. Adapt legacy
schemas at the reader boundary instead of maintaining parallel pipelines.

Freeze actual inputs and sources. Historical integrity, new reanalysis and
current-code rendering are separate operations: never silently refresh old receipts
or use archive validity as permission for new rendering. Keep frame and seed axes
distinct. Motion would require frame-specific geometry/references and temporal
statistics; static masks cannot establish motion validity.

## RTXDI validation history

The November 6–7 record describes historical local validation, not current-code
conformance. Campaign `cgns-di-gi-pt-20261106` contained 30 method entries and ten
references, remained `awaiting_ui` in its original state and predated later
transport fixes.

Post-debug 64×64 GI/PT saved captures and reference ancestry were revalidated.
Native-off pixels and uninterrupted/resumed references matched exactly. Across
20 view/group regression cases, SMAPE, masks, error/delta arrays, timing and
neighbors were exact. Legacy DI displayed improvement differed by at most
1.98e-14 percentage points from reduction-order rounding, without sign changes.
Review resolved configuration-validation bypasses, input-digest rebinding, GI/PT
timing fields and historical reference pairing.

The note reported 676 CPU/workflow, 23 native and eight Windows tests plus
scaffold before commits `864400e`, `47c8a55` and `d7e6b6f`. Isolated staged
snapshots checked DI (19 tests), transport (23) and comparison config/metrics/plan
(21). The user viewed and accepted the report, while machine receipts still
recorded `ui_verified=false`; historical states were not rewritten to infer UI
verification. No push or formal rendering occurred in that validation.

The original evidence locations,
`runs/validation/comparison-refactor-20261106-2337/` and
`runs/validation/commit-split-20261107/`, are absent from the current checkout.
The old documentation-recovery ZIP under
`runs/validation/docs-review-20261107/` is also absent. Retained summaries do
not make those retired files available or prove future exact-code conformance.

## Falcor CGNS and six-view configuration

The November 11 CGNS plan proposed a separately fingerprinted overlay on pinned
Falcor, initially with point reservoirs and unpaired spatial reuse. Its constraints
were consistent neighbor selection across spatial stages, a dedicated random
stream, retained native rejection/shift/merge/normalization, and explicit handling
of unsupported configurations. Candidate deduplication, background handling and
other differences from the author's Falcor 8 code must be documented. Clamp probes
must not alter the reference. That original task list did not itself establish
implementation or GPU validation; the method guide distinguishes subsequently
validated variants.

The November 15 suite design reused six fixed views/references and shared transport
and method settings. It separated quality and timing processes, retained immutable
configuration/reference/source/runtime snapshots, and preserved completed attempts.
Timing explicitly drains the delayed final timestamp without relabelling the
measured frame. Historical default measurement behavior remains readable.

An approved update replaced the initial single quality seed with four independent
offsets (0, 100000, 200000, 300000), keeping timing at offset 0. It required a fresh
batch rather than modifying the prepared single-seed batch. The retained protocol
uses 40 warmup frames, quality frames 41–56, GPU timing frames 41–104 and drain
frame 105: 96 quality and 24 timing executions, yielding 1536 quality EXRs.
The four labels are temporal-off, temporal-on, cgns and pdf; detailed settings,
seed schedules, metrics and commands live in the six-view guide.

Historical pre-run validation reported 41 targeted CPU checks and 48 generated
scripts compiled for the single-seed design; the four-seed update reported 71
targeted checks and 120 scripts compiled. Six view/reference bindings were checked
without rendering. These configuration checks were not experiment results; the
stage subsequently completed.

## Archive decisions and availability

The completed stage is an immutable collection, not a resumable batch.
Its current paths come from `runs/pt-6-views-spatial-compare/manifest.json`.
Original capture manifests remain byte-identical and can name removed paths;
relocation and cleanup inventories distinguish current availability from origin.

Retain all 1536 quality EXRs, four seeds per method/view, six final 16384-spp
references and one 8192-spp checkpoint per view with generation records.
Intermediate 1024-spp blocks were retired, so their reconstruction and
block-based uncertainty recalculation are unavailable. Archival did not recompute
quality metrics.

Timing selection uses the latest Veach Ajar recheck and original timings for the
other eligible views. Emerald timing is excluded from performance aggregates and
equal-time claims while its images remain eligible for quality analysis.
Across-run instability was observed; VRAM pressure was a hypothesis, not an
established cause. Timing inclusion flags are explicit, and nested cache/selection
events must not be added again to parent spatial time.

The post-migration archive verification recorded 2514 files, 96 quality captures,
1536 EXRs, six final references, six checkpoints and 24 timing captures, 20 included.
The archival work reported 14 CPU regressions, six-view input checks, nine migration
checks, scaffold/link checks and independent provenance review; approximately
7.70 GiB was retired. Its retained receipt is
`runs/pt-6-views-spatial-compare/provenance/verification.json`.
No renderer, commit or push was part of archival.

## Capture and runtime maintenance

The November 16 maintenance retained method mathematics and experiment defaults
while consolidating capture lifecycle, input validation and neutral runtime helpers.
New batches are constrained to `runs/pt-fixed-view-batches/`; the frozen stage
archive and nested archive copies are rejected. Pre-launch, argument and telemetry
failures preserve failed attempt/job records across restart and require explicit
numbered retry. Quality capture, measurement and suite execution share the
deployment-shader guard. Public campaign compatibility helpers remain available.

Current schema-2 runtime fingerprints include shared helper dependencies and
verify retained host sources. Historical schema-1/2 packages can be inspected
against an externally recorded receipt hash, but inspection cannot authorize
current-code rendering, rewrite receipts or resign old packages. Changed source
identity requires a newly verified private package.

Read-only capture/archive adapters expose shared saved-run records with seed,
full-history, timing-inclusion and path/hash evidence. Independent seeds remain
distinct from correlated frames. Raw timing samples remain the full archive
verifier's responsibility. Cached-shader consumer checks belong to the source
test group. Three retired single-seed workflow scripts and their audit-only test
dependency were removed after source backup; maintained operation uses the
six-view guide.

## Validation provenance: 2026-11-16

The retained [maintenance receipt](../../build/pt-maintenance-20261116/verification.json)
records checks against the maintenance worktree, after independent review found and
fixed a batch-preparation variable-shadowing regression.

| Check | Recorded result |
| --- | --- |
| CPU / source / native suites | 1079 / 21 / 29 tests passed; source/native had no skips |
| Final capture/campaign modules | 45 tests passed after correcting a test-module namespace |
| Scaffold and formatting | 40 required paths, 288 local Markdown links; diff/added-line whitespace checks passed |
| Six-view read-only check | All six views and reference bindings verified |
| Full archive integrity | 2514 files hashed; 96 captures, 1536 EXRs, six final references, six checkpoints; 24 timing captures, 20 included |
| Actual adapter decoding | Classroom temporal-on seeds 0/100000: 32 EXRs hashed/decoded, 56 controls per capture, two compatible independent sequences |
| All archive selection metadata | Collector controls/repeat compatibility checked for all 24 view/method groups and 96 realizations; no HDR decode in that check |
| Historical runtimes | Four trusted reference/glTF CGNS/PDF snapshots verified and correctly rejected as current implementations |

The receipt also records an unchanged initial HEAD/index, clean upstream,
unchanged archive manifest/verification receipt/reference-catalog hashes, and
unchanged experiment, result, scene and algorithm sources relative to the initial
dirty tree. These statements describe that maintenance verification, not every
later documentation edit.

Evidence under `build/pt-maintenance-20261116/` includes individual logs,
`runtime-snapshots.json`, `real-reader.json`, `scope-verification.json` and
`final-review.md`, plus source backup and patch records. The failed collection
command remains in `capture-final.log`; `capture-final-corrected.log` records
the passing 45-test run, followed by the complete CPU suite.

This maintenance ran no renderer/GPU job, runtime build, quality-metric
recomputation, formal experiment, trajectory or video. Windows/media-specific
integration groups were not rerun. Historical packages were not resigned, and no
commit or push was made. Archive integrity and selected HDR decoding do not
establish fresh quality results or current-runtime render validity.
