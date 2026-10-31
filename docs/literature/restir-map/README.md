# ReSTIR works · 文献与关系数据

检索截止日期：**2026-10-30**。这是依据公开来源逐段审读建立的研究导航，不是自动计算的论文相似性图，也不是完整引文数据库。审读由本次 agent 完成；不代表用户本人已经阅读，也不替代领域专家复核。

当前收录 **44 项**：39 项正式研究（包含正式短论文及会议论文集文章），以及分别标识的书章、技术报告、课程、会议报告和海报摘要各 1 项。已核验关系共 **130 条：87 条引用、43 条技术继承**；另有 4 条继承待核验，不进入网络。审计与候选取舍见 [audit.json](audit.json)，验证及独立评审见 [validation.md](validation.md)。

35 项拥有已校验 SHA-256 的本地 PDF；9 项本地 PDF 缺失，详见审计记录。缺少本地 PDF 不一定缺少全文证据：部分工作可通过出版方公开文本或作者 PDF 索引核查。FG、Novel MIS Weight、Blue-noise、Sample-Space Filtering 的继承保持待核验。Light Subpath、Multi-viewer 等仅有摘要/公开引言资料的条目明确标记覆盖范围，不补造上游继承。

## 收录范围

以已正式发表、直接提出或扩展 ReSTIR 方法的研究为主体；保留理解重采样所必需的 RIS 基础。渠道包括 TOG、CGF、PACMCGIT、SIGGRAPH/SIGGRAPH Asia、EGSR、HPG、I3D、TVCG 及具有直接技术相关性的其他发表渠道。相关性由方法决定，不能仅按 venue 或标题是否含 ReSTIR 判断。

课程、书章、会议报告、技术报告、海报摘要、预印本分别使用 `publication_status` 标识；不冒充完整研究论文。补充材料和预印本/正式版归属于同一 `paper_id`。公开页面只链接权威主页和公开 PDF，不复制或发布本地论文。资源无已核验关系时独立显示，不能为了连通而补边。

`papers.json` 是书目信息的唯一维护源，`relations.json` 是关系及证据。候选取舍、检索范围与缺口记录在 `audit.json`；来源定位与检查日期存于各记录中。纳入并不等于质量评价，未纳入也不等于无关或低质量。检索受公开来源可访问性限制，不能声称穷尽全部文献。

## 方向、分类与证据

- `citation`：后作参考文献明确包含前作；证据定位到参考文献条目或正文引用。
- `inheritance`：后作正文明确采用、扩展、推广或改进前作方法；只有引用不能证明继承。
- `predecessor → successor` 是展示方向，即箭头指向后作。内部 `citing_paper = successor`、`cited_paper = predecessor`，校验器检查一致性。
- 同一对论文允许各有一条 citation 和 inheritance。默认只显示已核验继承；完整关系视图合并同对边，详情保留两类证据，避免重叠双线。`pending` 不进入网络。
- 章节/页码指向所列来源版本，不同排版页码可能不同。跨正式发表年份的引用须解释早期版本，不能根据年份自动推断关系。

角色是编辑分类：`mainline` 标记 RIS、DI、GI、GRIS/路径重采样与条件重采样等核心概念；`branch` 标记相机、传输目标或估计器扩展；`optimization` 标记候选/邻居选择、权重、相关性和代价改进；`resource` 标记辅助材料。它们不是引用量或质量排名。多方向 `tags` 可以并存，首标签仅决定默认视觉颜色与矩阵 `method_family`。

布局只放在 `web/restir-map/src/graph/layout.json`。拖动节点只改变浏览器内位置，不修改关系、分类或研究结论。

## Representative figure manifest

[figures.json](figures.json) is an independent display-asset manifest keyed by `paper_id`; it does not change the bibliography, relationship evidence, or verification status. It currently records 68 WebP images across 43 of the 44 entries, with one or two representative paper figures or project teasers for each available entry. `mis_weight2024` is explicitly unavailable because no publicly accessible figure has been verified.

Each record contains `paper_id`, `status`, and `images`. An unavailable record has an empty `images` array and a nonempty `reason`; keep retrieval notes when they explain the gap. Each image maintains:

- `id` and `src`: a unique image ID and safe relative asset path such as `figures/restir_di2020-fig1.webp`.
- `alt` and `caption`: an accessible image description and a concise explanation of the figure.
- `source_url`, `source_locator`, and `credit`: the public source, figure/page or project-page locator, and attribution.
- `source_kind`: `paper_figure` or `project_teaser`.
- `sha256`, `width`, and `height`: the bundled image's content hash and pixel dimensions.

Selected images live in `web/restir-map/public/figures/` and ship as static assets. Full PDFs are not republished. Raw source PDFs and working crops remain in ignored `assets/`; visitors do not need those local files. The frontend imports the manifest at build time, prefixes image paths with the deployment base path, and offers enlarged views with captions, source links, and credits. Failed previews link to the source, and unavailable records display their reason.

When adding or replacing a figure, inspect the source and crop, preserve the locator and credit, and update the asset hash and dimensions together. `scripts/check_literature.py` checks full coverage against `papers.json`, one or two images per available entry, explicit unavailable reasons, unique IDs and paths, required attribution, public source URLs, safe asset paths, file existence, and SHA-256 agreement. The Python literature tests exercise these validation rules; `web/restir-map/tests/figures.test.tsx` checks the gallery, enlargement, source fallback, unavailable state, and Pages subpath handling. These checks do not replace visual inspection or verification of the source attribution.

## Graph interaction and reading layout

Method-lineage and citation arrows darken and thicken on hover or keyboard focus, with their arrowheads changing to match. Citation dashes remain visible, and `prefers-reduced-motion` disables the transitions. Enter or Space opens the focused connection's evidence without changing the selected paper.

Above 1000px, the paper-details panel matches the actual width of the left collection sidebar (about one quarter of the page). A `ResizeObserver` keeps the widths aligned after resizing. This replaces the earlier 420px target and 90% cap. At 1000px and below, the existing stacked tablet/mobile details layout remains. The collection eyebrow and graph introduction/count block are removed, leaving the map directly below its controls.

## 更新方式

1. 核实作者/机构论文页和出版方记录，更新 `papers.json` 的作者、年份、发表状态、DOI、链接和日期；未知值明确为空并解释，不能猜测。
2. 先查 `assets/papers/catalog.csv` 与 `metadata/catalog.json`，复用现有 PDF/提取文本。新增文件沿用年份加题名命名，记录合法来源、版本、SHA-256；不同哈希版本不能无检查覆盖。`assets/` 持续忽略，CI 不要求 PDF 存在。
3. 核读正文，记录关系的来源 URL、章节/页码和解释。未解决判断留为 `pending`。不得自动升级用户阅读状态。
4. 执行 `python -B scripts/check_literature.py --sync-matrix`。它只从权威 JSON 同步书目字段，保留已有 `reading_status`、`reproduction_status` 和 `notes_path`；新记录状态为 `not_started`。
5. 执行 `python -B scripts/check_literature.py`、`python -B -m unittest tests.workflows.test_literature_data -v` 及 `python -B scripts/check_scaffold.py`。拥有本地 PDF 时可另用 `--check-local-pdfs` 核对哈希。
6. 网页目录执行 `npm test`、`npm run build`，真实浏览器检查新节点及关系。发布步骤见 [网页 README](../../../web/restir-map/README.md)。

校验可发现结构、版本、字段、方向、证据缺失和矩阵漂移；它**不能证明自然语言解释正确**，正文审读和独立评审不可省略。

## 视觉参考

本次在 Chrome 实际打开 [Connected Papers 的 ReSTIR GI 图](https://www.connectedpapers.com/main/2c1d7958ba83b2dac94164bbb5a204ba58ec73a1/ReSTIR-GI%3A-Path-Resampling-for-Real%E2%80%90Time-Path-Tracing/graph)，检查白底简约网络、左侧论文列表及点击后持续显示的右侧详情。原图以相似性组织，包含同一工作的不同索引版本；本项目不导入这些连线或重复节点。
