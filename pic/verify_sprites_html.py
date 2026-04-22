#!/usr/bin/env python3
"""
生成验证预览 HTML，逐帧展示所有导出的动画，
方便确认裁剪对齐和映射关系。
"""
import json
import os

SPRITES_DIR = "./sprites"
OUTPUT = "./verify_sprites.html"

def generate():
    with open(os.path.join(SPRITES_DIR, "manifest.json"), "r") as f:
        manifest = json.load(f)

    sections = []
    for state_name, info in manifest.items():
        frames_html = []
        for frame in info["frame_files"]:
            path = os.path.join(SPRITES_DIR, state_name, frame["file"])
            frames_html.append(
                f'<div class="frame">'
                f'<img src="{path}" />'
                f'<span>{frame["file"]}</span>'
                f'</div>'
            )
        src_tag = f'{info["source_file"]} row{info["row"]} col{info["col_range"][0]}-{info["col_range"][1]}'
        sections.append(
            f'<div class="anim-section">'
            f'<h3>{state_name} ({info["frames"]} frames) <small>{src_tag}</small></h3>'
            f'<div class="frames-row">{"".join(frames_html)}</div>'
            f'</div>'
        )

    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Sprite Export Verification</title>
<style>
body {{ background: #1a1a2e; color: #fff; font-family: monospace; padding: 20px; }}
.anim-section {{ margin: 30px 0; padding: 16px; background: rgba(255,255,255,0.05); border-radius: 8px; }}
h3 {{ color: #00d4aa; }} h3 small {{ color: #888; font-weight: normal; font-size: 12px; }}
.frames-row {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: flex-end; }}
.frame {{ display: flex; flex-direction: column; align-items: center; background: #000; border: 1px solid #333; padding: 4px; }}
.frame img {{ image-rendering: pixelated; image-rendering: crisp-edges; width: 64px; height: 64px; }}
.frame span {{ font-size: 10px; color: #888; margin-top: 2px; }}
.checker {{
  background-image: linear-gradient(45deg, #222 25%, transparent 25%),
    linear-gradient(-45deg, #222 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #222 75%),
    linear-gradient(-45deg, transparent 75%, #222 75%);
  background-size: 16px 16px;
}}
</style></head><body>
<h1>Sprite Export Verification</h1>
<p>检查每组动画的帧裁剪、对齐、映射是否正确。</p>
{"".join(sections)}
</body></html>'''

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✓ 验证页面: {OUTPUT}")


if __name__ == "__main__":
    generate()