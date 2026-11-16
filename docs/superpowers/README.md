# Decision and validation notes

These three notes consolidate the former plans, design spec and validation ledger.
They retain architectural choices, experiment boundaries and dated validation
provenance. They are not pending task lists or authorization to render.

| Note | Scope |
| --- | --- |
| [Backend and shared analysis](backend-and-analysis.md) | Repository isolation, saved-result contracts, glTF adaptation, script maintenance and the research map |
| [Spatial-reuse comparison](spatial-reuse-comparison.md) | RTXDI comparison decisions and validation; Falcor configuration, archive and maintenance history |

Use [shared analysis](../shared-analysis.md) and the
[Falcor integration guide](../../renderers/falcor/README.md) for maintained interfaces.
Method definitions and experiment operation belong in the reproduction guides:
[RTXDI spatial reuse](../reproductions/spatial-reuse.md),
[RTXDI CGNS](../reproductions/cgns.md),
[RTXDI PDF Similarity](../reproductions/pdf-similarity.md),
[Falcor CGNS](../reproductions/falcor-cgns-pt.md),
[Falcor PDF-guided PT](../reproductions/falcor-pdf-pt.md), and the
[six-view stage](../reproductions/pt-6-views-spatial-compare.md).

Dated test counts describe the worktree checked at that time. Historical integrity,
new analysis and current-code rendering require different evidence. Some original
log locations are no longer present and are identified as such; retained receipts
do not recreate retired images, reference blocks or runtime authorization.

The source documents as found before this consolidation are backed up locally in
`build/docs-consolidation-20261116/source-before.zip`.
