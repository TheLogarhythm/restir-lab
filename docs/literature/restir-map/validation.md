# 本地验证与独立评审 · 2026-10-30

本文件按修订记录当时的实现、验证和发布边界；下方早期章节中的未提交说明仅对应当时的修订。文献检索截止为香港时间 2026-10-30，后续界面验证日期见各节。

## Code review and branch delivery · 2026-10-31

The user authorized reviewed Atlas commits and a push to `restir-research-map`, without merging `main` or publishing Pages. Three independent review passes covered graph geometry/gestures, reading state/accessibility, and data/build/maintenance. Cross-review of the fixes found and resolved an asynchronous sharing race; no substantive findings remain from these passes.

Fixed issues:

- Releasing a pointer outside the SVG, losing capture, canceling a pinch or switching windows could leave stale gesture state. `graph/useGraphGestures.ts` now owns interruption and capture cleanup. Regressions cover mouse/touch taps, StrictMode keyboard selection, child-to-SVG capture transfer and genuine SVG capture loss.
- Adding a paper through updated component props could read undefined coordinates before an effect ran. Positions are now available synchronously while preserving dragged nodes and the manual view.
- Reading related work could leave keyboard focus on the document body or the old edge. Details now receive focus on their heading without scrolling the page or map.
- A failed clipboard request could leave the address bar pointing at an invalid default-paper hash. Canonicalizing the share URL before awaiting clipboard access also prevents delayed rejection from overwriting a later selection.
- Clearing filters could restore a selected list row outside the list viewport. The row is now revealed inside the list when results change.
- `--sync-matrix` could silently retain only the last duplicate CSV row, losing reading/reproduction notes. Duplicate IDs now fail before any write; valid metadata synchronization retains workflow fields.

Organization: About and connection dialogs are separate components; evidence rendering is shared. Direction/classification types and complete reading-entry maps catch missing configuration during compilation. Package engine metadata now matches the pinned test stack (Node 22.12+ within 22.x, 24.x, or 26+); no dependency versions changed. The existing `THIRD_PARTY.md` bytes are preserved, with only the MIT icon notice appended. Historical provenance records were not rewritten.

Fresh checks: 94 frontend tests across six files; TypeScript/Vite production build; 18 literature tests; literature validation (44 entries, 130 verified relations); scaffold validation (40 required paths and 182 Markdown links); patch whitespace check. No tests were skipped or weakened. New failure regressions were observed failing before their fixes.

The production preview was checked in the real in-app browser at 1440×960, 1100×850 and 390×844. Equal desktop panel widths (345.59px / 270px), stacked mobile details, all 44 nodes, deep-link refresh, legend entry selection, background and node dragging, Center preserving dragged positions, related-paper and dialog focus handoff, image Escape/focus return, and no horizontal overflow were verified. Mobile related-paper activation preserved both scrollY (810px in the exercised state) and the exact SVG transform. Browser logs contained no warnings or errors. Pointer cancellation/capture-transfer edge cases are automated event regressions; no physical touchscreen test is claimed.

Research metadata, relationship evidence, representative images and saved layout coordinates are unchanged. All unrelated dirty files are protected by a fresh hash baseline. Validation uses no renderer submodules, GPU, local PDFs or Zotero.

## Legend reading entries · 2026-10-31

This revision supersedes the earlier rule that legend highlights never change the selected paper. A matching current paper stays selected, including matches through secondary direction tags. Otherwise the legend opens its curated reading entry. Toggling off keeps the paper. Explicitly choosing an outside paper, or restoring one through browser history, clears an incompatible highlight. Legend activation preserves search filters, node positions and the camera; a hidden entry uses the existing filter notice. All six directions and four classifications have explicit entries in `web/restir-map/src/data/readingEntries.ts`, with rationale in the web README. These are editorial navigation choices, not inferred graph roots or changes to scholarly evidence.

Fresh validation: 76 frontend tests passed, including all ten entries through the rendered app, copied share URLs, secondary-tag membership, keyboard toggles, all three manual selection paths, browser-history reconciliation, filter preservation, and exact map transforms after pan/zoom. Configuration checks validate the actual mapping's keys, IDs and membership; reduced-collection fallback is deterministic and does not mutate the source array. The 16 literature tests, literature validator, scaffold check and TypeScript/Vite production build passed. No checks were skipped or relaxed.

Real in-app-browser checks used the production preview at `/restir-lab/`, at 1440×960, 1100×850 and 390×844. Reuse quality opens Production ReSTIR; switching to Foundations retains it through its matching tag; toggling off retains the same paper. Keyboard selection opens Area ReSTIR, explicit list selection clears an incompatible highlight, Branch opens Volumetric ReSTIR, and Back/Forward restore paper selection without moving the view. Refreshing the Volumetric share hash preserves the paper and starts with all 44 nodes fitted. The resource facet opens/retains the course. Search remains intact when the chosen entry is outside the results. Desktop panels remain equal (270px each at 1100px); mobile details remain stacked without horizontal overflow. Image loading and Escape focus return passed; browser logs contained no errors or warnings. This revision adds no animation or gesture logic.

