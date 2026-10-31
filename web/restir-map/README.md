# ReSTIR Atlas

本地静态研究探索网页。React + TypeScript + Vite；论文数据与界面分离，访问者无需 PDF、GPU、Zotero 或实时文献 API。

The public interface and all paper summaries, evidence explanations and source notes are written in English. Keep new user-facing copy in natural English, including accessibility labels. The compact header shows `ReSTIR Atlas (44 papers)` with the count derived from the full dataset, unaffected by filtering. The inline Tabler Prism Light SVG is attributed in About; its full MIT license ships in `public/licenses/`. The sidebar begins with search; the graph begins with relationship-mode controls.

## 本地运行

需要 Node.js 22.12+（22.x）、24.x 或 26+，与锁定的测试依赖兼容；建议使用 CI 同款 Node 24。从仓库根目录运行：

```powershell
cd web/restir-map
npm ci
npm run dev
```

访问终端显示的地址，默认 `http://127.0.0.1:5173/restir-lab/`。

```powershell
npm test
npm run build
npm run preview
```

生产预览默认 `http://127.0.0.1:4173/restir-lab/`；生成目录是忽略的 `build/web/restir-map/`。所有依赖锁定在 `package-lock.json`。只需安装网页依赖，不会初始化 renderer submodule。

## 使用

- 左侧搜索支持题名、简称、作者、研究问题、venue 和方向关键词，多个词取交集；方向、年份和发表状态筛选同时影响目录和网络。
- 详情常驻；默认选择 ReSTIR DI，有效 `#paper=paper_id` 优先，缺失或无效参数回退到 DI。节点、目录和关联论文点击只更新阅读内容及分享状态，不移动视图。
- 默认显示已核验技术继承；“全部关系”合并同一对论文的继承与引用，详情保留两类证据；“仅引用”单独展示引用。
- 箭头从前作指向引用或继承它的后续论文。颜色对应主要研究方向，形状对应编辑分类；详情列出全部标签。
- 初始视图展示完整数据集。拖动空白平移、拖动节点整理布局，滚轮或双指捏合缩放。角落的 Center 按钮只将当前可见节点适配画布，保留拖动坐标、筛选和当前论文；没有 Reset 或缩放按钮。选择、筛选、关系模式和图例操作均不自动恢复手动视图。缩小概览时自动避让文字，保留全部节点；悬停或聚焦节点优先显示标签。
- 选中状态保存在 `#paper=paper_id`。分享按钮复制当前链接；浏览器刷新、前进与后退均可恢复选择。
- `/` 聚焦搜索，Tab 遍历可操作元素，Enter/空格选中节点。图区域聚焦后方向键平移，`+` / `-` 缩放。Esc 只关闭模态，不清空当前论文。模态限制焦点，关闭后返回原触发控件。
- 窄屏目录改为水平卡片列表，平板与窄屏详情排在网络下方；选择论文不自动滚动页面。无持续动画，并遵循 `prefers-reduced-motion`。

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

## 结构与维护

权威研究内容位于 [论文数据](../../docs/literature/restir-map/papers.json)、[关系证据](../../docs/literature/restir-map/relations.json) 和 [收录说明](../../docs/literature/restir-map/README.md)。前端通过 `src/data/load.ts` 在构建时导入，不复制书目，不请求实时 API；本机 PDF 缓存不进入构建。

`src/components/` 分别负责目录、SVG 网络、节点、论文详情、关系证据、控制和可访问模态。`AboutDialog` 和 `ConnectionDialog` 管理各自的展示内容，`RelationEvidence` 统一详情与弹窗的证据显示，`App` 负责阅读状态和组件联动。`src/graph/selection.ts` 维护筛选、已核验关系合并和分享语义；`data/types.ts` 的方向与分类类型约束默认阅读入口的完整性。布局是独立的 `src/graph/layout.json`；新增节点应添加坐标，拖动仅修改浏览器内存，绝不修改论文标签或关系。

`graph/useGraphGestures.ts` owns drag/pinch tracking, outside releases, cancellation and pointer-capture cleanup; `PaperGraph` owns rendering, viewport sizing and explicit navigation. Delayed pointer capture preserves ordinary node/edge clicks. New collection entries receive coordinates synchronously without resetting the view or existing dragged positions.

