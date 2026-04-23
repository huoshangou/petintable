#!/usr/bin/env python3
"""
分析 assets/sprites/ 下所有 sprite 的实际调色板。
目的：决定后续"调色板规范化"的目标色数（8/12/16/24/32）。

输出:
  - 原始非透明像素的独特颜色数
  - top 20 高频颜色 + 累计覆盖率
  - 量化到 8/16/24/32 色后的视觉对比（保存到 _palette_analysis/）
  - 推荐的目标色数
"""

from PIL import Image
import numpy as np
import os
from collections import Counter

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "sprites")
OUT_DIR = os.path.join(os.path.dirname(__file__), "_palette_analysis")
QUANTIZE_LEVELS = [8, 12, 16, 24, 32]


def collect_all_pixels():
    """遍历所有 sprite，收集非透明像素 RGB。"""
    all_rgb = []
    file_count = 0
    for root, _, files in os.walk(ASSETS_DIR):
        for f in files:
            if not f.endswith(".png"):
                continue
            path = os.path.join(root, f)
            img = np.array(Image.open(path).convert("RGBA"))
            mask = img[:, :, 3] > 0
            rgb = img[mask][:, :3]
            all_rgb.append(rgb)
            file_count += 1
    return np.concatenate(all_rgb, axis=0), file_count


def freq_table(rgb):
    """统计颜色频率。"""
    tuples = [tuple(p) for p in rgb]
    return Counter(tuples)


def render_palette_swatch(colors_with_counts, out_path, title):
    """把 top 颜色画成色卡图。"""
    n = len(colors_with_counts)
    cell = 32
    cols = min(n, 16)
    rows = (n + cols - 1) // cols
    canvas = Image.new("RGB", (cols * cell, rows * cell + 16), (240, 240, 240))
    pixels = canvas.load()
    for i, (color, _count) in enumerate(colors_with_counts):
        r, c = divmod(i, cols)
        for dy in range(cell):
            for dx in range(cell):
                pixels[c * cell + dx, r * cell + dy] = color
    canvas.save(out_path)


def quantize_one_image(path, n_colors, out_path):
    """量化单张图到 n 色（保留 alpha）。"""
    img = Image.open(path).convert("RGBA")
    arr = np.array(img)
    alpha = arr[:, :, 3]

    rgb = Image.fromarray(arr[:, :, :3], mode="RGB")
    quantized = rgb.quantize(colors=n_colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).convert("RGB")
    q_arr = np.array(quantized)

    out = np.dstack([q_arr, alpha])
    Image.fromarray(out, mode="RGBA").save(out_path)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print("📊 收集像素中…")
    rgb, file_count = collect_all_pixels()
    print(f"  扫描了 {file_count} 个 PNG，共 {len(rgb):,} 个非透明像素")

    counts = freq_table(rgb)
    n_unique = len(counts)
    print(f"\n🎨 原始独特颜色数: {n_unique}")

    top20 = counts.most_common(20)
    total = len(rgb)
    cum = 0
    print(f"\n📈 Top 20 颜色 (总像素 {total:,}):")
    print(f"  {'#':>3}  {'RGB':<18}  {'HEX':<10}  {'count':>8}  {'pct':>6}  {'cum%':>6}")
    for i, ((r, g, b), c) in enumerate(top20):
        cum += c
        pct = c / total * 100
        cum_pct = cum / total * 100
        hex_code = f"#{r:02x}{g:02x}{b:02x}"
        print(f"  {i+1:>3}  rgb({r:>3},{g:>3},{b:>3})  {hex_code:<10}  {c:>8,}  {pct:>5.1f}%  {cum_pct:>5.1f}%")

    # Top N 累计覆盖率（评估"长尾"程度）
    print(f"\n📐 累计覆盖率（决定调色板大小的关键指标）:")
    for n in [8, 12, 16, 24, 32, 64, 128]:
        if n > n_unique:
            break
        top_n = counts.most_common(n)
        coverage = sum(c for _, c in top_n) / total * 100
        print(f"  Top {n:>3} 色覆盖: {coverage:>5.1f}%")

    # 渲染色卡
    print(f"\n🖼️  生成色卡到 {OUT_DIR}/")
    for n in QUANTIZE_LEVELS:
        render_palette_swatch(counts.most_common(n), os.path.join(OUT_DIR, f"palette_top{n:02d}.png"), f"top {n}")

    # 量化测试图：拿 idle 第一帧、coding 第一帧、question 第一帧分别量化
    test_samples = [
        ("idle_no_glasses/frame_00.png", "idle"),
        ("coding/frame_00.png", "coding"),
        ("question/frame_00.png", "question"),
        ("knock/frame_00.png", "knock"),
    ]

    print(f"\n🧪 量化对比图（每个等级一组样本）:")
    for n in QUANTIZE_LEVELS:
        for rel, name in test_samples:
            src = os.path.join(ASSETS_DIR, rel)
            if not os.path.exists(src):
                continue
            dst = os.path.join(OUT_DIR, f"q{n:02d}_{name}.png")
            quantize_one_image(src, n, dst)
        print(f"  q{n:02d}: 4 张样本已生成 → q{n:02d}_*.png")

    # 推荐
    print("\n💡 调色板大小推荐参考:")
    coverage_16 = sum(c for _, c in counts.most_common(16)) / total * 100
    coverage_24 = sum(c for _, c in counts.most_common(24)) / total * 100
    coverage_32 = sum(c for _, c in counts.most_common(32)) / total * 100
    print(f"  Top 16  覆盖 {coverage_16:.1f}% → 适合纯色块风格")
    print(f"  Top 24  覆盖 {coverage_24:.1f}% → 中等细节")
    print(f"  Top 32  覆盖 {coverage_32:.1f}% → 保留更多渐变/抗锯齿")
    print(f"\n  请打开 {OUT_DIR}/q*_*.png 对比量化效果，选最低能接受的色数。")
    print(f"  色数越少，palette swap 时人工映射越简单。")


if __name__ == "__main__":
    main()
