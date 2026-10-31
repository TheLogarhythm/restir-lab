# ReSTIR Atlas

本地静态研究探索网页。React + TypeScript + Vite；论文数据与界面分离，访问者无需 PDF、GPU、Zotero 或实时文献 API。

The public interface and all paper summaries, evidence explanations and source notes are written in English. Keep new user-facing copy in natural English, including accessibility labels. The header contains the ReSTIR Atlas brand without a tagline; the sidebar and graph have no status footer rows.

## 本地运行

需要 Node.js 22.12 或更新版本（本次验证使用 Node 24）。从仓库根目录运行：

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
- 节点或目录悬停突出相关论文；点击保持选中，打开可持续阅读的详情。图与列表双向同步。
- 默认显示已核验技术继承；“全部关系”合并同一对论文的继承与引用，详情保留两类证据；“仅引用”单独展示引用。
- 箭头从前作指向引用或继承它的后续论文。颜色对应主要研究方向，形状对应编辑分类；详情列出全部标签。
- 拖动空白平移、拖动节点整理布局、滚轮或按钮缩放。“重置视图”恢复节点初始坐标并适配可见论文。缩小概览时自动避让文字，保留全部节点；当前悬停或聚焦节点优先显示标签，放大后显示全部标签。
- 选中状态保存在 `#paper=paper_id`。分享按钮复制当前链接；浏览器刷新、前进与后退均可恢复选择。
- `/` 聚焦搜索，Tab 遍历可操作元素，Enter/空格选中节点。图区域聚焦后方向键平移，`+` / `-` 缩放。Esc 关闭模态或清除选择。模态限制焦点，关闭后返回原触发控件。
- 窄屏目录改为水平卡片列表，平板与窄屏详情排在网络下方；选中新论文时自动定位到阅读面板，无滚动动画。无持续动画，并遵循 `prefers-reduced-motion`。

### Arrow interaction and desktop reading width

Hovering a method-lineage or citation arrow darkens and thickens both its line and arrowhead over a short transition. Keyboard focus provides the same emphasis; Enter or Space opens the connection evidence. Hovering does not change the selected paper. Citation lines retain their dashes, and each arrow has a 12px hit area that stays the same screen width while zooming. `prefers-reduced-motion: reduce` disables the transitions.

Above 1000px, the paper-details panel matches the actual width of the left collection sidebar (about one quarter of the page). A `ResizeObserver` keeps the widths aligned after resizing. This replaces the earlier 420px target and 90% cap. At 1000px and below, the existing stacked tablet/mobile details layout remains. The collection eyebrow and graph introduction/count block are removed, leaving the map directly below its controls.

### Representative figures

The details gallery contains 68 WebP images for 43 of the 44 entries, with one or two verified paper figures or project teasers per available entry. `mis_weight2024` has no verified publicly accessible figure and shows an explicit unavailable reason.

Select an image to open an accessible enlarged view. Captions, source links with figure/page locators, and credits remain available in the gallery and enlarged view. If a preview cannot load, the gallery offers a link to the source. Image URLs use Vite's `BASE_URL`, including the default `/restir-lab/` Pages subpath.

## 结构与维护

权威研究内容位于 [论文数据](../../docs/literature/restir-map/papers.json)、[关系证据](../../docs/literature/restir-map/relations.json) 和 [收录说明](../../docs/literature/restir-map/README.md)。前端通过 `src/data/load.ts` 在构建时导入，不复制书目，不请求实时 API；本机 PDF 缓存不进入构建。

`src/components/` 分别负责目录、SVG 网络、节点、论文详情、关系证据、控制和可访问模态；`src/graph/selection.ts` 维护筛选、已核验关系合并和分享语义。布局是独立的 `src/graph/layout.json`；新增节点应添加坐标，拖动仅修改浏览器内存，绝不修改论文标签或关系。

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
