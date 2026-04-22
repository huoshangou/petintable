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


def place_on_canvas(cropped, canvas_size):
    """
    底部居中放置到 canvas_size × canvas_size 透明画布。
    如果裁剪图比画布大，等比缩放使高度适配，保持像素风用 NEAREST。
    """
    cw, ch = cropped.size
    scale = min(canvas_size / cw, canvas_size / ch)
    if scale < 1.0:
        new_w = max(1, int(cw * scale))
        new_h = max(1, int(ch * scale))
        cropped = cropped.resize((new_w, new_h), Image.NEAREST)
        cw, ch = new_w, new_h

    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    x = (canvas_size - cw) // 2
    y = canvas_size - ch  # bottom align
    canvas.paste(cropped, (x, y), cropped)
    return canvas


def extract_all():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    manifest = {}

    for filename, row, col_start, col_end, state_name in STATE_MAP:
        img = load_sheet(filename)
        out_dir = os.path.join(OUTPUT_DIR, state_name)
        os.makedirs(out_dir, exist_ok=True)

        frames = []
        for col in range(col_start, col_end + 1):
            cell, cell_w, cell_h = get_cell(img, row, col)
            bbox = find_content_bbox(cell)
            if bbox is None:
                print(f"  ⚠ 空帧: {state_name} row={row} col={col}")
                continue

            cropped = cell.crop(bbox)
            canvas = place_on_canvas(cropped, CANVAS_SIZE)

            frame_idx = col - col_start
            frame_path = f"frame_{frame_idx:02d}.png"
            canvas.save(os.path.join(out_dir, frame_path), "PNG")
            frames.append({
                "file": frame_path,
                "source": f"{filename}:row{row}:col{col}",
                "orig_bbox": [int(v) for v in bbox],
                "orig_size": (int(cell_w), int(cell_h)),
            })

        manifest[state_name] = {
            "frames": len(frames),
            "source_file": filename,
            "row": row,
            "col_range": [col_start, col_end],
            "frame_files": frames,
        }
        print(f"✓ {state_name}: {len(frames)} frames extracted")

    with open(os.path.join(OUTPUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"\n全量导出完成 → {OUTPUT_DIR}/")
    print(f"共 {len(manifest)} 组动画")
    print("请检查每组输出，确认映射关系后调整 STATE_MAP 做正式导出。")


if __name__ == "__main__":
    extract_all()