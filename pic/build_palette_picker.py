#!/usr/bin/env python3
"""
构建交互式调色板命名工具。

工作流:
  1. 读取所有 sprite，全集量化到 N 色，得到统一调色板
  2. 把每张原图重映射到这个调色板（最近邻）
  3. 为每个色生成"高亮 mask"：在代表性 sprite 上把该色像素高亮，其他像素灰度化
  4. 输出 HTML/JS 让用户给每个色命名，导出 palette.json

输出:
  pic/_palette_picker/
    index.html
    app.js
    data/
      palette.json         # 16 色的 hex + 像素数
      previews/            # 4-6 张代表性 sprite（量化后）
        <state>_<frame>.png
      masks/
        color_NN_<state>_<frame>.png  # 高亮版
"""

from PIL import Image
import numpy as np
import os
import json
import shutil

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "sprites")
OUT_DIR = os.path.join(os.path.dirname(__file__), "_palette_picker")
DATA_DIR = os.path.join(OUT_DIR, "data")
N_COLORS = 16
PREVIEW_FRAMES = [
    ("idle_no_glasses", "frame_00.png"),
    ("idle_no_glasses", "frame_04.png"),
    ("coding", "frame_00.png"),
    ("question", "frame_00.png"),
    ("question", "frame_04.png"),
    ("knock", "frame_00.png"),
]
HIGHLIGHT_MAGENTA = (255, 0, 255)


def collect_all_pixels():
    all_rgb = []
    for root, _, files in os.walk(ASSETS_DIR):
        for f in files:
            if not f.endswith(".png"):
                continue
            img = np.array(Image.open(os.path.join(root, f)).convert("RGBA"))
            mask = img[:, :, 3] > 0
            all_rgb.append(img[mask][:, :3])
    return np.concatenate(all_rgb, axis=0)


def derive_global_palette(all_pixels, n_colors):
    """用 PIL mediancut 在全集像素上做量化，得到统一调色板。"""
    # 把 (N, 3) 像素 reshape 成 (N, 1) 单行图，PIL 接受这种宽度
    h = 1
    w = len(all_pixels)
    img = Image.fromarray(all_pixels.reshape(h, w, 3).astype(np.uint8), mode="RGB")
    quantized = img.quantize(colors=n_colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    raw_palette = quantized.getpalette()[: n_colors * 3]
    palette = np.array(raw_palette, dtype=np.uint8).reshape(-1, 3)
    return palette


def remap_to_palette(rgb_array, palette):
    """每个像素找最近的调色板色，返回索引。
    rgb_array 可以是 (H, W, 3) 或 (N, 3)。返回保持除最后一维外的形状。"""
    orig_shape = rgb_array.shape[:-1]
    flat = rgb_array.reshape(-1, 3).astype(np.int32)
    pal = palette.astype(np.int32)
    dists = np.sum((flat[:, None, :] - pal[None, :, :]) ** 2, axis=2)
    return np.argmin(dists, axis=1).reshape(orig_shape)


def quantize_image(src_path, palette):
    img = np.array(Image.open(src_path).convert("RGBA"))
    rgb = img[:, :, :3]
    alpha = img[:, :, 3]
    indices = remap_to_palette(rgb, palette)
    new_rgb = palette[indices]
    out = np.dstack([new_rgb, alpha]).astype(np.uint8)
    return out, indices, alpha


def make_highlight(quantized_rgba, indices, alpha, target_color_idx):
    """生成高亮 mask: 目标色用洋红描边/填充，其他色降饱和。"""
    rgb = quantized_rgba[:, :, :3].astype(np.float32)
    # 灰度化非目标像素，强调目标
    gray = (0.3 * rgb[:, :, 0] + 0.59 * rgb[:, :, 1] + 0.11 * rgb[:, :, 2])
    desat = np.dstack([gray, gray, gray]) * 0.5 + rgb * 0.2
    desat = np.clip(desat, 0, 255).astype(np.uint8)

    target_mask = (indices == target_color_idx) & (alpha > 0)
    out_rgb = desat.copy()
    out_rgb[target_mask] = HIGHLIGHT_MAGENTA

    return np.dstack([out_rgb, alpha]).astype(np.uint8)


def render_palette_swatch(palette, counts, out_path):
    """生成色卡总览图：16 色按使用频率排序。"""
    cell = 64
    cols = 4
    rows = (len(palette) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * cell, rows * cell), (240, 240, 240))
    pixels = canvas.load()
    for i, color in enumerate(palette):
        r, c = divmod(i, cols)
        for dy in range(cell):
            for dx in range(cell):
                pixels[c * cell + dx, r * cell + dy] = tuple(int(v) for v in color)
    canvas.save(out_path)


