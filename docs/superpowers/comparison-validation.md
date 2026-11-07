# Comparison validation record

Supersedes the uncommitted execution ledger and pending-work lists. This is a
local audit summary, not a new scientific experiment or a rendering authorization.

- Historical campaign `cgns-di-gi-pt-20261106` has 30 method entries and ten
  references. Its original state is awaiting_ui; it predates later transport fixes.
- Post-debug 64×64 saved GI/PT captures and reference ancestry were revalidated.
  Native-off pixels and uninterrupted/resumed reference images matched exactly.
- Refactor regression compared 20 view/group cases: SMAPE, masks, error/delta
  arrays, timing and neighbors were exact. Legacy DI displayed improvement has
  at most 1.98e-14 pp reduction-order rounding, with no sign changes.
- Fresh independent review found and resolved configuration validation bypasses,
  input digest rebinding, GI/PT timing fields and historical reference pairing.
- Before the three code commits: 676 CPU/workflow, 23 native and eight Windows
  tests passed, plus scaffold. Isolated staged snapshots checked DI (19 tests),
  transport (23) and comparison config/metrics/plan (21).
- The user viewed and accepted the latest report. Machine receipts still record
  ui_verified=false; no historical receipt/state was changed to infer UI status.

Evidence: `runs/validation/comparison-refactor-20261106-2337/` and
`runs/validation/commit-split-20261107/`. Three code commits are 864400e, 47c8a55
and d7e6b6f. No push or new formal rendering occurred. These are local historical
records; current exact-code conformance must be established for a future run.
