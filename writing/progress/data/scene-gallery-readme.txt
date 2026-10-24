# Scene Gallery

快速查看已配置 RTXDI 场景，并选取展示图片。[打开图库](index.html)。点击图片查看全分辨率，左侧为未降噪版，右侧为 OIDN 处理版。场景数、机位数和完成状态均从配置自动生成。

## 目录与职责

```text
scene-gallery/
├── gallery.json                 默认分辨率、渲染预算、OIDN 路径、冻结的实验定义
├── scenes/                      可编辑配置：每个场景一个 JSON
│   ├── cornell-box.json
│   └── ...
├── render.py                    统一命令入口、原生渲染与 PNG 后处理
├── gallery_tools/
│   ├── catalog.py               配置验证、场景发现、状态合并、变更检测
│   ├── site.py                  HTML 生成、图片和复现记录验证
│   └── page.html                简洁的静态页面模板与样式
├── tests/test_catalog.py        无需 GPU 的扩展与渲染流程检查
├── manifest.json                自动生成：配置快照、资源来源、完成状态、结果哈希
├── verification.json            最近一次完整性检查
├── index.html                   自动生成的图库，可直接打开
└── <scene-id>/
    ├── view-a/
    │   ├── raw.png
    │   ├── processed.png
    │   ├── config.json          该次渲染实际使用的原生配置，可在此目录复现
    │   ├── render-record.json   输入帧哈希、曝光、处理方式、时间、复现信息
    │   ├── renderer.log
    │   ├── timings.csv
    │   └── resolved.json
    └── view-b/
```

日常编辑 `gallery.json` 和 `scenes/*.json`。不要手改生成的 `manifest.json`、`index.html` 或历史 `render-record.json`。场景 ID 对应仓库注册项，机位 ID 在该场景内唯一；两者使用小写字母、数字与连字符。目录不使用日期，也不依赖固定场景数量。

`gallery.json` 的 `scene_order` 控制已有章节顺序。新增配置会自动发现并排在其后，想改变顺序时再把 ID 加入这个列表。每个场景默认两个机位，也支持继续增加机位。

## 添加一个新场景

以下命令从 **restir-lab 仓库根目录**运行。一次只运行一个原生渲染进程。

1. 先完成仓库级场景导入：资源来源和许可写入 `THIRD_PARTY.md`，注册到 `scenes/manifest.yaml`，配置 `scenes/configs/rtxdi/<scene-id>.json`。图库复用这些资源和验证接口，不复制模型或纹理。
2. 查看可用 ID，再创建图库配置。PowerShell 示例中的 ID 需要替换为真实注册项：

   ```powershell
   python -B runs/scene-gallery/render.py --list-scenes
   $sceneId = 'your-registered-scene-id'
   python -B runs/scene-gallery/render.py --add-scene $sceneId
   ```

   命令创建 `scenes/<scene-id>.json` 并更新图库，不覆盖已有配置。`view-a` 使用注册机位；`view-b.camera` 初始为 `null`，页面显示“待选择机位”，不会伪造第二张展示图。

3. 编辑新 JSON 的 `title`、`credit`、两个机位的 `title` 和 `camera`。相机格式如下，数值只是格式示例，需要按实际场景选择：

   ```json
   {
     "position": [0, 2, -8],
     "direction": [0, 0, 1],
     "up": [0, 1, 0],
     "vertical_fov": 60
   }
   ```

   `direction` 可用“目标点减相机位置”得到，`vertical_fov` 是垂直视角（度）。两个机位必须有不同位置，并选择明显不同的主体或朝向；只调整 FOV 不够。自动检查会拒绝位置重复、方向与 up 平行等错误，但构图仍需人工看图。

4. 先检查和试拍新场景，不影响其他场景的图片：

   ```powershell
   python -B runs/scene-gallery/render.py --check --scene $sceneId
   python -B runs/scene-gallery/render.py --scout --scene $sceneId
   ```

   默认试拍为 640×360、128 帧、取最后一帧，只输出未降噪 PNG 和记录到 `_scouts/<scene-id>/<view-id>/`。如果第二个相机还没选好，可先用 `--view "${sceneId}/view-a"`。修改机位后重新试拍；构图、光照等原生配置变化会使试拍缓存失效。`--force` 可强制重拍。

5. 看过试拍后，输出选定机位，再更新页面和检查结果：

   ```powershell
   python -B runs/scene-gallery/render.py --render --scene $sceneId
   python -B runs/scene-gallery/render.py --html --verify
   ```

   新增场景无需修改 Python 或 HTML，也无需重跑已有场景。`--scene` 选择整个场景，`--view scene-id/view-id` 选择机位，均支持多个参数。省略选择器时处理所有相机已就绪的机位；已有完整且匹配的图片会跳过。

## 修改、更新与完成状态

