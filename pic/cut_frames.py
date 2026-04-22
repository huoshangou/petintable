#!/usr/bin/env python3
"""
帧切割脚本：改进绿幕抠图 + 逐帧切出 + 生成交互式标注 HTML
"""
import os
import json
import math
from PIL import Image, ImageFilter

RAW_DIR = "./raw_sprites"
OUTPUT_DIR = "./frames"
COLS = 4
ROWS = 2

# --- 改进绿幕抠图 ---
def remove_green_screen(img):
    """HSL 色相抠图 + 边缘羽化"""
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    w, h = img.size
    rgba = list(img.getdata())

    # 第一步：计算每个像素的绿幕强度（0=保留, 1=移除）
    green_strength = [0.0] * (w * h)
    for idx in range(w * h):
        r, g, b, a = rgba[idx]
        cmax = max(r, g, b)
        cmin = min(r, g, b)
        delta = cmax - cmin

        if delta < 5:
            # 近乎灰色/黑色/白色，不是绿幕
            green_strength[idx] = 0.0
            continue

        # HSL hue
        if cmax == g:
            hue = 60.0 * ((b - r) / delta + 2)
        elif cmax == r:
            hue = 60.0 * (((g - b) / delta) % 6)
        else:
            hue = 60.0 * ((r - g) / delta + 4)

        sat = delta / cmax
        lum = (cmax + cmin) / 2.0 / 255.0

        # 绿色判断：色相 60-180, 高饱和, 中等亮度
        if 60 <= hue <= 180 and sat > 0.20 and g > 40 and lum > 0.05:
            # 越饱和越绿，alpha 越强
            green_strength[idx] = min(sat * 1.5, 1.0)
        else:
            green_strength[idx] = 0.0

    # 第二步：2D 高斯羽化 alpha map（3x3 近似）
    # 先做水平模糊
    feather_r = 2
    blurred_h = [0.0] * (w * h)
    for y in range(h):
        for x in range(w):
            total = 0.0
            count = 0
            for dx in range(-feather_r, feather_r + 1):
                nx = x + dx
                if 0 <= nx < w:
                    total += green_strength[y * w + nx]
                    count += 1
            blurred_h[y * w + x] = total / max(count, 1)

    # 再做垂直模糊
    blurred = [0.0] * (w * h)
    for y in range(h):
        for x in range(w):
            total = 0.0
            count = 0
            for dy in range(-feather_r, feather_r + 1):
                ny = y + dy
                if 0 <= ny < h:
                    total += blurred_h[ny * w + x]
                    count += 1
            blurred[y * w + x] = total / max(count, 1)

    # 第三步：应用 alpha
    new_data = []
    for idx in range(w * h):
        r, g, b, orig_a = rgba[idx]
        # 移除像素的强度 = 羽化后的绿幕强度
        remove_alpha = min(blurred[idx], 1.0)
        new_alpha = int((1.0 - remove_alpha) * 255)
        new_data.append((r, g, b, new_alpha))

    img.putdata(new_data)
    return img


def cut_frames(img, cols, rows):
    """将 sprite sheet 切成独立帧"""
    w, h = img.size
    fw = w // cols
    fh = h // rows
    frames = []
    for row in range(rows):
        for col in range(cols):
            box = (col * fw, row * fh, (col + 1) * fw, (row + 1) * fh)
            frame = img.crop(box)
            # 裁掉多余空白边距，保留紧凑包围盒
            frame = auto_crop(frame)
            frames.append(frame)
    return frames, fw, fh


