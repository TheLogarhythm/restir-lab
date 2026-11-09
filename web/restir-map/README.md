# ReSTIR Explorer

A local, static research explorer built with React, TypeScript and Vite. Paper data is maintained separately from the interface. Visitors do not need PDFs, a GPU, Zotero or a live literature API.

The public interface and all paper summaries, evidence explanations and source notes are written in English. Keep new user-facing copy in natural English, including accessibility labels. The compact header shows `ReSTIR Explorer (44 papers)` with the count derived from the full dataset, unaffected by filtering. The inline Tabler Prism Light SVG is attributed in About; its full MIT license ships in `public/licenses/`. The sidebar begins with search; the graph begins with relationship-mode controls.

## Running locally

Use Node.js 22.12 or later within the 22.x series, 24.x, or 26 and later, as required by the pinned test dependencies. Node 24 is recommended to match CI. From the repository root, run:

```powershell
cd web/restir-map
npm ci
npm run dev
```

Open the address printed in the terminal, normally `http://127.0.0.1:5173/restir-lab/`.

```powershell
npm test
npm run build
npm run preview
```

The production preview normally runs at `http://127.0.0.1:4173/restir-lab/`. Build output goes to the ignored `build/web/restir-map/` directory. All dependencies are pinned in `package-lock.json`. Installing the web dependencies does not initialize renderer submodules.

## Using the explorer

- Search matches titles, short titles, authors, research questions, venues and research-area keywords. Multiple search terms must all match. Research area, year and publication-type filters affect both the collection and the network.
- Paper details remain open. ReSTIR DI is selected by default; a valid `#paper=paper_id` takes precedence, while a missing or invalid ID falls back to DI. Selecting a node, collection entry or related paper updates the reading content and share state without moving the graph view.
- The default Method lineage view shows verified technical inheritance. All connections combines inheritance and citation edges for the same pair of papers, while retaining both kinds of evidence in the details. Citations only shows citation edges separately.
- Arrows point from earlier work to later work that cites or builds on it. Color represents the primary research area, and shape represents the editorial classification. Paper details list all tags.
- The initial view includes the full dataset. Drag the background to pan, drag nodes to rearrange them, and use the mouse wheel or a two-finger pinch to zoom. Center fits the visible nodes to the canvas while preserving dragged positions, filters and the selected paper. There are no Reset or zoom buttons. Selection, filters, connection modes and legend actions do not reset the manual view. Zoomed-out views avoid overlapping labels while retaining every node; hovered or focused nodes receive label priority.
- The selected paper is stored in `#paper=paper_id`. Share copies the current link. Refresh, Back and Forward restore the selection.
- Press `/` to focus search, Tab to move between controls, and Enter or Space to select a node. With the graph focused, use arrow keys to pan and `+` / `-` to zoom. Esc closes a modal without clearing the selected paper. Modals contain keyboard focus and return it to the trigger when closed.
- On narrow screens, the collection becomes a horizontal card list. On tablets and narrow screens, details appear below the network. Selecting a paper does not automatically scroll the page. There is no continuous animation, and the interface respects `prefers-reduced-motion`.

### Arrow interaction and desktop reading width

Hovering a method-lineage or citation arrow darkens and thickens both its line and arrowhead over a short transition. Keyboard focus provides the same emphasis; Enter or Space opens the connection evidence. Hovering does not change the selected paper. Citation lines retain their dashes, and each arrow has a 12px hit area that stays the same screen width while zooming. `prefers-reduced-motion: reduce` disables the transitions.

Above 1000px, the paper-details panel matches the actual width of the left collection sidebar (about one quarter of the page). A `ResizeObserver` keeps the widths aligned after resizing. This replaces the earlier 420px target and 90% cap. At 1000px and below, the existing stacked tablet/mobile details layout remains. The collection eyebrow and graph introduction/count block are removed, leaving the map directly below its controls.

### Node size and highlight legend

`graph/nodeMetrics.ts` counts distinct neighbors in the full dataset using only verified `inheritance` relations, in both directions. Duplicate edges and a neighbor appearing on both sides count once; citations, pending relations and self-edges do not contribute. Counts are independent of filters, selection and edge mode. Small/medium/large nodes use fixed thresholds (0–2, 3–7, 8+ neighbors), not a ranking of quality or influence. Mainline rings and role shapes remain separate from size.