- 改标题、署名或章节顺序：运行 `--sync --html` 即可，不重渲染。
- 改相机、曝光、灯光、渲染参数或分辨率：运行 `--sync --html` 后，受影响机位标为 `stale`，页面提示“配置已更新，待重新渲染”。原 PNG 仍留在磁盘上，页面不再把它展示为新配置的结果。
- 确认新配置后，用 `--render --force --view scene-id/view-id` 替换该机位。其他机位保留。
- `camera: null` 表示待选机位；相机已设置但尚未渲染是 `pending`。`--verify` 默认要求所有机位完成。规划新场景期间，可用 `--html --verify --allow-pending` 检查已完成部分；`stale` 仍会使检查失败。
- 误拼的参数名、未知 ID、重复机位 ID 等会报错。更新后运行 `--html --verify` 检查 PNG 尺寸与哈希、同源与同曝光元数据、原生配置哈希、页面链接和数量。

每个机位可选字段：

| 字段 | 用途 |
| --- | --- |
| `exposure_ev` | 显示曝光；`null` 使用记录在结果中的自动曝光；两份 PNG 始终一致 |
| `lighting_overrides` | 覆盖注册场景已有灯光字段，例如 `emissive_scale`；会记录到实际配置 |
| `render_overrides` | 覆盖默认设置，例如 `frames`、`averaged_tail_frames` |
| `indirect_mode` | `RESTIRPT` 或 `BRDF`；默认继承全局设置 |

预算需要 `frames >= 128`，且 `1 <= averaged_tail_frames <= frames`，以兼容冻结定义中的 motion/reset 配置。只有静态机位用于此图库。除非有明确理由，不要修改 `definition_snapshot`；它保留初始实验基础设置，便于后续场景使用相同标准。

## 渲染与复现约定

- 现有 RTXDI v3.1.0 `FullSamplePdf` 构建，渲染前验证构建指纹与所选场景资源；没有改 renderer 源码。
- 默认 1920×1080，seed 1，ReSTIR DI + ReSTIR PT / ULTRA，5 次反弹，384 帧，平均最后 32 帧；PDF Similarity、原生降噪和原生 AA 关闭。
- 已有例外保持不变：Emerald Square 使用 BRDF 间接光、128 / 32 帧；Zero-Day 使用 512 / 64 帧、emissive scale 64。实际 ID 是 `zero-day-measure-one`。
- `raw.png` 是有限帧平均后的未降噪结果，加上记录的曝光与 ACES fitted / sRGB 显示转换。ReSTIR 历史导致这些样本相关，不应把帧数当作独立 spp。
- `processed.png` 对**同一份内存中的线性 RGB**做 OIDN RT / HDR / HIGH、CUDA、color-only 降噪，然后使用相同曝光和显示转换。当前安装版本是 OIDN 2.5。
- 不保留 HDR、PFM 或原生浮点图像。逐帧输入哈希、平均结果哈希和处理记录保存在每对图片旁边；成功后移除临时浮点文件。渲染失败时 `_work/` 会保留诊断内容，检查后再清理该失败机位，避免覆盖未检查的结果。

要求：同一仓库和场景资源、已验证的 renderer 与 shaders、Python 3.11 + NumPy / Pillow，以及兼容 CUDA 的 OIDN 2.x。更换安装位置时编辑 `gallery.json` 的 `oidn_library`。可用 `--oidn-smoke` 单独检查库能否工作。[OIDN C API](https://github.com/RenderKit/oidn/blob/master/include/OpenImageDenoise/oidn.h) 属 Apache-2.0；图库不分发其二进制文件。

`manifest.json` 是当前请求配置与输出状态的汇总；`config.json`、`render-record.json` 保留每次实际产出的配置和哈希。原始图库的复现摘要保留在 `initial_publication_reproduction`，重构不会改写历史图片和渲染记录。硬件、驱动或 renderer 变更可能导致像素差异。

这些图片用于查看配置后的场景样式，不代表材质导入已完全验证或达到 reference 收敛标准。资源许可与署名以仓库 `THIRD_PARTY.md` 为准。

## 维护代码与验证

新增场景走配置流程；改展示布局编辑 `gallery_tools/page.html` / `site.py`；改场景配置规则编辑 `catalog.py`；改实际捕获和处理管线编辑 `render.py`。生成记录不作为手工维护的源文件。

```powershell
python -B -m unittest discover -s runs/scene-gallery/tests -v
python -B runs/scene-gallery/render.py --sync --html --verify
python -B scripts/check_scaffold.py
```

测试覆盖新增场景发现、已有结果复用、配置变更失效、无效配置、动态页面，以及用模拟 renderer/OIDN 验证完整 PNG 成对导出；不会启动 GPU 渲染。`--sync`、`--html`、`--verify` 和 `--list-scenes` 也不会启动 renderer。

本目录位于 Git 默认忽略的 `runs/` 中；需要迁移或备份图库时，请同时保留配置、辅助代码、图片和记录，不能只复制 HTML。

无需服务器即可打开 HTML。若需要本地 HTTP 预览，在此目录运行 `python -B -m http.server 8767 --bind 127.0.0.1`。