def auto_crop(img):
    """裁剪透明边距，保留 2px 最小边距"""
    bbox = img.getbbox()
    if bbox is None:
        return img
    # 保留 2px padding
    pad = 2
    x0 = max(0, bbox[0] - pad)
    y0 = max(0, bbox[1] - pad)
    x1 = min(img.width, bbox[2] + pad)
    y1 = min(img.height, bbox[3] + pad)
    return img.crop((x0, y0, x1, y1))


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    sources = sorted([
        f for f in os.listdir(RAW_DIR)
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif'))
        and not f.startswith('.')
    ])

    if not sources:
        print(f"错误: {RAW_DIR} 中没有图片")
        return

    all_animations = []

    for src_name in sources:
        src_path = os.path.join(RAW_DIR, src_name)
        base_name = os.path.splitext(src_name)[0]
        print(f"处理: {src_name}")

        img = Image.open(src_path)
        img = remove_green_screen(img)
        frames, fw, fh = cut_frames(img, COLS, ROWS)

        # 保存每帧
        anim_dir = os.path.join(OUTPUT_DIR, base_name)
        os.makedirs(anim_dir, exist_ok=True)

        frame_info = []
        for i, frame in enumerate(frames):
            fname = f"frame_{i:02d}.png"
            fpath = os.path.join(anim_dir, fname)
            frame.save(fpath, 'PNG')
            frame_info.append({
                'file': f"{base_name}/{fname}",
                'width': frame.width,
                'height': frame.height,
            })

        all_animations.append({
            'source': src_name,
            'name': base_name,
            'frame_count': len(frames),
            'frames': frame_info,
            'orig_frame_width': fw,
            'orig_frame_height': fh,
        })
        print(f"  → {len(frames)} 帧切出，保存到 {anim_dir}/")

    # 保存元数据 JSON
    meta = {
        'animations': all_animations,
        'cols': COLS,
        'rows': ROWS,
        'labels': {},
    }
    with open(os.path.join(OUTPUT_DIR, 'animations.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 生成标注用 HTML
    generate_label_html(all_animations)
    print(f"\n=== 完成 ===")
    print(f"切帧输出: {OUTPUT_DIR}/")
    print(f"元数据: {OUTPUT_DIR}/animations.json")
    print(f"标注工具: label_animations.html （浏览器打开即可）")


def generate_label_html(animations):
    """生成交互式标注 HTML：播放每个动画，让用户命名"""
    html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>动画标注工具</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0d0d1a;
    color: #fff;
    padding: 24px;
    min-height: 100vh;
}
h1 { color: #00d4aa; margin-bottom: 4px; }
.subtitle { color: #666; font-size: 14px; margin-bottom: 24px; }
.grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px;
}
.card {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 12px;
    padding: 16px;
    transition: border-color 0.2s;
}
.card:hover { border-color: rgba(0,212,170,0.4); }
.card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
}
.card-title { font-size: 15px; font-weight: 600; }
.frame-counter { font-size: 12px; color: #888; }
.preview-area {
    position: relative;
    width: 100%;
    height: 200px;
    background: repeating-conic-gradient(#1a1a2e 0% 25%, #111 0% 50%) 0 0 / 16px 16px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    margin-bottom: 12px;
    border: 1px solid rgba(255,255,255,0.08);
}
.preview-area canvas {
    image-rendering: pixelated;
    image-rendering: crisp-edges;
}
.controls {
    display: flex;
    gap: 8px;
    align-items: center;
    margin-bottom: 12px;
}
.controls button {
    padding: 6px 12px;
    background: rgba(255,255,255,0.1);
    border: 1px solid rgba(255,255,255,0.2);
    border-radius: 6px;
    color: #fff;
    cursor: pointer;
    font-size: 12px;
}
.controls button:hover { background: rgba(0,212,170,0.3); }
.controls button.active { background: #00d4aa; color: #000; }
.speed-label { font-size: 12px; color: #888; }
.speed-slider { flex: 1; }
.frame-strip {
    display: flex;
    gap: 4px;
    overflow-x: auto;
    padding: 4px 0;
    margin-bottom: 12px;
}
.frame-strip canvas {
    image-rendering: pixelated;
    image-rendering: crisp-edges;
    border: 2px solid transparent;
    border-radius: 4px;
    cursor: pointer;
    transition: border-color 0.15s;
    flex-shrink: 0;
}
.frame-strip canvas.current { border-color: #00d4aa; }
.frame-strip canvas:hover { border-color: rgba(0,212,170,0.5); }
.label-area { display: flex; gap: 8px; align-items: center; }
.label-area label { font-size: 12px; color: #888; white-space: nowrap; }
.label-area input, .label-area select {
    flex: 1;
    padding: 6px 10px;
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 6px;
    color: #fff;
    font-size: 13px;
}
.label-area select option { background: #1a1a2e; }
.footer {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    background: #0d0d1aee;
    border-top: 1px solid rgba(255,255,255,0.1);
    padding: 12px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.export-btn {
    padding: 10px 24px;
    background: #00d4aa;
    border: none;
    border-radius: 8px;
    color: #000;
    font-weight: 600;
    cursor: pointer;
    font-size: 14px;
}
.export-btn:hover { background: #00e8b8; }
.status { font-size: 13px; color: #888; }
</style>
</head>
<body>
<h1>动画标注工具</h1>
<div class="subtitle">点击播放每个动画 → 从下拉菜单选择或输入标签名 → 导出配置</div>
<div class="grid" id="grid"></div>
<div class="footer">
    <div class="status" id="status">标注后点击导出，生成 animations.json</div>
    <button class="export-btn" onclick="exportLabels()">导出配置</button>
</div>

<script>
const ANIMATIONS = ''' + json.dumps(animations, ensure_ascii=False) + ''';

// 预定义的标签选项（对应你的 6 个状态 + 自定义）
const PRESET_LABELS = [
    { value: '', text: '-- 选择标签 --' },
    { value: 'idle_no_glasses', text: 'idle_no_glasses (待机-无眼镜)' },
    { value: 'equip_glasses', text: 'equip_glasses (戴上眼镜)' },
    { value: 'coding', text: 'coding (敲键盘)' },
    { value: 'question', text: 'question (歪头疑问)' },
    { value: 'knock', text: 'knock (啄击屏幕)' },
    { value: 'remove_glasses', text: 'remove_glasses (摘下眼镜)' },
    { value: 'idle_with_glasses', text: 'idle_with_glasses (待机-戴眼镜)' },
    { value: '_custom', text: '✏️ 自定义...' },
];

const animStates = {};
let allImages = {};

async function loadAllImages() {
    const promises = [];
    for (const anim of ANIMATIONS) {
        for (const frame of anim.frames) {
            const p = new Promise((resolve) => {
                const img = new Image();
                img.onload = () => { allImages[frame.file] = img; resolve(); };
                img.onerror = () => resolve();
                img.src = 'frames/' + frame.file;
            });
            promises.push(p);
        }
    }
    await Promise.all(promises);
}

function buildCards() {
    const grid = document.getElementById('grid');
    ANIMATIONS.forEach((anim, idx) => {
        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = `
            <div class="card-header">
                <span class="card-title">${anim.name}</span>
                <span class="frame-counter">${anim.frame_count} 帧</span>
            </div>
            <div class="preview-area">
                <canvas id="canvas-${idx}"></canvas>
            </div>
            <div class="controls">
                <button onclick="togglePlay(${idx})" id="playbtn-${idx}">▶ 播放</button>
                <button onclick="stepFrame(${idx}, -1)">◀</button>
                <button onclick="stepFrame(${idx}, 1)">▶</button>
                <input type="range" class="speed-slider" min="50" max="500" value="150"
                       oninput="setSpeed(${idx}, this.value)">
                <span class="speed-label" id="speed-${idx}">150ms</span>
            </div>
            <div class="frame-strip" id="strip-${idx}"></div>
            <div class="label-area">
                <label>标签:</label>
                <select id="label-${idx}" onchange="onLabelChange(${idx}, this.value)">
                    ${PRESET_LABELS.map(l => `<option value="${l.value}">${l.text}</option>`).join('')}
                </select>
                <input type="text" id="custom-${idx}" placeholder="自定义标签名"
                       style="display:none" oninput="setLabel(${idx}, this.value)">
            </div>
        `;
        grid.appendChild(card);

        animStates[idx] = {
            currentFrame: 0,
            playing: false,
            speed: 150,
            interval: null,
            maxScale: 1,
        };

        // Build frame strip
        const strip = card.querySelector(`#strip-${idx}`);
        anim.frames.forEach((frame, fi) => {
            const c = document.createElement('canvas');
            c.width = frame.width;
            c.height = frame.height;
            c.title = `帧 ${fi}`;
            c.onclick = () => { animStates[idx].currentFrame = fi; drawFrame(idx); };
            strip.appendChild(c);
        });
    });
}

function onLabelChange(idx, value) {
    const customInput = document.getElementById(`custom-${idx}`);
    if (value === '_custom') {
        customInput.style.display = '';
        customInput.focus();
    } else {
        customInput.style.display = 'none';
    }
}

function setLabel(idx, value) {}

function togglePlay(idx) {
    const st = animStates[idx];
    if (st.playing) {
        clearInterval(st.interval);
        st.playing = false;
        document.getElementById(`playbtn-${idx}`).textContent = '▶ 播放';
    } else {
        st.playing = true;
        document.getElementById(`playbtn-${idx}`).textContent = '⏸ 暂停';
        st.interval = setInterval(() => {
            st.currentFrame = (st.currentFrame + 1) % ANIMATIONS[idx].frame_count;
            drawFrame(idx);
        }, st.speed);
    }
}

function stepFrame(idx, dir) {
    const st = animStates[idx];
    const total = ANIMATIONS[idx].frame_count;
    st.currentFrame = (st.currentFrame + dir + total) % total;
    drawFrame(idx);
}

function setSpeed(idx, ms) {
    animStates[idx].speed = parseInt(ms);
    document.getElementById(`speed-${idx}`).textContent = ms + 'ms';
    if (animStates[idx].playing) {
        clearInterval(animStates[idx].interval);
        animStates[idx].interval = setInterval(() => {
            animStates[idx].currentFrame = (animStates[idx].currentFrame + 1) % ANIMATIONS[idx].frame_count;
            drawFrame(idx);
        }, animStates[idx].speed);
    }
}

function drawFrame(idx) {
    const anim = ANIMATIONS[idx];
    const st = animStates[idx];
    const frame = anim.frames[st.currentFrame];
    const img = allImages[frame.file];
    if (!img) return;

    const canvas = document.getElementById(`canvas-${idx}`);
    const ctx = canvas.getContext('2d');

    // Scale to fit preview area (max 200px height)
    const maxH = 180;
    const scale = Math.min(maxH / frame.height, maxH / frame.width, 2);
    canvas.width = Math.round(frame.width * scale);
    canvas.height = Math.round(frame.height * scale);
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    // Update strip highlights
    const strip = document.getElementById(`strip-${idx}`);
    const canvases = strip.querySelectorAll('canvas');
    canvases.forEach((c, i) => {
        c.classList.toggle('current', i === st.currentFrame);
        // Draw strip frame thumbnails
        if (allImages[anim.frames[i].file]) {
            const tc = c.getContext('2d');
            tc.imageSmoothingEnabled = false;
            c.width = anim.frames[i].width;
            c.height = anim.frames[i].height;
            // Scale down for strip
            const ts = Math.min(1, 48 / anim.frames[i].height);
            c.style.height = Math.round(anim.frames[i].height * ts) + 'px';
            c.style.width = Math.round(anim.frames[i].width * ts) + 'px';
            tc.clearRect(0, 0, c.width, c.height);
            tc.drawImage(allImages[anim.frames[i].file], 0, 0);
        }
    });
}

function exportLabels() {
    const labels = {};
    let unlabeled = 0;
    ANIMATIONS.forEach((anim, idx) => {
        const select = document.getElementById(`label-${idx}`);
        const custom = document.getElementById(`custom-${idx}`);
        let label = select.value === '_custom' ? custom.value.trim() : select.value;
        if (label) {
            labels[anim.name] = label;
        } else {
            unlabeled++;
        }
    });

    if (unlabeled > 0) {
        if (!confirm(`还有 ${unlabeled} 个动画未标注，确定要导出吗？`)) return;
    }

    // Build output JSON
    const output = {
        animations: ANIMATIONS.map((anim, idx) => ({
            source: anim.source,
            name: anim.name,
            label: labels[anim.name] || '',
            frame_count: anim.frame_count,
            frames: anim.frames,
            orig_frame_width: anim.orig_frame_width,
            orig_frame_height: anim.orig_frame_height,
        })),
        labels: labels,
    };

    const blob = new Blob([JSON.stringify(output, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'labeled_animations.json';
    a.click();
    URL.revokeObjectURL(url);

    document.getElementById('status').textContent = `已导出！${Object.keys(labels).length} 个动画已标注`;
}

async function init() {
    buildCards();
    await loadAllImages();
    // Draw first frame of each
    ANIMATIONS.forEach((_, idx) => drawFrame(idx));
}

init();
</script>
</body>
</html>
'''

    with open('label_animations.html', 'w', encoding='utf-8') as f:
        f.write(html)


if __name__ == '__main__':
    main()