Independent read-only review found no substantive implementation defect. Its suggested mapping-integrity test was added and the full frontend suite/build were rerun successfully. All pre-existing changes outside the scoped frontend/documentation files were hash-checked against a fresh baseline; research metadata, evidence, figures and saved layout coordinates remain unchanged. HEAD remains `960f1c6`; no commit, push, merge or Pages publication was performed.

## Persistent reading and stable-map revision · 2026-10-31

This local-only revision keeps details open, defaults to ReSTIR DI for absent/invalid paper hashes, and gives valid share links priority. Escape closes dialogs only. The 52px header uses the full dataset count and the licensed inline Tabler Prism Light icon. The sidebar heading, graph introduction/hints, zoom toolbar and Reset/Clear controls are removed.

Node radii are 18/22/26 world units for 0–2/3–7/8+ distinct verified inheritance neighbors in the full dataset. Citations and pending relations never affect size. Legend buttons match all direction tags or editorial roles without hiding nodes or changing the selected paper, layout or view. Initial fitting waits for actual canvas dimensions and includes all papers. Only explicit Center fits the currently visible, potentially dragged positions; selection, filtering, mode changes and later resize preserve the view.

Independent review caught two issues that were fixed: list auto-scrolling could move the entire mobile page, and expanded transparent hit circles could capture neighboring marker centers. List scrolling is now confined to its own container; hit radii are bounded by nearest visible neighbors and decorative rings do not intercept input. The old panel entrance animation was removed to prevent transient overflow during persistent content changes.

Validation: 57 frontend tests passed, covering fallback/default/deep-link selection, modal/selection separation, stable views through selection and legend/filter changes, distinct-neighbor counting, size tiers, pinch gestures, Center preserving dragged positions, and real-layout mobile hit geometry. Literature tests (16), literature validation and scaffold checks passed; TypeScript/Vite build passed. Independent review found no remaining substantive defects.

Real in-app-browser checks at 1440×960, 1100×850 and 390×844 confirmed equal desktop side panels, stacked mobile details, loaded representative images, no settled horizontal overflow, and all initial node shapes inside the canvas. Paper and secondary-tag legend selection preserve the exact SVG view transform. Keyboard pan/zoom, real pointer background/node dragging, Center, valid share refresh, invalid-hash fallback and image/Escape focus return were exercised. Direct mobile marker taps select ReGIR and World-space correctly without changing page scroll or camera transform. Locator-driven test scrolling was distinguished from actual screen-coordinate taps. Reduced motion was verified by stylesheet rules; no OS preference was changed. Two-finger pinch is covered by pointer-event tests, not a physical touchscreen test.

No new commit, push, merge or Pages publication was performed. Existing branch commits, the 40 unrelated working-tree files, literature metadata/evidence and representative images remain intact.

## Layout simplification · 2026-10-31

Removed the collection eyebrow and the entire graph introduction/count block, including its reserved height and obsolete styles. The network retains a screen-reader heading. Above 1000px, details now match the measured left-sidebar width, replacing the earlier 420px target, 90% cap and width floors; tablet/mobile details remain stacked. The obsolete mobile minimum height was removed to avoid unused space after deleting the introduction.

Fresh validation: 31 frontend tests, TypeScript/Vite build, literature validation and scaffold checks passed. Independent code review found no remaining issues. Chrome measured equal left/right widths of 614.40px at a 2560px viewport and 345.59px at 1440px. The graph toolbar begins at the header's lower edge (76px), reclaiming the former introduction area. Closing/reopening details works; 800px and 390px layouts remain stacked without horizontal overflow, and representative images load. All 40 unrelated baseline files remain unchanged. No commit, push or publication.

## English interface update · 2026-10-30

Applied user feedback: the interface, all 44 paper entries and all 134 relationship records now use English prose. Removed the header tagline/divider, sidebar classification footer and graph status footer. The narrow-screen filters now use two rows so English labels remain readable. IDs, bibliography, URLs, evidence status, graph endpoints and layout coordinates are unchanged. The Blue-noise source note now explicitly reflects its existing abstract-only evidence status.

Validation: 13 frontend tests, 12 literature tests, the literature validator, scaffold checks and the production build passed. No Han characters remain in the interface or the two public data files. Chrome checks at 1440×960 and 390×844 covered the removed elements, English controls, search/list selection, paper details, evidence, sources, About dialog and horizontal overflow. Independent copy/semantic review passed after correcting JSX spacing, singular result wording and bibliographic terminology. No commit, push or deployment was performed.

