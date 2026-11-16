# 六个固定视角的 ReSTIR PT 历史比较

2026-11-16 归档整理：本页保留 2026-11-14 单 seed 比较的历史表格。旧 `runs/falcor-pt-three-methods-20261114` 及其图像、HTML、逐帧指标、耗时与清单已退役并移除；下表未在本次整理中重算或重新验证。当前四方法、四 seed 的原始数据与计时取舍见[六视角比较记录](../../../docs/reproductions/pt-6-views-spatial-compare.md)。

本次使用相同的固定相机、10-bounce transport、seed 日程、1920×1080、1 spp/frame 和 40 帧 warmup，在 temporal on 下比较 ordinary spatial reuse、CGNS 与 PDF Similarity。复用已核验的 ordinary/CGNS temporal-on 图像及 ordinary temporal-off 图像，共 144 张 HDR。新增 48 张 PDF HDR，并为旧 ordinary/CGNS 补采原生 GPU 耗时。

旧报告与原始产物已移除，不再提供失效链接。

CGNS 在六个视角的 SMAPE 均降低，相对下降 4.26%–23.29%，测得 GPU frame time 增加 17.70%–52.98%。PDF 的相对 SMAPE 在 Bistro exterior、Classroom、Zero Day Measure Seven 分别降低 1.94%、0.79%、1.75%；Bistro interior 几乎相同。在 Emerald Square 和 Veach Ajar 分别上升 5.27% 和 0.14%。PDF 的测得帧耗时增加 12.81%–43.01%。

Emerald Square 的 PDF initial sampling 为 138.00 ms，高于其 temporal 的 69.12 ms 和 spatial 的 48.49 ms。CGNS 在该视角的 spatial 为 133.69 ms，其中 workload 为 63.19 ms、retrace 为 14.00 ms、merge 为 56.49 ms。父阶段包含子阶段，二者不可重复相加。Visibility 的独立耗时记为 N/A，其工作计入 tracing/retrace。

SMAPE 先对每个单帧的全图 scene-linear luminance 计算，再对 8 帧等权平均。公式为 100×mean(|Y−Yref|/(|Y|+|Yref|+1e−4))，luminance 系数为 (0.2126,0.7152,0.0722)，使用相同的 16384-spp reference。GPU frame time 来自 inclusive onFrameRender timestamp，排除加载、编译和 EXR 导出。原生 profiler 延迟一帧返回，所以 GPU 耗时统一使用第 41–47 帧，图像指标使用第 41–48 帧。每种方法只运行一条 seed 序列，这些相关帧属于描述性比较。

Emerald Square 的第一个 PDF attempt 因 DXGI_ERROR_DEVICE_REMOVED 退出；同一配置的第二个 attempt 成功。相关旧目录和日志现已移除。失败的底层原因尚未进一步定位。没有修改算法或采集预算来恢复该运行。

旧原始数据已经移除，不能从原 run 路径重新计算本页历史结果。当前六视角数据需按其档案清单选择正确的 quality 与 timing 来源。

完整数据表如下。


1920×1080, 1 spp/frame, 40 warmup frames. SMAPE uses frames 41–48; GPU timings use frames 41–47.
Single seed stream per method. At the time, retained baseline/CGNS HDR and ordinary temporal-off HDR were reused; those old method images have since been removed.

| Scene | Ordinary SMAPE % | CGNS SMAPE % | PDF SMAPE % | Ordinary GPU ms | CGNS GPU ms | PDF GPU ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bistro interior | 28.1460 | 25.3451 | 28.1447 | 39.2796 | 54.2211 | 46.3512 |
| Bistro exterior | 16.7101 | 15.1329 | 16.3856 | 44.0449 | 67.3808 | 49.6858 |
| Classroom | 17.4142 | 16.0721 | 17.2773 | 35.9864 | 49.6968 | 43.3834 |
| Emerald Square | 25.8681 | 19.8437 | 27.2310 | 189.8933 | 277.6314 | 271.5721 |
| Veach Ajar | 16.8276 | 15.9473 | 16.8514 | 24.4108 | 28.7310 | 30.1275 |
| Zero Day Measure Seven | 19.1881 | 18.3709 | 18.8522 | 71.5222 | 92.9482 | 83.8442 |

