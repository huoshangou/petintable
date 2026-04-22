# Vibe Sprite 切帧 — 锚点 & 缩放修复方案

> 任务对象：Kimi 2.6 执行
> 目标：修复 knock / question 等大动作动画的横向位移与「呼吸式缩放」
> 预估工时：30-45 分钟（含验证）

---

## 0. 背景速读（必看）

### 现象
- knock（敲键盘）和 question（啄屏幕）动画播放时，鸟出现明显横向抖动
- 部分帧鸟整体大小不一致，有「呼吸感」

### 根因（已定位）
**Bug 1 — 锚点错误**：[`pic/extract_sprites.py:78-112`](pic/extract_sprites.py#L78-L112) 的 `place_on_canvas_aligned()` 用 **bbox 几何中心** 当对齐基准。但当鸟把手伸出去、嘴啄出去时，bbox 向一侧扩展，bbox 中心不再代表鸟身体的位置——算法误以为鸟在移动，反向补偿，造成视觉抖动。

**Bug 2 — 逐帧独立缩放**：`place_on_canvas_aligned()` line 89 给每帧独立算 `scale = min(canvas/w, canvas/h, 1.0)`。动作大的帧 bbox 大就被压缩，小动作帧不压。结果鸟在帧间「呼吸」式变大变小。

### 不动的东西
- `STATE_MAP` 配置（`pic/extract_sprites.py:32-45`）—— 来源映射不要改
- `find_content_bbox()` —— bbox 检测算法不变
- `sync_to_assets()` —— 同步逻辑不变
- `assets/sprites/` 下的目录结构与文件命名
- 渲染层 `src/renderer/pet.js`

---

## 1. 验收标准（按此打分，全过才算完）

| # | 验证方式 | 期望结果 | 当前结果 |
|---|---------|---------|---------|
| V1 | `pic/verify_sprites.html` 打开 knock 动画，把 8 帧叠加成半透明对比 | 鸟脚的位置完全重合（±1 px） | ✗ 偏差大 |
| V2 | 同上 question | 鸟脚完全重合（±1 px） | ✗ 偏差大 |
| V3 | 同上 idle_no_glasses（已正常的小动作组） | 不退化 | ✓ |
| V4 | 同上 coding（已正常） | 不退化 | ✓ |
| V5 | knock / question 的所有帧最大像素高度差 ≤ 2 px | 整体大小一致 | ✗ 当前差异 5+ px |
| V6 | 在 Vibe 里实际播放 knock 动画 5 秒 | 视觉上无横向跳动、无呼吸感 | ✗ |
| V7 | 在 Vibe 里实际播放 question 动画 5 秒 | 视觉上无横向跳动、无呼吸感 | ✗ |

---

## 2. 实现方案

### 2.1 新增 `find_foot_anchor()` 函数

**位置**：`pic/extract_sprites.py`，加在 `find_content_bbox()` 函数之后（约 line 76 之后）。

**思路**：取 bbox 下方 25% 区域的非透明像素 x 中位数。理由：
- 鸟的脚是动画里最稳定的特征（啄屏幕时脚不动，敲键盘时脚也不动）
- 取下方 25% 而非最底行，是为了容错（脚可能略微抬起）
- 用中位数比平均更抗噪（爪子张开时，平均值会被边缘像素拉偏）

```python
def find_foot_anchor(cell_img, bbox):
    """
    取 bbox 下方 25% 区域的非透明像素中位数 x，作为该帧的脚锚点。
    返回值：在原始 cell 坐标系下的 x 坐标（float）。
    """
    arr = np.array(cell_img)
    alpha = arr[:, :, 3]
    bbox_h = bbox[3] - bbox[1]
    bottom_y = int(bbox[1] + bbox_h * 0.75)
    bottom = alpha[bottom_y:bbox[3], bbox[0]:bbox[2]]
    cols_with_content = np.any(bottom > 0, axis=0)
    foot_cols = np.where(cols_with_content)[0]
    if len(foot_cols) == 0:
        # 兜底：用 bbox 中心
        return (bbox[0] + bbox[2]) / 2
    return bbox[0] + float(np.median(foot_cols))
```

### 2.2 改写 `place_on_canvas_aligned()` → `place_on_canvas_aligned_v2()`

**位置**：替换 [`pic/extract_sprites.py:78-112`](pic/extract_sprites.py#L78-L112) 的 `place_on_canvas_aligned()` 函数。**新增函数，旧的可以删掉**（确保没人调用旧的）。

**核心改动**：
1. 移除函数内的 `scale` 计算，改为接受外部传入的 `group_scale`
2. 用「脚锚点放到 canvas 水平中心」替代「bbox 居中 + 偏移补偿」

```python
def place_on_canvas_aligned_v2(cropped, bbox, frame_anchor_x, group_scale, canvas_size):
    """
    使用脚锚点对齐 + 组级统一缩放，把 cropped 帧放到 canvas_size × canvas_size 透明画布。

    参数：
      cropped:        从 cell 中按 bbox 裁出的 RGBA 图
      bbox:           (left, top, right, bottom)，原始 cell 坐标
      frame_anchor_x: 该帧的脚锚点（原始 cell 坐标系下的 x）
      group_scale:    整组动画统一的缩放系数（由 extract_all 计算并传入）
      canvas_size:    输出画布边长

    对齐规则：
      - 水平：脚锚点对齐到 canvas 水平中心
      - 垂直：底部对齐到 canvas 底边
    """
    content_w = bbox[2] - bbox[0]
    content_h = bbox[3] - bbox[1]

    scaled_w = max(1, int(content_w * group_scale))
    scaled_h = max(1, int(content_h * group_scale))

    if group_scale < 1.0:
        cropped = cropped.resize((scaled_w, scaled_h), Image.NEAREST)

    # 脚锚点在 cropped（缩放后）内的相对 x
    anchor_in_crop = (frame_anchor_x - bbox[0]) * group_scale

    # 让锚点出现在 canvas 水平中心
    canvas_center = canvas_size / 2
    x = int(round(canvas_center - anchor_in_crop))

    # 底部对齐
    y = canvas_size - scaled_h

    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    # PIL paste 会自动裁掉越界的部分；正常对齐下不应越界
    canvas.paste(cropped, (x, y), cropped)
    return canvas
```

### 2.3 改写 `extract_all()` 中的两遍循环

**位置**：替换 [`pic/extract_sprites.py:159-220`](pic/extract_sprites.py#L159-L220) 的 `extract_all()` 函数中第一遍/第二遍的逻辑。

**核心改动**：
- 第一遍除了收集 bboxes，同时计算 `group_scale` 和 `unified_anchor_x`
- 第二遍调用 `place_on_canvas_aligned_v2()` 而不是旧函数

```python
def extract_all():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    manifest = {}

    for filename, row, col_start, col_end, state_name in STATE_MAP:
        img = load_sheet(filename)
        out_dir = os.path.join(OUTPUT_DIR, state_name)
        os.makedirs(out_dir, exist_ok=True)

        # ─── 第一遍：收集 bbox + 锚点 + 计算组级参数 ───
        bboxes = []
        for col in range(col_start, col_end + 1):
            cell, cell_w, cell_h = get_cell(img, row, col)
            bbox = find_content_bbox(cell)
            bboxes.append((col, cell, cell_w, cell_h, bbox))

        valid_bboxes = [b for *_, b in bboxes if b is not None]
        if not valid_bboxes:
            print(f"  ⚠ 跳过空动画组: {state_name}")
            continue

        # 组级统一缩放：以整组动画 bbox 的最大尺寸为基准
        group_max_w = max(b[2] - b[0] for b in valid_bboxes)
        group_max_h = max(b[3] - b[1] for b in valid_bboxes)
        group_scale = min(CANVAS_SIZE / group_max_w, CANVAS_SIZE / group_max_h, 1.0)

        # 组级统一锚点：所有帧脚锚点的中位数（仅用于日志/调试，对齐由每帧自己的锚点完成）
        foot_anchors = [
            find_foot_anchor(cell, bbox)
            for col, cell, cell_w, cell_h, bbox in bboxes
            if bbox is not None
        ]
        unified_anchor_x = sorted(foot_anchors)[len(foot_anchors) // 2]

        # ─── 第二遍：用 group_scale + 每帧锚点渲染 ───
        frames = []
        for col, cell, cell_w, cell_h, bbox in bboxes:
            if bbox is None:
                print(f"  ⚠ 空帧: {state_name} row={row} col={col}")
                continue

            cropped = cell.crop(bbox)
            frame_anchor_x = find_foot_anchor(cell, bbox)
            canvas = place_on_canvas_aligned_v2(
                cropped, bbox, frame_anchor_x, group_scale, CANVAS_SIZE
            )

            frame_idx = col - col_start
            frame_path = f"frame_{frame_idx:02d}.png"
            canvas.save(os.path.join(out_dir, frame_path), "PNG")
            frames.append({
                "file": frame_path,
                "source": f"{filename}:row{row}:col{col}",
                "orig_bbox": [int(v) for v in bbox],
                "orig_size": (int(cell_w), int(cell_h)),
                "foot_anchor_x": round(frame_anchor_x, 2),
            })

        manifest[state_name] = {
            "frames": len(frames),
            "source_file": filename,
            "row": row,
            "col_range": [col_start, col_end],
            "group_scale": round(group_scale, 4),
            "unified_anchor_x": round(unified_anchor_x, 2),
            "frame_files": frames,
        }
        print(
            f"✓ {state_name}: {len(frames)} frames "
            f"(scale={group_scale:.3f}, anchor_x={unified_anchor_x:.1f})"
        )

    with open(os.path.join(OUTPUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"\n全量导出完成 → {OUTPUT_DIR}/")
    print(f"共 {len(manifest)} 组动画")

    print("\n--- 同步到 assets/sprites/ ---")
    sync_to_assets()
```

### 2.4 增强 `verify_sprites.html` 加一个「叠加对比」视图（可选但推荐）

**位置**：`pic/verify_sprites.html`

**目的**：让 V1/V2 验收能直观看到。在原有逐帧展示之外，加一个把同组所有帧以 30% 透明度叠加渲染到同一画布的视图。

实现：在每个动画组下方加一个 `<canvas width=64 height=64>`，用 JS 把该组所有帧画到同一个 canvas，每帧 globalAlpha = 0.3。

如果 verify_sprites.html 当前没用 canvas 而是 `<img>`，按原结构最简方案就好，不必大改。判断标准：能让 Steve 一眼看出对齐效果即可。

---

## 3. 测试步骤

### 3.1 跑提取脚本
```bash
cd ~/Desktop/petintable/pic
python3 extract_sprites.py
```

期望日志包含每组的 `scale` 和 `anchor_x`，所有 6 个白名单状态都成功导出并同步到 `../assets/sprites/`。

### 3.2 离线验证（V1-V5）
```bash
# 用浏览器打开
open verify_sprites.html
```

逐项检查：
- V1：knock 8 帧叠加，鸟脚是否重合
- V2：question 8 帧叠加，鸟脚是否重合
- V3/V4：idle_no_glasses 和 coding 是否退化
- V5：用 ImageMagick 或肉眼比对每组各帧的最大像素高度

V5 自动化辅助命令（可选）：
```bash
# 列出 knock 各帧实际内容高度（最顶非透明行 → 最底非透明行）
python3 -c "
from PIL import Image
import numpy as np, os
for f in sorted(os.listdir('../assets/sprites/knock')):
    if not f.endswith('.png'): continue
    a = np.array(Image.open(f'../assets/sprites/knock/{f}'))[:,:,3]
    rows = np.where(np.any(a>0, axis=1))[0]
    h = rows[-1]-rows[0]+1 if len(rows) else 0
    print(f'{f}: h={h}')
"
```
所有帧 h 差异应 ≤ 2 px。

### 3.3 在线验证（V6/V7）
```bash
cd ~/Desktop/petintable
npm start
# 通过 HTTP API 强制切到 knock / question
curl 'http://localhost:3000/state?action=wait'   # 触发 question
# 看 5 秒，肉眼检查是否还有抖动/呼吸
# knock 不易直接触发，可临时改 pet.js 让 idle 后插一段 knock 循环用作目测
```

### 3.4 回归确认
- 切回 idle / coding 看是否退化
- 关闭 Vibe 重启，确认资产完整

---

## 4. 提交建议

单 commit 即可：`fix(sprites): use foot anchor + group-level scale for jitter-free animation`。

commit body 列出：
- 修复了什么 bug（锚点 + 缩放）
- 受影响的动画组（主要是 knock、question）
- 验收结果（V1-V7 全过）

---

## 5. 不要做的事

- ❌ 不要引入新依赖（OpenCV、scikit-image 等）。Pillow + numpy 够用。
- ❌ 不要改 `STATE_MAP` 来"修复某个特定帧"——若有源素材问题，记录在交付报告里告诉 Steve，**不要在脚本里硬编码补偿**。
- ❌ 不要顺手重构 `sync_to_assets()` 或 `find_content_bbox()`。
- ❌ 不要在主流程里加日志洪水。新增的 `foot_anchor_x` 写到 manifest 即可。
- ❌ 不要把 `place_on_canvas_aligned`（旧版）保留，避免下次有人误用。

---

## 6. 已知边界

- **如果某帧鸟把脚抬起来**（比如未来加飞行动画），`find_foot_anchor` 会失准。当前 5 个白名单状态都是站立动画，不存在此问题。未来加飞行帧需另外手标锚点。
- **如果源素材某帧鸟尺寸超过 cell 边界一半**，`group_scale` 会把整组压得很小。当前素材未遇到此情况。

---

## 7. 完成后给 Steve 的反馈

按以下格式回复：

```
✅ Sprite 锚点修复完成

V1 knock 叠加: [通过/未通过 + 描述]
V2 question 叠加: [通过/未通过 + 描述]
V3 idle_no_glasses: [无退化/有退化 + 描述]
V4 coding: [无退化/有退化 + 描述]
V5 高度差: knock=[max-min]px, question=[max-min]px
V6 实播 knock: [无抖动/有抖动 + 描述]
V7 实播 question: [无抖动/有抖动 + 描述]

manifest.json 中 group_scale 和 unified_anchor_x 数值：
- knock: scale=___, anchor=___
- question: scale=___, anchor=___
- (其他)

commit hash: ___
```

如果有验收项未过，附具体截图或像素差数据，**不要自己尝试硬编码修补**——告诉 Steve，让他判断是源素材问题还是算法问题。
