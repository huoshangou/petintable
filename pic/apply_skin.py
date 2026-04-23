#!/usr/bin/env python3
"""
皮肤应用脚本：基于 _roles.json 的颜色角色定义，把原始 sprite 量化映射到指定皮肤色。

工作流:
  1. 读 assets/skins/_roles.json 得到 16 个角色 → 默认 HEX
  2. 读 assets/skins/<skin>.json 得到 overrides
  3. 合并：每角色最终色 = override 优先，否则继承默认
  4. 遍历 assets/sprites/ 每张 PNG：
       a. 每个非透明像素 → 找最近的默认角色色 → 得到角色索引
       b. 用该角色的最终色替换
  5. 输出到 assets/skins/<skin>/sprites/<state>/<frame>.png

用法:
  ./venv/bin/python apply_skin.py default              # 用默认色生成 default 皮肤（量化版）
  ./venv/bin/python apply_skin.py blueberry            # 应用蓝莓皮肤
  ./venv/bin/python apply_skin.py --all                # 一次性出所有 skins/*.json + default

输出:
  assets/skins/<skin_name>/sprites/<state>/<frame>.png
  assets/skins/<skin_name>/manifest.json   (该皮肤的最终颜色映射快照)
"""

import sys
import os
import json
import shutil
import argparse
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPRITES_SRC = os.path.join(ROOT, "assets", "sprites")
SKINS_DIR = os.path.join(ROOT, "assets", "skins")
ROLES_FILE = os.path.join(SKINS_DIR, "_roles.json")


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def load_roles():
    with open(ROLES_FILE) as f:
        data = json.load(f)
    role_names = list(data["roles"].keys())
    role_default_hex = [data["roles"][n] for n in role_names]
    role_default_rgb = np.array([hex_to_rgb(h) for h in role_default_hex], dtype=np.uint8)
    return role_names, role_default_hex, role_default_rgb


def load_skin(skin_name, role_names, role_default_hex):
    """返回该皮肤每个角色的最终 HEX/RGB（按 role_names 顺序）。"""
    if skin_name == "default":
        final_hex = list(role_default_hex)
    else:
        skin_path = os.path.join(SKINS_DIR, f"{skin_name}.json")
        if not os.path.exists(skin_path):
            raise FileNotFoundError(f"皮肤定义不存在: {skin_path}")
        with open(skin_path) as f:
            skin = json.load(f)
        overrides = skin.get("overrides", {})
        final_hex = [overrides.get(n, role_default_hex[i]) for i, n in enumerate(role_names)]
    final_rgb = np.array([hex_to_rgb(h) for h in final_hex], dtype=np.uint8)
    return final_hex, final_rgb


def apply_skin_to_image(src_path, default_rgb, final_rgb):
    """对单张 PNG 做：像素 → 最近默认色 → 替换为 final 色。"""
    img = np.array(Image.open(src_path).convert("RGBA"))
    rgb = img[:, :, :3].astype(np.int32)
    alpha = img[:, :, 3]

    flat = rgb.reshape(-1, 3)
    pal = default_rgb.astype(np.int32)
    dists = np.sum((flat[:, None, :] - pal[None, :, :]) ** 2, axis=2)
    indices = np.argmin(dists, axis=1).reshape(rgb.shape[:2])

    new_rgb = final_rgb[indices]
    out = np.dstack([new_rgb, alpha]).astype(np.uint8)
    return out


def process_skin(skin_name, role_names, role_default_hex, role_default_rgb):
    final_hex, final_rgb = load_skin(skin_name, role_names, role_default_hex)
    skin_out_dir = os.path.join(SKINS_DIR, skin_name, "sprites")
    if os.path.exists(skin_out_dir):
        shutil.rmtree(skin_out_dir)
    os.makedirs(skin_out_dir, exist_ok=True)

    file_count = 0
    for state in sorted(os.listdir(SPRITES_SRC)):
        state_dir = os.path.join(SPRITES_SRC, state)
        if not os.path.isdir(state_dir):
            continue
        out_state_dir = os.path.join(skin_out_dir, state)
        os.makedirs(out_state_dir, exist_ok=True)
        for frame in sorted(os.listdir(state_dir)):
            if not frame.endswith(".png"):
                continue
            src = os.path.join(state_dir, frame)
            out_arr = apply_skin_to_image(src, role_default_rgb, final_rgb)
            Image.fromarray(out_arr, mode="RGBA").save(os.path.join(out_state_dir, frame))
            file_count += 1

    # 写当前皮肤的 manifest 快照
    manifest = {
        "skin": skin_name,
        "n_colors": len(role_names),
        "final_palette": {n: final_hex[i] for i, n in enumerate(role_names)},
    }
    with open(os.path.join(SKINS_DIR, skin_name, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"  ✓ {skin_name}: {file_count} 帧 → assets/skins/{skin_name}/sprites/")


def list_skins():
    """返回所有可用皮肤名（包括 default）。"""
    skins = ["default"]
    for f in sorted(os.listdir(SKINS_DIR)):
        if f.endswith(".json") and not f.startswith("_"):
            skins.append(f[:-5])
    return skins


def main():
    parser = argparse.ArgumentParser(description="apply skin overrides to sprites")
    parser.add_argument("skin", nargs="?", help="皮肤名（不含 .json），或 'default'")
    parser.add_argument("--all", action="store_true", help="处理所有可用皮肤")
    args = parser.parse_args()

    role_names, role_default_hex, role_default_rgb = load_roles()
    print(f"📖 已加载 {len(role_names)} 个颜色角色")

    if args.all:
        skins = list_skins()
        print(f"🎨 处理全部 {len(skins)} 个皮肤: {', '.join(skins)}")
        for s in skins:
            process_skin(s, role_names, role_default_hex, role_default_rgb)
    elif args.skin:
        process_skin(args.skin, role_names, role_default_hex, role_default_rgb)
    else:
        print("用法: apply_skin.py <skin> 或 --all")
        print(f"可用皮肤: {', '.join(list_skins())}")
        sys.exit(1)

    print("\n✅ 完成")


if __name__ == "__main__":
    main()
