# PDF Similarity：实验查看与进展汇报

平时只需打开两个页面：

| 用途 | 入口 |
| --- | --- |
| 查看视频、原图、误差图、ROI 和三种子统计 | [comparison.html](comparison.html) |
| 播放 Marp 幻灯片并录制汇报 | [progress.html](progress.html) |

## 视频对照

四组实验各保留 PDF off、PDF on、自动斜线对比三个视频。每个视频为 1920×1080、96 帧、30 FPS，共 3.2 秒，无音轨。两路画面完全重叠；左侧显示 PDF on，右侧显示 PDF off，分界线从左下斜向右上 /。独立对比视频自动从全 off 扫到全 on。

在对照页中可以播放、暂停、慢放、循环、逐帧选择和全屏；直接拖动画面上的斜线，或用下方滑块调整位置。分界线把手也支持方向键、Home 和 End。页面只显示配对成功的同一帧；等待解码时保留上一对完整画面。

视频采用 H.264 CRF 20 编码，是有损展示素材。需要观察噪声和细节时，暂停并点击“检查原始 PNG”；两侧同步读取同一帧的未改动 PNG。原图仍采用实验原有的显示变换，不能替代线性 HDR 误差分析。

自动对比视频：[Arcade](assets/videos/arcade-motion/comparison.mp4) · [Bistro 内景](assets/videos/bistro-interior-motion/comparison.mp4) · [Bistro 外景](assets/videos/bistro-exterior-motion/comparison.mp4) · [Bistro 变光](assets/videos/bistro-lighting/comparison.mp4)。

## 文件放在哪里

- assets/：幻灯片选图、论文 Figure 2 摘图、一个演示封面帧，以及 12 个视频。媒体不进入 Git。
- data/：总览 CSV、字段说明、来源与场景索引、视频生成记录、验证及整理清单。
- [source/progress.md](source/progress.md)：唯一的幻灯片、逐页口播和排练计时源稿。
- source/ 中的 HTML/CSS/JS：实验查看页模板和交互代码。
- tools/：生成和验证工具。

完整实验展示图、误差图、逐帧 PNG 和原始统计保留在 [pdf-similarity-archive](../../runs/pdf-similarity-archive/README.md)。对照页通过相对路径读取这些文件，不复制整个实验目录。新增场景的完整图库保留在 [scene-gallery](../../runs/scene-gallery/README.md)，本目录只保留汇报选图。使用完整对照页时，保持当前仓库目录关系。

正式统计、参考政策和观察范围见 [实验报告](../../results/summaries/pdf-similarity/README.md)。图片为 seed 1，数值为 seeds 1/2/3；Cornell/Arcade 的五个参考状态保留原精度验收，Bistro 的十个参考状态精度未评估。局部时域指标只覆盖 31→32、47→48、95→96。统计值在本次整理中保持不变。

## 修改与生成

修改 Marp 源稿后，从仓库根目录运行：

~~~powershell
.\writing\progress\tools\build.ps1
~~~

默认只生成两个 HTML；需要本机 Python、Node.js 和 Marp CLI 4.5.1。选图缺失时会从来源索引恢复。论文 Figure 2 缺失时，使用 Poppler 的 pdftoppm 从本地论文第 3 页重新截取；原文哈希、裁剪参数和署名见 [paper-figure.json](data/paper-figure.json)。首次生成视频或重新生成已变更的媒体，需要本机 FFmpeg：

~~~powershell
.\writing\progress\tools\build.ps1 -Media
python -B writing/progress/tools/verify.py --media --write
~~~

-PreviewImages 可按需生成十一张检查图，-Notes 可导出口播备注；它们放在被 Git 忽略的 build/，可以删除。默认不生成 PDF 或 PPTX。HTML 输出和媒体同样被忽略，Git 保留源稿、模板、脚本和小型数据索引。

页面无需联网，可以直接用近期 Chrome 或 Edge 打开。验证脚本检查所有来源哈希、图片组合与链接、十一页幻灯片、视频帧数和同步控制逻辑。浏览器工具拒绝本次 file:// 访问，因此记录中的浏览器实机交互检查仍标为未验证。

## 录制

十一页稿件的排练目标为 **3:30（210 秒）**，前三页回顾共 65 秒。英文口播稿共 354 词，已按 humanizer 指引改写；每页备注给出时间段和简短操作提示。第六页预留 28 秒，包含视频播放和观察对照。第四页用 Tokuyoshi (2023) 的 Figure 2 解释 PDF Similarity：明暗像素的目标方向分布不同，用 vMF 波瓣近似后比较方向和集中程度，减少不合适的复用。第六页播放 Bistro 外景斜线对比视频，也可以打开交互对照页，慢放后停在第 48 帧拖动比较。第七页汇总三个静态场景的 off/on 图片、SMAPE 定义及质量/耗时表；第八页展示室内 spatial-only 退化，并把原因保留为待验证假设。第十页介绍 CGNS 集成和受控失败案例测试；第十一页单独致谢。演示使用保存的渲染输出；播放速度不代表 GPU 性能。口播与计时在源稿备注中统一维护，实际时长需排练。较长的来源与科学范围说明保存在 [speaker-note-sources.json](data/speaker-note-sources.json)，不混入口播提示。

课程要求来自 [GitHub issue 3](https://github.com/TheLogarhythm/restir-lab/issues/3)，此前核对于 2026-10-22：总时长 3:30–4:00，开头用 60–90 秒回顾项目，展示实现，说明已完成与剩余编程工作；于 2026-10-25 23:59（香港时间）向 Canvas 提交 progress.mp4。本目录没有代为录制或提交最终视频。

场景许可和来源保留在 [场景索引](data/scenes.json) 与 [THIRD_PARTY.md](../../THIRD_PARTY.md)。六个新增场景的 OIDN 图片用于介绍场景配置进展，不参与本轮受控 PDF 比较。
