# 本地验证与独立评审 · 2026-10-30

本次只实现本地网页与发布准备。未 commit、push、启用 Pages 或实际发布。真实浏览器为 Chrome；检索截止和验证日期均为香港时间 2026-10-30。

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
