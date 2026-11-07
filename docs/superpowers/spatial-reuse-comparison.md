# Spatial-reuse comparison decisions

Consolidates the November 6 experiment design, implementation plan and comparison
unification plan. Archived originals remain in the local documentation recovery ZIP.

- Compare original versus CGNS within DI/GI/PT. Use one build per pair; GI/PT's
  CGNS toggle changes their indirect spatial pass only. Keep rejection and do
  not replenish rejected neighbors.
- Reuse verified DI captures explicitly. Direct reference matches the historical
  DI target; GI/PT share direct plus one indirect bounce. Use ordinary PT with
  8192 paths/pixel, seed 1001 and 4096/8192 checkpoints.
- One schema separates algorithm, reuse, static protocol, view, frame, seed,
  reference and input reuse. Config validity and approved-budget gates differ.
- Configuration/collection, process lifecycle, numerical analysis, display and
  verification have distinct responsibilities. Legacy schemas adapt at the
  reader boundary; they do not retain a second pipeline.
- Freeze actual inputs and sources. Historical integrity, new reanalysis and
  current-code rendering are distinct operations. Never refresh old receipts
  silently or accept an archive as authorization for new rendering.
- Keep frame and seed axes separate. Future motion requires frame-specific
  geometry/reference and temporal statistics; static masks cannot establish it.

Use the [workflow](../comparison.md) and
[study note](../reproductions/spatial-reuse.md) as the maintained user documentation.
