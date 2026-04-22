#!/usr/bin/env python3
"""
从已抠绿的 Sprite Sheet 中精确裁剪每帧小鸟，
底部居中对齐到 64×64 透明画布，导出 PNG 序列。

每张来源图 = 4行 × 8列 的网格 (176×192 每格)
3 张来源图对应 3 种角色状态组，共 12 组动画 × 8 帧 = 96 张输出

输出目录结构:
  sprites/
    idle_no_glasses/   frame_00.png ~ frame_07.png
    equip_glasses/      frame_00.png ~ frame_03.png  (只取前4帧)
    coding/            frame_00.png ~ frame_03.png  (只取前4帧)
    question/          frame_00.png ~ frame_07.png
    knock/             frame_00.png ~ frame_03.png
    remove_glasses/    frame_00.png ~ frame_03.png  (取后4帧)
"""

from PIL import Image
import numpy as np
import os
import json

RAW_DIR = "./assets"
OUTPUT_DIR = "./sprites"
CANVAS_SIZE = 64

SHEET_GRID = (4, 8)  # rows, cols

# 来源图 → 状态映射
# 每项: (文件名, 动画行号, 起始列, 结束列(含), 输出目录名)
STATE_MAP = [
    # idle without glass.png: only row0 usable, row1-3 have size/position issues
    ("idle without glass.png", 0, 0, 7, "idle_no_glasses"),
    # wear glass.png: row0 = equip_glasses (full 8 frames)
    ("wear glass.png", 0, 0, 7, "equip_glasses"),
    ("wear glass.png", 1, 0, 7, "wear_row1"),
    ("wear glass.png", 2, 0, 7, "wear_row2"),
    ("wear glass.png", 3, 0, 7, "wear_row3"),
    # with glass.png: row0=wearglass_idle, row1=coding, row2=question, row3=knock
    ("with glass.png", 0, 0, 7, "wearglass_idle"),
    ("with glass.png", 1, 0, 7, "coding"),
    ("with glass.png", 2, 0, 7, "question"),
    ("with glass.png", 3, 0, 7, "knock"),
]

# 需要确认哪些行对应哪个动画，上面是初步猜测
# 先全量导出，你看了图再决定正式映射


def load_sheet(filename):
    path = os.path.join(RAW_DIR, filename)
    img = Image.open(path).convert("RGBA")
    return img


def get_cell(img, row, col):
    cell_w = img.width // SHEET_GRID[1]
    cell_h = img.height // SHEET_GRID[0]
    x0 = col * cell_w
    y0 = row * cell_h
    return img.crop((x0, y0, x0 + cell_w, y0 + cell_h)), cell_w, cell_h


def find_content_bbox(cell_img):
    """在单个 cell 内找非透明像素的紧致包围盒"""
    arr = np.array(cell_img)
    alpha = arr[:, :, 3]
    rows = np.any(alpha > 0, axis=1)
    cols = np.any(alpha > 0, axis=0)
    if not rows.any():
        return None
    rmin, rmax = np.where(rows)[0][[0, -1]]
    cmin, cmax = np.where(cols)[0][[0, -1]]
    return (cmin, rmin, cmax + 1, rmax + 1)  # left, top, right, bottom


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
        return (bbox[0] + bbox[2]) / 2
    return bbox[0] + float(np.median(foot_cols))


def place_on_canvas_aligned_v2(cropped, bbox, frame_anchor_x, group_scale, canvas_size):
    """
    使用脚锚点对齐 + 组级统一缩放，把 cropped 帧放到 canvas_size × canvas_size 透明画布。
    """
    content_w = bbox[2] - bbox[0]
    content_h = bbox[3] - bbox[1]

    scaled_w = max(1, int(content_w * group_scale))
    scaled_h = max(1, int(content_h * group_scale))

    if group_scale < 1.0:
        cropped = cropped.resize((scaled_w, scaled_h), Image.NEAREST)

    anchor_in_crop = (frame_anchor_x - bbox[0]) * group_scale
    canvas_center = canvas_size / 2
    x = int(round(canvas_center - anchor_in_crop))
    y = canvas_size - scaled_h

    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    canvas.paste(cropped, (x, y), cropped)
    return canvas


# 最终同步到应用资产目录的白名单
ASSET_STATES = [
    "idle_no_glasses",
    "equip_glasses",
    "coding",
    "question",
    "knock",
    "wearglass_idle",
]


def sync_to_assets():
    """将 pic/sprites/ 中白名单内的动画组同步到 ../assets/sprites/"""
    src_base = OUTPUT_DIR
    dst_base = os.path.join(os.path.dirname(__file__), "..", "assets", "sprites")
    os.makedirs(dst_base, exist_ok=True)

    for state_name in ASSET_STATES:
        src_dir = os.path.join(src_base, state_name)
        dst_dir = os.path.join(dst_base, state_name)
        if not os.path.exists(src_dir):
            print(f"  ⚠ 跳过同步: {state_name} 不存在于 {src_base}")
            continue

        # 清空目标目录，确保无残留旧帧
        if os.path.exists(dst_dir):
            for f in os.listdir(dst_dir):
                if f.endswith(".png"):
                    os.remove(os.path.join(dst_dir, f))
        else:
            os.makedirs(dst_dir, exist_ok=True)

        for f in os.listdir(src_dir):
            if f.endswith(".png"):
                src_path = os.path.join(src_dir, f)
                dst_path = os.path.join(dst_dir, f)
                with open(src_path, "rb") as sf:
                    with open(dst_path, "wb") as df:
                        df.write(sf.read())
        print(f"  → 已同步: {state_name}")

    print(f"\n资产同步完成 → {dst_base}/")


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

        group_max_w = max(b[2] - b[0] for b in valid_bboxes)
        group_max_h = max(b[3] - b[1] for b in valid_bboxes)
        group_scale = min(CANVAS_SIZE / group_max_w, CANVAS_SIZE / group_max_h, 1.0)

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


if __name__ == "__main__":
    extract_all()