Reading a related paper transfers keyboard focus to its heading with `preventScroll`. Graph, list and legend selections retain their normal focus behavior. Sharing canonicalizes the selected-paper URL before the asynchronous clipboard request, so a delayed rejection cannot overwrite a newer selection. Clearing filters reveals the selected list row by scrolling only the list container. The literature `--sync-matrix` command rejects duplicate IDs before writing, preserving ambiguous reading notes for manual resolution.

约 40 个节点采用原生 SVG：无需图形运行时或持续力导向计算，节点和连线可直接检查，键盘可操作，重现同一布局，产物较小。固定布局避免每次打开都重新排列；节点可自由拖动。图上长简称可以显示排版用缩写，完整书目信息仍见详情。

`tests/selection.test.ts` 验证组合筛选、继承与引用合并、方向和分享状态；`tests/app.test.tsx` 验证真实 React 流程：列表/图联动、键盘、分享、深链接恢复、筛选、证据展开和模态焦点。浏览器中的实际平移、缩放、拖拽与断点布局需在更新后复查，单元测试不代替浏览器检查。

Figure metadata has its own [figures.json manifest](../../docs/literature/restir-map/figures.json), separate from bibliography and relationship evidence. Its `paper_id` records cover every entry and either contain one or two images or declare `status: "unavailable"`, an empty `images` array, and a `reason`. Each image maintains `id`, `src`, `alt`, `caption`, `source_url`, `source_locator`, `credit`, `source_kind` (`paper_figure` or `project_teaser`), `sha256`, `width`, and `height`.

The selected images in `public/figures/` are bundled static assets. Full PDFs are not republished; raw source PDFs and working crops stay under ignored `assets/`. When replacing an image, update its metadata, dimensions, and SHA-256 together. `scripts/check_literature.py` validates manifest coverage, image hashes, public source URLs, safe local asset paths, and required attribution. `tests/figures.test.tsx` covers the gallery, enlarged view, source fallback, unavailable state, and Pages base path; the selection and app tests also cover panel-width boundaries and edge keyboard activation.

## GitHub Pages 准备

默认 Vite `base` 为 `/restir-lab/`。其他仓库名、根域名或自定义部署路径应设置 `VITE_BASE_PATH`，例如 PowerShell：

```powershell
$env:VITE_BASE_PATH = '/another-repository/'
npm run build
```

不要使用路径路由；hash 选择状态让 GitHub Pages 刷新深链接无需服务器重写。静态资源、favicon 均由 Vite 的 base 处理。

仓库的 [独立网页工作流](../../.github/workflows/restir-map.yml) 提供校验和发布准备，与 renderer CI 分离。实际发布前，需用户在当前会话明确授权提交/推送及发布；授权后只选择本次文件提交，设置仓库 Settings → Pages → Source 为 GitHub Actions，再按工作流说明手动启用发布选项。2026-10-31 用户已授权将此次工作提交并推送到 `restir-research-map` 分支；`main` 不接收本次提交。Pages 启用和实际发布仍需另行授权。

获得授权后的操作：

1. 仅提交并推送此次文献、网页、校验测试及工作流文件；保留无关工作区改动，不提交 `assets/`、`node_modules` 或构建目录。
2. 在仓库 Settings → Pages 选择 GitHub Actions；进入 Actions → **ReSTIR literature map** → Run workflow。
3. 确认 `base_path` 为 `/restir-lab/`，勾选 `deploy` 后运行。只有这次显式手动运行会发布；普通 push/PR 仅检查并保存可下载构建产物。
4. 打开部署任务返回的 Pages 地址，检查首页、`#paper=gris2022` 刷新及 JS/CSS/favicon。若仓库名或站点路径变化，先调整 `base_path` 再构建。

Vite 的项目路径部署要求见 [官方静态部署说明](https://vite.dev/guide/static-deploy.html#github-pages)。

## Branch and publication boundary

On 2026-10-31, the user authorized review, fixes, and scoped commits/pushes to `restir-research-map` after validation. Preserve unrelated working-tree changes. This authorization does not include merging into `main`, enabling GitHub Pages, or publishing the site; those remain separate actions requiring authorization.