## Arrow, figure gallery and reading-panel update · 2026-10-30

Method and citation arrows now darken and thicken on pointer hover or keyboard focus, including their arrowheads. Citation dashes remain visible. Their hit targets keep a constant screen width during zoom, and the transitions respect reduced motion. Clicking or pressing Enter/Space opens the existing evidence viewer without changing the selected paper.

The separate `figures.json` manifest covers all 44 entries: 43 have one or two representative images, for a total of 68 attributed WebP assets (9,243,268 bytes). The Novel MIS Weight entry remains explicitly unavailable: no suitable public figure could be retrieved and verified. Images come from actual paper figures or public project teasers; they are not generated illustrations. Each has a source URL and locator, credit, English caption/alt text, dimensions and SHA-256. Raw source material stays in ignored `assets/`; the small static derivatives are bundled under the site's `public/figures/`. This does not change bibliographic or relationship verification status.

The independent reviewer inspected image provenance, decoding/hashes, gallery code, keyboard behavior and width logic. Visual crop checks led to corrections for the course diagram, Object Space, MCMC, DDGI, Volumetric ReSTIR and GRIS; a misleading Blue-noise alt description and ambiguous gallery numbering were also corrected. A final GRIS check confirmed the complete last row, formulas and bottom border. No blocking review findings remain. This review is not a new full-text audit of every paper or relation.

Final automated results: **31 frontend tests and 16 literature tests passed**, along with the literature validator, required scaffold checks, TypeScript and the production Vite build. All 68 images returned HTTP 200 under `/restir-lab/figures/` and matched their manifest hashes. Tests cover figure provenance, complete/unique coverage, safe paths, missing assets, hash drift, image failure fallback, base-path loading, enlargement/focus return, arrow evidence actions and sizing limits. All 40 unrelated baseline files still match their initial hashes.

Chrome production-preview checks confirmed:

- At 2560px, details are 420px wide; at 1920px, the measured 460.79px list yields a 414.71px details panel; at 1440px, the previous 335px floor prevents the 90% cap from narrowing the panel.
- At 1280px and 1200px, the existing 335px and 300px widths remain. The 800px and 390px stacked layouts have no horizontal overflow.
- Real pointer hover on method and citation edges changes line and arrowhead to the darker color and a 3px line; citation dashes remain `4px 4px`. Keyboard activation opens evidence.
- The mobile gallery and enlarged-image dialog load the corrected GRIS image at its actual 1500×468 dimensions. The dialog stays within the viewport; Escape closes it and restores focus to the image button. The `/` shortcut cannot escape the modal.
- The isolated final preview has no captured console warnings or errors. Reduced-motion behavior was checked in CSS, not by changing the operating-system preference.

No commit, push, Pages activation or publication was performed.

## 数据与检查

- 44 项：39 正式研究，5 项分别标记类型的辅助/摘要资源；134 条关系中 130 已核验、4 待核验。
- 87 条已核验引用、43 条已核验技术继承。全关系视图合并同对论文的两类记录，不叠画双线；待核验记录不参与图。
- `python -B scripts/check_literature.py --check-local-pdfs`：通过；35 份本地 PDF 的实际 SHA-256 与记录一致。
- `python -B -m unittest tests.workflows.test_literature_data -v`：12/12 通过。覆盖身份/版本去重、端点、自环、重复关系、引用方向、继承证据、跨版本年份、公开链接、矩阵状态保留、无效字段及完整/有限/互异布局坐标。
- `python -B scripts/check_scaffold.py`：通过，保留原有检查规则，未删除或跳过检查。
- 网页 `npm test`：13/13 通过，含筛选与联动、证据展开、hash、拖后重新定位、窗口变化不重放缩放、模态焦点、低缩放标签优先级、窄屏标签留白和缩小方向等回归。
- `npm run build`：TypeScript 与 Vite 构建通过；产物位于忽略的 `build/web/restir-map/`。
- 网页 CI 只安装 Node/Python 及网页依赖，不初始化 renderer submodule，不需要 GPU、论文 PDF 或 Zotero。

## 真实浏览器

先用 10 篇真实论文的明确标识原型检查列表/网络/持续详情，再加载完整 44 项并检查生产产物。