def write_html(out_dir, n_colors, preview_keys):
    html = f"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Vibe 调色板命名工具</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, "PingFang SC", sans-serif;
    margin: 0; padding: 16px;
    background: #1a1a1a; color: #eee;
    display: grid;
    grid-template-columns: 360px 1fr;
    gap: 24px;
    min-height: 100vh;
  }}
  h1 {{ margin: 0 0 12px; font-size: 16px; }}
  .help {{ font-size: 12px; color: #888; margin-bottom: 12px; line-height: 1.5; }}
  .palette-list {{ display: flex; flex-direction: column; gap: 6px; }}
  .color-row {{
    display: grid;
    grid-template-columns: 32px 80px 1fr 56px;
    gap: 8px; align-items: center;
    padding: 6px 8px; border-radius: 6px;
    background: #222; cursor: pointer;
    border: 2px solid transparent;
  }}
  .color-row:hover {{ background: #2c2c2c; }}
  .color-row.active {{ border-color: #4af; background: #1a3550; }}
  .swatch {{
    width: 32px; height: 32px; border-radius: 4px;
    border: 1px solid #444;
  }}
  .hex {{ font-family: ui-monospace, Menlo; font-size: 11px; color: #aaa; }}
  .name-input {{
    background: #111; color: #eee; border: 1px solid #333;
    padding: 4px 8px; border-radius: 4px; font-size: 13px;
    font-family: ui-monospace, Menlo;
  }}
  .name-input:focus {{ outline: none; border-color: #4af; }}
  .count {{ font-size: 11px; color: #777; text-align: right; }}
  .preview-area {{ display: flex; flex-direction: column; gap: 16px; }}
  .preview-label {{ font-size: 13px; color: #aaa; }}
  .preview-grid {{
    display: grid;
    grid-template-columns: repeat({len(preview_keys)}, 1fr);
    gap: 16px;
  }}
  .preview-cell {{ text-align: center; }}
  .preview-cell img {{
    width: 192px; height: 192px;
    image-rendering: pixelated;
    background: #2a2a2a;
    border-radius: 6px;
  }}
  .preview-cell .label {{ font-size: 11px; color: #777; margin-top: 4px; }}
  .actions {{
    position: sticky; top: 0;
    padding: 8px 0; background: #1a1a1a;
    display: flex; gap: 8px; flex-wrap: wrap;
  }}
  button {{
    background: #4af; color: white; border: none;
    padding: 8px 16px; border-radius: 6px; cursor: pointer;
    font-size: 13px;
  }}
  button:hover {{ background: #3af; }}
  button.secondary {{ background: #444; }}
  button.secondary:hover {{ background: #555; }}
  textarea {{
    width: 100%; height: 200px; background: #0a0a0a; color: #cfc;
    border: 1px solid #333; padding: 12px; border-radius: 6px;
    font-family: ui-monospace, Menlo; font-size: 12px;
  }}
  .hint {{ font-size: 11px; color: #666; margin-top: 4px; }}
</style>
</head>
<body>

<aside>
  <h1>🎨 调色板命名（{n_colors} 色）</h1>
  <div class="help">
    1. 点击任意颜色行 → 右侧显示该色在原图的高亮位置（洋红色）<br>
    2. 给每个色起一个语义名（如 body_main, outline, beak）<br>
    3. 命名常用约定：snake_case，如 body_main / shadow_dark / glasses_frame
  </div>

  <div class="actions">
    <button onclick="exportJson()">📋 导出 JSON</button>
    <button class="secondary" onclick="loadDraft()">↺ 恢复草稿</button>
    <button class="secondary" onclick="clearDraft()">✕ 清空</button>
  </div>

  <div class="palette-list" id="paletteList"></div>
</aside>

<main>
  <div class="preview-label" id="previewLabel">← 点击左侧任意颜色查看高亮</div>
  <div class="preview-grid" id="previewGrid"></div>

  <h1 style="margin-top:24px">导出</h1>
  <textarea id="exportArea" readonly placeholder="点击「导出 JSON」按钮"></textarea>
  <div class="hint">导出后请保存为 assets/skins/_roles.json（或其他位置）。这是颜色角色→HEX 的基础映射，皮肤就是替换 HEX。</div>
</main>

<script src="app.js"></script>
</body>
</html>
"""
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(html)


def write_app_js(out_dir, palette_meta, preview_keys):
    js = f"""// Vibe palette picker
const PALETTE = {json.dumps(palette_meta, ensure_ascii=False, indent=2)};
const PREVIEW_KEYS = {json.dumps(preview_keys)};

const STORAGE_KEY = "vibe_palette_picker_draft";

function $(sel) {{ return document.querySelector(sel); }}
function $$(sel) {{ return document.querySelectorAll(sel); }}

function renderList() {{
  const list = $('#paletteList');
  list.innerHTML = '';
  PALETTE.forEach((c, i) => {{
    const row = document.createElement('div');
    row.className = 'color-row';
    row.dataset.idx = i;
    row.innerHTML = `
      <div class="swatch" style="background:${{c.hex}}"></div>
      <div class="hex">${{c.hex}}</div>
      <input class="name-input" data-idx="${{i}}" type="text" placeholder="color_${{String(i).padStart(2,'0')}}">
      <div class="count">${{c.count.toLocaleString()}}</div>
    `;
    row.addEventListener('click', (e) => {{
      if (e.target.tagName === 'INPUT') return;
      selectColor(i);
    }});
    list.appendChild(row);
  }});
  // input change → save draft
  $$('.name-input').forEach(inp => {{
    inp.addEventListener('input', saveDraft);
  }});
}}

function selectColor(idx) {{
  $$('.color-row').forEach(r => r.classList.remove('active'));
  document.querySelector(`.color-row[data-idx="${{idx}}"]`).classList.add('active');
  const grid = $('#previewGrid');
  grid.innerHTML = '';
  PREVIEW_KEYS.forEach(key => {{
    const safeKey = key.replace('/', '__').replace('.png', '');
    const cell = document.createElement('div');
    cell.className = 'preview-cell';
    cell.innerHTML = `
      <img src="data/masks/color_${{String(idx).padStart(2,'0')}}_${{safeKey}}.png">
      <div class="label">${{key}}</div>
    `;
    grid.appendChild(cell);
  }});
  $('#previewLabel').textContent = `🔍 当前高亮: ${{PALETTE[idx].hex}} (${{PALETTE[idx].count.toLocaleString()}} 像素)`;
}}

function exportJson() {{
  const roles = {{}};
  PALETTE.forEach((c, i) => {{
    const inp = document.querySelector(`.name-input[data-idx="${{i}}"]`);
    const name = inp.value.trim() || `color_${{String(i).padStart(2,'0')}}`;
    if (roles[name]) {{
      alert(`重复角色名: ${{name}} (色 ${{i}}). 请改一个唯一名字。`);
      inp.focus();
      return;
    }}
    roles[name] = c.hex;
  }});
  const out = {{
    "version": 1,
    "n_colors": PALETTE.length,
    "roles": roles,
    "_meta": PALETTE.map((c, i) => ({{
      idx: i, hex: c.hex, count: c.count,
      role: document.querySelector(`.name-input[data-idx="${{i}}"]`).value.trim()
    }}))
  }};
  $('#exportArea').value = JSON.stringify(out, null, 2);
  $('#exportArea').focus();
  $('#exportArea').select();
}}

function saveDraft() {{
  const data = {{}};
  $$('.name-input').forEach(inp => {{
    if (inp.value.trim()) data[inp.dataset.idx] = inp.value.trim();
  }});
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}}

function loadDraft() {{
  try {{
    const data = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}');
    $$('.name-input').forEach(inp => {{
      if (data[inp.dataset.idx]) inp.value = data[inp.dataset.idx];
    }});
  }} catch (_) {{}}
}}

function clearDraft() {{
  if (!confirm('清空所有命名？')) return;
  localStorage.removeItem(STORAGE_KEY);
  $$('.name-input').forEach(inp => inp.value = '');
}}

renderList();
loadDraft();
"""
    with open(os.path.join(out_dir, "app.js"), "w") as f:
        f.write(js)


def main():
    if os.path.exists(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(os.path.join(DATA_DIR, "masks"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "previews"), exist_ok=True)

    print(f"📊 收集像素…")
    all_pixels = collect_all_pixels()
    print(f"  像素总数: {len(all_pixels):,}")

    print(f"🎨 全集量化到 {N_COLORS} 色…")
    palette = derive_global_palette(all_pixels, N_COLORS)
    print(f"  调色板: {len(palette)} 色")

    # 统计每个色的实际使用量（基于 remap）
    print(f"📐 统计各色像素数…")
    indices_all = remap_to_palette(all_pixels, palette)
    counts = np.bincount(indices_all, minlength=N_COLORS)

    # 按使用量排序，重排 palette
    order = np.argsort(-counts)
    palette = palette[order]
    counts = counts[order]

    palette_meta = [
        {
            "idx": i,
            "hex": "#{:02x}{:02x}{:02x}".format(*[int(v) for v in palette[i]]),
            "rgb": [int(v) for v in palette[i]],
            "count": int(counts[i]),
        }
        for i in range(N_COLORS)
    ]
    with open(os.path.join(DATA_DIR, "palette.json"), "w") as f:
        json.dump(palette_meta, f, indent=2, ensure_ascii=False)

    # 渲染色卡总览
    render_palette_swatch(palette, counts, os.path.join(DATA_DIR, "palette_swatch.png"))

    # 处理代表性 sprite
    print(f"🖼️  量化代表性 sprite + 生成 {N_COLORS}×{len(PREVIEW_FRAMES)} 张高亮 mask…")
    preview_keys = []
    for state, frame in PREVIEW_FRAMES:
        src = os.path.join(ASSETS_DIR, state, frame)
        if not os.path.exists(src):
            print(f"  ⚠ 跳过 {state}/{frame} (不存在)")
            continue
        key = f"{state}/{frame}"
        preview_keys.append(key)
        safe_key = key.replace("/", "__").replace(".png", "")

        quant_rgba, indices, alpha = quantize_image(src, palette)
        Image.fromarray(quant_rgba, mode="RGBA").save(
            os.path.join(DATA_DIR, "previews", f"{safe_key}.png")
        )

        for color_idx in range(N_COLORS):
            mask_img = make_highlight(quant_rgba, indices, alpha, color_idx)
            mask_path = os.path.join(
                DATA_DIR, "masks",
                f"color_{color_idx:02d}_{safe_key}.png"
            )
            Image.fromarray(mask_img, mode="RGBA").save(mask_path)
        print(f"  ✓ {key}")

    # 写 HTML / JS
    write_html(OUT_DIR, N_COLORS, preview_keys)
    write_app_js(OUT_DIR, palette_meta, preview_keys)

    print(f"\n✅ 工具构建完成")
    print(f"   打开:  open {OUT_DIR}/index.html")
    print(f"   或:    file://{os.path.abspath(OUT_DIR)}/index.html")


if __name__ == "__main__":
    main()
