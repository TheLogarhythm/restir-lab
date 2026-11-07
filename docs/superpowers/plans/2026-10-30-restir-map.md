# ReSTIR works map implementation

Initial scope (2026-10-30): implement the supplied Connected Papers-inspired research explorer locally; do not commit, push, enable Pages, or publish. Work in the existing checkout, preserving unrelated renderer/analysis changes.

Update (2026-10-31): the user authorized scoped commits on `restir-research-map` and pushing that branch to GitHub. Do not commit to `main` or enable/publish GitHub Pages. Preserve unrelated working-tree changes.

1. Read AGENTS.md and inspect Git, existing literature matrix, PDFs and provenance. Capture the starting dirty paths. Inspect the actual Connected Papers page and its list/detail interaction.
2. In parallel, verify early and recent papers against publisher/author/institution sources, reuse existing PDF bytes and extracted text, and record source/version/hash for additions. Review full-text passages for inheritance and reference entries for citations. Retain uncertainties as pending.
3. Build a React/TypeScript/Vite explorer in `web/restir-map`: 25% list, compact SVG graph, persistent detail panel, coordinated search/filter/selection, independent layout, directional evidence-backed edges, hash sharing, keyboard and reduced motion. First exercise ten real papers, then expand.
4. Consolidate research into authoritative `docs/literature/restir-map/papers.json` and `relations.json`. Keep the reading matrix as a synchronized bibliographic projection with its reading/reproduction state preserved. Record exclusions and search limits separately.
5. Write dependency-free Python data validation and meaningful negative tests: unique IDs/versions, endpoint and direction correctness, evidence requirements, matrix drift, public links, independent layout. Add a standalone web CI workflow with manual, opt-in Pages deployment only.
6. Run scaffold/data/unit/build checks, exercise the actual site in Chrome at desktop and narrow widths, test hash refresh under `/restir-lab/`, and inspect labels/arrows/focus behavior.
7. A fresh reviewer checks evidence, implementation, usability, and maintenance/deployment. Fix material findings, rerun affected checks, deliver local preview and exact publish instructions.

Implementation decisions: static data has no runtime literature API, Zotero or local-PDF dependency. SVG fits this small curated network and exposes keyboard-focusable nodes without a heavy graph engine. Directions and roles are editorial categories, not quality scores. Graph position never changes paper metadata. Publication evidence and relationship evidence are separate.

Baseline (2026-10-30): ordinary sandbox Git inspection failed; approved read-only host inspection confirmed branch `main` and existing unrelated modifications in README, CGNS renderer integration, shared/static analysis and tests. These are outside this task. The initial reference graph loaded in Chrome; list selection changed its detail pane. Its similarity links and duplicate records are not imported as evidence.