| 场景 | 观察结果 |
| --- | --- |
| 桌面 1440×960 | 44 节点全部加载；默认 43 条继承边；逐对检查节点标签矩形无相互重叠。修正了 Novel MIS Weight 与 Multi-layer Splatting 的初始标签碰撞。 |
| 800px 平板 | 详情位于网络下方，不覆盖选中节点；无横向溢出。 |
| 390×844 手机 | 水平目录、堆叠网络/详情；选中或打开论文深链接后定位阅读区；无横向溢出。总览保留 44 节点并避让显示 10 个标签，无标签碰撞或边缘裁切；键盘聚焦可唤出隐藏标签，选中放大后恢复全部 44 个标签。 |
| 搜索/筛选 | 2026 + 复用质量同时得到 5 项列表与 5 个节点；不存在的词得到 0 项及明确空状态；重置恢复全部。 |
| 节点与列表 | 鼠标悬停显示简介并突出相邻边，既有选中详情保持；Enter 选中同步列表、图及 URL。 |
| 拖拽/缩放/平移 | 真实拖动改变节点坐标；鼠标空白拖动与方向键平移有效；按钮和滚轮缩放有效；重置恢复初始布局。 |
| 窄屏缩小 | 总览点击“−”后比例从 0.17153 降至 0.14294，未反向放大；相应回归测试先在旧实现上失败，再验证修复。 |
| 完整关系模式 | 全量数据的“全部关系”为 88 组去重边，“仅引用”为 87 条；默认技术脉络为 43 条。 |
| 拖后重新选中 | 切换到其他论文再重新选择拖动节点，节点中心与图中心的差异小于 1 CSS px，未回到旧坐标。 |
| 证据 | 展开同对论文分别看到正文继承解释和参考文献定位、检查日期、公开来源链接。 |
| 分享与历史 | 分享按钮复制包含 `/restir-lab/#paper=...` 的 URL；刷新、后退、前进均恢复正确选择。 |
| 模态键盘 | 打开后焦点进入对话框；Shift+Tab/Tab 闭环；`/` 不逃逸到背景搜索；Esc 关闭并返回触发按钮。 |
| 子路径资源 | 生产 HTML、JS、CSS、favicon 均以 `/restir-lab/` 加载，HTTP 200；hash 深链接不依赖服务器路由重写。 |

动画检查：节点没有持续 animation；构建 CSS 的 `prefers-reduced-motion: reduce` 规则禁用动画、过渡和滚动动画。浏览器当时系统偏好为 `no-preference`，未更改系统设置或模拟另一偏好，不能把静态规则检查声称为真实 OS 模拟。浏览器日志中的一条早期开发 HMR effect-dependency 警告来自修改中的 5173 原型，生产预览没有该错误。

## 独立复审

由未参与实现的 reviewer agent 分两轮只读检查代码、资料和维护/部署配置；它未操作浏览器，视觉结论来自主 agent 的实际浏览器检查。复审不是全部关系的第二次全文通读。

风险优先抽查包括 PDF Similarity/MCMC 的 2022 预印本与 2024 正式版、CGNS、ToF、RGB、Guided FG+、Gradient、LoD、Ghost、Blue-noise、Shape Splatting，以及最后补齐的 Sample-Space Filtering、Visibility Reuse、Tiled Reservoirs、Object Space、Multi-viewer、Light Subpath。核查正文/References、作者或出版方记录，确认未把“相关工作”或“未来工作”误当继承。

已修复：拖动后按旧坐标居中、resize 重放缩放、平板详情覆盖、模态 `/` 焦点逃逸、遗漏 RGB 代码入口；Shape Splatting 的解释明确限定为离线 ReSTIR PT 上组合图像贡献 splatting。最后一轮增量复审另发现窄屏适配比例低于旧缩放下限时，“缩小”反向放大；统一缩放函数与下限后，独立回归 7/7 和 TypeScript 检查通过。复审及增量复审均未留下阻塞性发现。

## 限制与工作区边界

本地 PDF 尚缺：Tiled Reservoirs、Light Subpath、Multi-viewer、ReSTIR FG、Novel MIS Weight、Sample-Space Filtering、Shape Splatting、Blue-noise、Guided FG+。其中有公开全文文本/索引的工作仍可核验特定关系；只依据摘要/公开引言的条目在 `verification` 中说明。下载残片不列作可用 PDF。候选清单中的六项直接相关工作已补查结案；范围仍是有说明的 curated map，不宣称穷尽整个领域或全部引文。

未运行 renderer/GPU 实验、未改 runs/冻结记录，也未将无关 CPU/renderer 测试的状态当成本次结果。未执行远程 GitHub Actions 或实际 Pages 部署。

起始 40 项无关未提交文件已逐文件记录并复核 SHA-256，一致。它们包括根 README、CGNS 集成与测试、共享/静态分析脚本、相关设计记录及实验配置。原有 33 条阅读矩阵的阅读状态、复现状态、笔记路径保持；本次新增条目为 `not_started`。本次只在文献目录、独立网页目录、数据校验/测试、独立工作流及实施计划内写入源码。`assets/`、构建输出和 `node_modules` 仍受 Git 忽略。