## GPU stages

| Scene | Method | Initial ms | Temporal ms | Spatial ms | Spatial workload ms | Spatial retrace ms | Spatial merge ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bistro interior | baseline | 15.0471 | 9.8354 | 11.2086 | 0.7342 | 1.3764 | 9.0974 |
| Bistro interior | cgns | 15.4892 | 9.6468 | 25.9359 | 3.5151 | 2.7556 | 19.6634 |
| Bistro interior | pdf-similarity | 16.0949 | 12.1170 | 13.1375 | 1.2039 | 1.3746 | 10.5574 |
| Bistro exterior | baseline | 15.7411 | 12.6793 | 12.2074 | 0.9247 | 0.5372 | 10.7441 |
| Bistro exterior | cgns | 15.8296 | 12.4140 | 35.7527 | 5.7224 | 1.1874 | 28.8418 |
| Bistro exterior | pdf-similarity | 16.9867 | 14.9441 | 13.4940 | 1.1763 | 0.5588 | 11.7571 |
| Classroom | baseline | 15.7183 | 8.8396 | 8.7733 | 0.8252 | 0.5582 | 7.3889 |
| Classroom | cgns | 14.4659 | 8.1006 | 24.4041 | 3.7692 | 1.6810 | 18.9528 |
| Classroom | pdf-similarity | 16.4005 | 12.2128 | 10.9703 | 1.2965 | 0.6122 | 9.0605 |
| Emerald Square | baseline | 93.1117 | 48.8449 | 29.8878 | 0.9516 | 2.4613 | 26.4738 |
| Emerald Square | cgns | 75.9988 | 50.4585 | 133.6864 | 63.1903 | 14.0001 | 56.4950 |
| Emerald Square | pdf-similarity | 137.9986 | 69.1237 | 48.4949 | 1.2377 | 3.9629 | 43.2931 |
| Veach Ajar | baseline | 8.1866 | 6.5830 | 7.3138 | 0.7368 | 0.7143 | 5.8623 |
| Veach Ajar | cgns | 8.6036 | 7.0521 | 10.5220 | 1.0145 | 1.0696 | 8.4364 |
| Veach Ajar | pdf-similarity | 8.5634 | 9.1756 | 9.5193 | 1.0894 | 0.7200 | 7.7087 |
| Zero Day Measure Seven | baseline | 41.0127 | 13.4359 | 14.2813 | 0.7481 | 4.2802 | 9.2520 |
| Zero Day Measure Seven | cgns | 44.0177 | 14.0782 | 32.1257 | 3.8203 | 8.4242 | 19.8786 |
| Zero Day Measure Seven | pdf-similarity | 45.4301 | 17.8202 | 16.8117 | 1.3365 | 4.8116 | 10.6632 |

## Historical ordinary temporal-off results

| Scene | Temporal-off SMAPE % | Temporal-on SMAPE % |
| --- | ---: | ---: |
| Bistro interior | 79.8753 | 28.1460 |
| Bistro exterior | 77.3396 | 16.7101 |
| Classroom | 85.0624 | 17.4142 |
| Emerald Square | 58.8715 | 25.8681 |
| Veach Ajar | 96.1728 | 16.8276 |
| Zero Day Measure Seven | 73.6028 | 19.1881 |

## Historical failed attempt

- jobs/emerald-square/view-a/pdf-similarity/attempt-001/manifest.json — Renderer failed with exit code 1

GPU frame time is the inclusive native onFrameRender timestamp. Initial sampling is tracePass.
Temporal and spatial parent timings include their workload, retrace and merge children.
Visibility/shadow work is integrated into tracing; an isolated visibility duration is unavailable.
Loading, shader compilation and export wall time are recorded independently in each manifest.

Detailed per-frame quality, raw event timings and provenance were recorded in metrics.json, summary.csv and stages.csv; these retired files are no longer available from the former run directory.