Direction and classification legend buttons use `aria-pressed` and toggle a single highlight. Direction matching uses every tag on a paper. They dim nonmatching nodes and list entries without hiding, reordering or refitting. If the current paper matches the chosen group, it stays selected; otherwise the details open that group's editorial reading entry. Activate the same button again to clear the highlight and keep the current paper. Explicitly selecting an outside paper through the graph, list or related work clears the highlight; selecting another matching paper retains it. Back/Forward also clears an incompatible highlight. The filled selected node remains visually distinct. Keyboard: Tab to a legend button, then Enter/Space.

### Default reading entries

`src/data/readingEntries.ts` stores stable paper IDs for the six directions and four classifications. These are editorial starting points, not graph roots, prerequisites or quality rankings. A zero in-degree can reflect a different research direction or incomplete verified connections, so it does not determine the reading entry. The choices below use the existing paper summaries and membership tags; they introduce no new scholarly claims or relations.

| Direction or classification | Entry | Reason |
| --- | --- | --- |
| Foundations | ReSTIR DI (`restir_di2020`) | Introduces spatiotemporal reservoir reuse. |
| Reuse quality | Production ReSTIR (`production2021`) | Early treatment of candidate generation, visibility reuse and rendering cost. |
| Cameras & motion | Area ReSTIR (`area2024`) | Introduces camera-domain sampling for subpixel detail and depth of field. |
| Light transport | ReSTIR GI (`restir_gi2021`) | Connects direct-light reuse to multi-bounce indirect paths. |
| Estimator extensions | Inverse-rendering ReSTIR (`inverse2023`) | Early concrete extension to differential samples in inverse rendering. |
| Learning & implementation | ReSTIR Course (`course2023`) | Educational synthesis of theory, algorithms and implementation. |
| Mainline | ReSTIR DI (`restir_di2020`) | Starts with the original ReSTIR method. |
| Branch | Volumetric ReSTIR (`volume2021`) | Early extension into participating media. |
| Optimization | Production ReSTIR (`production2021`) | Improves the original method's execution and reuse costs. |
| Resource | ReSTIR Course (`course2023`) | Broad introduction that connects the individual works. |

Entries are selected from the full collection, independently of search filters and connection mode. Legend activation preserves filters and the map's exact view and node positions. If filters hide the entry, the existing selected-paper notice offers to reveal it. Only explicit paper selection retains the existing behavior of clearing filters when necessary. A reduced collection without the curated entry falls back to its earliest matching paper (year, then stable ID); an empty group preserves the selection. No fallback changes the source array.

When adding a direction or classification, choose an entry that actually belongs to it, update this table, and update the real-data entry cases in `tests/app.test.tsx`. Tests enforce facet coverage, existing IDs and membership, and exercise every entry through the rendered app, including share links and unchanged map transforms. `tests/selection.test.ts` covers reduced and empty collections.

### Representative figures

The details gallery contains 68 WebP images for 43 of the 44 entries, with one or two verified paper figures or project teasers per available entry. `mis_weight2024` has no verified publicly accessible figure and shows an explicit unavailable reason.

Select an image to open an accessible enlarged view. Captions, source links with figure/page locators, and credits remain available in the gallery and enlarged view. If a preview cannot load, the gallery offers a link to the source. Image URLs use Vite's `BASE_URL`, including the default `/restir-lab/` Pages subpath.

### ReSTIR DI pipeline

The ReSTIR DI overview includes a compact English SVG flowchart in an accessible modal. Three equal-width stages cover initial RIS, temporal reuse and spatial reuse, with visibility decisions, historical and neighboring reservoir inputs, a spatial reuse loop, final shading and feedback to the next frame. Candidate weights use mathematical subscripts and a hat accent.

The diagram fits within a desktop dialog and supports horizontal scrolling on narrow screens. It follows the original 2020 paper at a conceptual level; implementation-specific validity checks and estimator bias correction are not expanded. A source link opens the original paper.

## Structure and maintenance

The authoritative research content is maintained in the [paper dataset](../../docs/literature/restir-map/papers.json), [relationship evidence](../../docs/literature/restir-map/relations.json) and [collection documentation](../../docs/literature/restir-map/README.md). The frontend imports these files at build time through `src/data/load.ts`. It does not duplicate bibliography data or query a live API. Local PDF caches are excluded from the build.

Components in `src/components/` handle the collection, SVG network, nodes, paper details, relationship evidence, controls and accessible modals. `AboutDialog` and `ConnectionDialog` manage their respective content, `RelationEvidence` shares evidence rendering between details and dialogs, and `App` coordinates reading state and component interactions. `src/graph/selection.ts` handles filtering, verified-edge merging and share behavior. Research-area and classification types in `data/types.ts` enforce complete default reading-entry coverage. Layout coordinates are maintained separately in `src/graph/layout.json`; add coordinates for new nodes. Dragging updates browser memory only and never changes paper tags or relationships.

