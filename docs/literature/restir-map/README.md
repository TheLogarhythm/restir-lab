# ReSTIR Atlas 数据

Atlas 收录 ReSTIR 及相关研究，区分正式论文和辅助资料。每条关系都附原文依据。箭头由前作指向后作，`citation` 表示可核实的引用，`inheritance` 表示正文明确采用或扩展前作方法。待核实关系保留为 `pending`，不进入图谱。

| 文件 | 内容 |
| --- | --- |
| [papers.json](papers.json) | 书目、公开来源、发表状态和核验范围。 |
| [relations.json](relations.json) | 引用、方法继承、方向和证据定位。 |
| [figures.json](figures.json) | 图像路径、说明、署名、来源、尺寸和 SHA-256。 |
| [audit.json](audit.json) | 检索范围、纳入取舍和证据缺口。 |
| [reading-matrix.csv](../reading-matrix.csv) | 书目索引、阅读状态和复现状态。 |

新增论文时使用稳定的 `paper_id`，按原文记录关系定位和解释。图像放在 Atlas 的 `public/figures/`，同步更新图像来源、署名、尺寸和哈希。网页链接公开论文来源。

书目字段变更后，运行 `python -B scripts/check_literature.py --sync-matrix` 同步矩阵。同步保留已有阅读和复现状态。检查命令与发布入口见 [验证说明](validation.md) 和 [Atlas 网页 README](../../../web/restir-map/README.md)。
