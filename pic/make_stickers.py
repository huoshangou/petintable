#!/usr/bin/env python3
"""
将帧动画序列合成为透明背景 GIF 表情包。
输出到 pic/stickers/，每个状态一个 GIF。
"""
import os
from PIL import Image

ASSET_DIR = "../assets/sprites"
OUTPUT_DIR = "./stickers"
FRAME_DURATION_MS = 120  # 每帧 120ms

STATES = [
    "idle_no_glasses",
    "equip_glasses",
    "coding",
    "question",
    "knock",
]

def make_gif(state_name, scale=2):
    src_dir = os.path.join(ASSET_DIR, state_name)
    if not os.path.exists(src_dir):
        print(f"⚠ 跳过 {state_name}: 目录不存在")
        return

    frames = []
    for i in range(8):
        path = os.path.join(src_dir, f"frame_{i:02d}.png")
        if not os.path.exists(path):
            break
        img = Image.open(path)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        if scale != 1:
            w, h = img.size
            img = img.resize((w * scale, h * scale), Image.NEAREST)
        frames.append(img)

    if not frames:
        print(f"⚠ 跳过 {state_name}: 无帧")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"{state_name}_{scale}x.gif")

    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_DURATION_MS,
        loop=0,
        transparency=0,
        disposal=2,
    )
    print(f"✓ {out_path} ({len(frames)} frames, {scale}x)")

if __name__ == "__main__":
    for state in STATES:
        make_gif(state, scale=2)  # 64*2 = 128px
        make_gif(state, scale=4)  # 64*4 = 256px

    print(f"\n表情包输出到 {OUTPUT_DIR}/")
    print("建议: 微信表情包建议 240x240 以内，用 128px 版本")