`graph/useGraphGestures.ts` owns drag/pinch tracking, outside releases, cancellation and pointer-capture cleanup; `PaperGraph` owns rendering, viewport sizing and explicit navigation. Delayed pointer capture preserves ordinary node/edge clicks. New collection entries receive coordinates synchronously without resetting the view or existing dragged positions.

Reading a related paper transfers keyboard focus to its heading with `preventScroll`. Graph, list and legend selections retain their normal focus behavior. Sharing canonicalizes the selected-paper URL before the asynchronous clipboard request, so a delayed rejection cannot overwrite a newer selection. Clearing filters reveals the selected list row by scrolling only the list container. The literature `--sync-matrix` command rejects duplicate IDs before writing, preserving ambiguous reading notes for manual resolution.

The network uses native SVG for its roughly 40 nodes. This avoids a graph runtime or continuous force-directed simulation, keeps nodes and edges directly inspectable and keyboard-accessible, reproduces the same layout, and keeps the build small. The fixed layout avoids rearranging the network on each visit, while nodes remain draggable. Long short titles may use display abbreviations in the graph; full bibliographic details remain in the reading panel.

`tests/selection.test.ts` covers combined filters, inheritance/citation merging, directions and share state. `tests/app.test.tsx` exercises React workflows: collection/graph coordination, keyboard navigation, sharing, deep-link restoration, filtering, evidence expansion and modal focus. Recheck actual panning, zooming, dragging and breakpoint layouts in a browser after updates; unit tests do not replace browser inspection.

Figure metadata has its own [figures.json manifest](../../docs/literature/restir-map/figures.json), separate from bibliography and relationship evidence. Its `paper_id` records cover every entry and either contain one or two images or declare `status: "unavailable"`, an empty `images` array, and a `reason`. Each image maintains `id`, `src`, `alt`, `caption`, `source_url`, `source_locator`, `credit`, `source_kind` (`paper_figure` or `project_teaser`), `sha256`, `width`, and `height`.

The selected images in `public/figures/` are bundled static assets. Full PDFs are not republished; raw source PDFs and working crops stay under ignored `assets/`. When replacing an image, update its metadata, dimensions, and SHA-256 together. `scripts/check_literature.py` validates manifest coverage, image hashes, public source URLs, safe local asset paths, and required attribution. `tests/figures.test.tsx` covers the gallery, enlarged view, source fallback, unavailable state, and Pages base path; the selection and app tests also cover panel-width boundaries and edge keyboard activation.

## Preparing for GitHub Pages

The default Vite `base` is `/restir-lab/`. For a different repository name, a root-domain deployment or a custom deployment path, set `VITE_BASE_PATH`. For example, in PowerShell:

```powershell
$env:VITE_BASE_PATH = '/another-repository/'
npm run build
```

Use hash-based selection rather than path routing so GitHub Pages can refresh deep links without server rewrites. Vite's base path handles static assets and the favicon.

The repository's [dedicated web workflow](../../.github/workflows/restir-map.yml) provides validation and publication preparation separately from renderer CI. Before publication, obtain explicit authorization in the current session for commits/pushes and deployment. After authorization, select only the relevant files for the commit, set Settings → Pages → Source to GitHub Actions, and manually enable deployment as described by the workflow. On 2026-10-31, the user authorized committing and pushing this work to `restir-research-map`; `main` is excluded. Enabling Pages and publishing the site still require separate authorization.

After authorization:

1. Commit and push only the relevant literature, web, validation-test and workflow files. Preserve unrelated working-tree changes and exclude `assets/`, `node_modules` and build directories.
2. Select GitHub Actions under repository Settings → Pages, then open Actions → **ReSTIR literature map** → Run workflow.
3. Confirm `base_path` is `/restir-lab/`, enable `deploy` and run the workflow. Only this explicit manual run publishes the site. Ordinary pushes and pull requests run checks and retain downloadable build artifacts.
4. Open the Pages URL returned by the deployment job. Check the home page, refresh `#paper=gris2022`, and verify JavaScript, CSS and the favicon. If the repository name or site path changes, update `base_path` before rebuilding.

See Vite's [official static deployment guide](https://vite.dev/guide/static-deploy.html#github-pages) for project-path deployment requirements.

## Branch and publication boundary

On 2026-10-31, the user authorized review, fixes, and scoped commits/pushes to `restir-research-map` after validation. Preserve unrelated working-tree changes. This authorization does not include merging into `main`, enabling GitHub Pages, or publishing the site; those remain separate actions requiring authorization.
