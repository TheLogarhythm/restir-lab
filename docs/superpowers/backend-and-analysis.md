# Backend and shared-analysis decisions

Consolidates the uncommitted Falcor integration, shared-analysis and flat-layout
plans from October 28–30. Original notes are preserved in the ignored
`runs/validation/docs-review-20261107/before.zip` recovery archive.

- Falcor 9.0 remains an independent pinned upstream backend. Its bounded smoke
  runs establish environment operation; they do not certify RTXDI-equivalent
  lighting, independent trials, GPU timing or a converged reference.
- Shared packages live directly under `src/`: metrics, image_io, records,
  analysis and backends. Pure metrics do not import renderer/process code.
- Backend readers normalize immutable saved captures and retain provenance,
  full control/RNG schedules and explicit capability limits. Missing historical
  metadata does not become evidence of equivalence or independence.
- Tests are grouped into core, backends, workflows, assets and fixtures, with
  CPU/native/Windows/media groups. Test registration must preserve discovery
  failures and required integration checks.

Current interfaces and use are documented in
[shared analysis](../shared-analysis.md) and the
[Falcor guide](../../renderers/falcor/README.md). The older committed Falcor design
and other committed historical plans remain unchanged.
