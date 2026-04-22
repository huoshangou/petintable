#!/usr/bin/env python3
"""
绿幕抠图 + 精确状态机动画播放器
支持自定义每个状态的行列范围和播放模式
"""
import os
import sys
from PIL import Image
import glob
import re
import json

# 配置
RAW_DIR = "./raw_sprites"
OUTPUT_DIR = "./assets"
TOLERANCE = 80

# 动画状态定义（根据你的需求配置）
# row: 所在行（0-based）
# colStart/colEnd: 该状态在Sprite Sheet中的起始/结束列（包含）
# mode: loop(循环), once(单次), pingpong(往复)
ANIMATION_STATES = {
    'idle_no_glasses': {
        'name': 'Idle (无眼镜)',
        'row': 0,
        'colStart': 0,
        'colEnd': 7,  # 共8帧
        'mode': 'loop',
        'isDefault': True
    },
    'equip_glasses': {
        'name': '戴上眼镜',
        'row': 1,
        'colStart': 0,
        'colEnd': 3,  # 前4帧
        'mode': 'once'
    },
    'coding': {
        'name': '敲键盘 (戴眼镜)',
        'row': 2,
        'colStart': 0,
        'colEnd': 3,  # 前4帧
        'mode': 'loop'
    },
    'question': {
        'name': '歪头疑问',
        'row': 2,
        'colStart': 4,
        'colEnd': 7,  # 后4帧
        'mode': 'loop'
    },
    'knock': {
        'name': '啄击屏幕',
        'row': 3,
        'colStart': 0,
        'colEnd': 3,
        'mode': 'once'
    },
    'remove_glasses': {
        'name': '摘下眼镜',
        'row': 1,
        'colStart': 4,  # 戴上眼镜的逆向帧，或单独配置
        'colEnd': 7,
        'mode': 'once'
    }
}

def remove_green_screen(image_path, output_path):
    """移除绿幕背景，转为透明PNG"""
    img = Image.open(image_path)
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    pixels = img.load()
    width, height = img.size

    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if g > 150 and g > r + 40 and g > b + 40:
                pixels[x, y] = (0, 0, 0, 0)

    img.save(output_path, 'PNG')
    print(f"✓ 处理完成: {os.path.basename(image_path)}")
    return img

def generate_preview(processed_files):
    """生成状态机动画播放器 HTML"""

    img_info = processed_files[0]  # 使用第一个图片
    total_width = img_info['width']
    total_height = img_info['height']

    # 假设均匀分布的 4x8 网格
    frame_width = total_width // 8
    frame_height = total_height // 4

    # 构建状态配置
    states_config = {}
    for key, cfg in ANIMATION_STATES.items():
        states_config[key] = {
            'name': cfg['name'],
            'row': cfg['row'],
            'colStart': cfg['colStart'],
            'colEnd': cfg['colEnd'],
            'frames': cfg['colEnd'] - cfg['colStart'] + 1,
            'y': cfg['row'] * frame_height,
            'x': cfg['colStart'] * frame_width,
            'mode': cfg['mode'],
            'isDefault': cfg.get('isDefault', False)
        }

    sprite_config = json.dumps({
        'url': f'./assets/{img_info["filename"]}',
        'width': total_width,
        'height': total_height,
        'frameWidth': frame_width,
        'frameHeight': frame_height,
        'states': states_config
    })

    html_content = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Claude Code 宠物动画状态机</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            padding: 30px;
            color: #fff;
        }}
        h1 {{ text-align: center; margin-bottom: 10px; font-size: 24px; color: #00d4aa; }}
        .subtitle {{ text-align: center; color: #888; font-size: 14px; margin-bottom: 30px; }}
        .main-display {{
            display: flex;
            gap: 30px;
            max-width: 1200px;
            margin: 0 auto;
            flex-wrap: wrap;
        }}
        .preview-panel {{
            flex: 1;
            min-width: 300px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 16px;
            padding: 24px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .panel-title {{
            font-size: 14px;
            color: #888;
            margin-bottom: 16px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .animation-stage {{
            position: relative;
            width: 100%;
            height: 280px;
            background: #0d0d1a;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            border: 2px solid rgba(0, 212, 170, 0.3);
        }}
        .checkerboard {{
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background-image:
                linear-gradient(45deg, #1a1a2e 25%, transparent 25%),
                linear-gradient(-45deg, #1a1a2e 25%, transparent 25%),
                linear-gradient(45deg, transparent 75%, #1a1a2e 75%),
                linear-gradient(-45deg, transparent 75%, #1a1a2e 75%);
            background-size: 20px 20px;
            opacity: 0.3;
        }}
        .sprite-container {{
            position: relative;
            z-index: 1;
            width: var(--frame-width);
            height: var(--frame-height);
            overflow: hidden;
        }}
        .sprite-img {{
            position: absolute;
            top: 0;
            left: 0;
            image-rendering: pixelated;
            image-rendering: crisp-edges;
            transform: translate(calc(-1 * var(--offset-x)), calc(-1 * var(--offset-y)));
        }}
        .state-info {{
            margin-top: 16px;
            padding: 12px;
            background: rgba(0, 212, 170, 0.1);
            border-radius: 8px;
            border-left: 3px solid #00d4aa;
        }}
        .state-name {{ font-size: 16px; font-weight: bold; color: #00d4aa; }}
        .state-mode {{ font-size: 12px; color: #888; margin-top: 4px; }}
        .controls-panel {{
            flex: 1;
            min-width: 300px;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }}
        .control-card {{
            background: rgba(255, 255, 255, 0.05);
            border-radius: 16px;
            padding: 20px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .control-title {{ font-size: 14px; color: #888; margin-bottom: 12px; }}
        .state-buttons {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
        }}
        .state-btn {{
            padding: 12px 16px;
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 8px;
            color: #fff;
            cursor: pointer;
            font-size: 13px;
            transition: all 0.2s;
            text-align: left;
        }}
        .state-btn:hover {{
            background: rgba(0, 212, 170, 0.2);
            border-color: #00d4aa;
        }}
        .state-btn.active {{
            background: rgba(0, 212, 170, 0.3);
            border-color: #00d4aa;
            box-shadow: 0 0 10px rgba(0, 212, 170, 0.3);
        }}
        .mode-badge {{
            display: inline-block;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 10px;
            margin-left: 6px;
            background: rgba(255, 255, 255, 0.2);
        }}
        .state-btn.active .mode-badge.loop {{ background: #00d4aa; color: #000; }}
        .state-btn.active .mode-badge.once {{ background: #ff9500; color: #000; }}
        .state-btn.active .mode-badge.pingpong {{ background: #bf5af2; color: #fff; }}
        .speed-control {{
            margin-top: 16px;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .speed-control label {{ font-size: 12px; color: #888; }}
        .speed-control input {{ flex: 1; }}
        .speed-value {{ font-size: 12px; color: #00d4aa; min-width: 40px; }}
        .workflow-section {{
            background: rgba(255, 255, 255, 0.05);
            border-radius: 16px;
            padding: 20px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .workflow-title {{ font-size: 14px; color: #888; margin-bottom: 12px; }}
        .workflow-list {{
            list-style: none;
            font-size: 13px;
            color: #ccc;
            line-height: 1.8;
        }}
        .workflow-list li {{
            padding: 6px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }}
        .workflow-list li:last-child {{ border-bottom: none; }}
        .highlight {{ color: #00d4aa; font-weight: bold; }}
        .frame-info {{
            margin-top: 8px;
            font-size: 11px;
            color: #666;
        }}
    </style>
</head>
<body>
    <h1>🐦 Claude Code 宠物动画状态机</h1>
    <div class="subtitle">精确控制每个动画状态的行列范围</div>

    <div class="main-display">
        <div class="preview-panel">
            <div class="panel-title">Animation Preview</div>
            <div class="animation-stage">
                <div class="checkerboard"></div>
                <div class="sprite-container" id="sprite-container"
                     style="--frame-width: 176px; --frame-height: 192px;">
                    <img class="sprite-img" id="sprite-img" src="" alt="">
                </div>
            </div>
            <div class="state-info">
                <div class="state-name" id="current-state">Idle (无眼镜)</div>
                <div class="state-mode" id="current-mode">模式: 循环播放</div>
                <div class="frame-info" id="frame-info">帧: 0/8</div>
            </div>
            <div class="speed-control">
                <label>播放速度:</label>
                <input type="range" id="speed-slider" min="0.2" max="3" step="0.1" value="1">
                <span class="speed-value" id="speed-value">1.0x</span>
            </div>
        </div>

        <div class="controls-panel">
            <div class="control-card">
                <div class="control-title">状态切换 / State Switch</div>
                <div class="state-buttons" id="state-buttons"></div>
            </div>

            <div class="workflow-section">
                <div class="workflow-title">动画状态机规则</div>
                <ul class="workflow-list">
                    <li><span class="highlight">Idle (无眼镜)</span> - 默认循环动画</li>
                    <li><span class="highlight">戴上眼镜</span> - 单次播放，完成后自动切到 Coding</li>
                    <li><span class="highlight">敲键盘</span> - 循环动画 (戴眼镜状态)</li>
                    <li><span class="highlight">歪头疑问</span> - 循环动画 (Y/N确认时)</li>
                    <li><span class="highlight">啄击屏幕</span> - 单次播放 (提醒)</li>
                    <li><span class="highlight">摘下眼镜</span> - 单次播放，回到 Idle</li>
                </ul>
            </div>
        </div>
    </div>

    <script>
        const SPRITE_CONFIG = {sprite_config};

        let currentState = null;
        let currentFrame = 0;
        let animationId = null;
        let playDirection = 1;
        let lastTime = 0;
        let frameDuration = 150;

        function init() {{
            const container = document.getElementById('sprite-container');
            const img = document.getElementById('sprite-img');

            // 设置容器和图像尺寸
            container.style.setProperty('--frame-width', SPRITE_CONFIG.frameWidth + 'px');
            container.style.setProperty('--frame-height', SPRITE_CONFIG.frameHeight + 'px');
            img.src = SPRITE_CONFIG.url;
            img.style.width = SPRITE_CONFIG.width + 'px';
            img.style.height = SPRITE_CONFIG.height + 'px';

            // 生成状态按钮
            generateButtons();

            // 切换到默认状态
            const defaultState = Object.entries(SPRITE_CONFIG.states)
                .find(([k, v]) => v.isDefault)?.[0] || Object.keys(SPRITE_CONFIG.states)[0];
            switchState(defaultState);

            // 启动动画循环
            requestAnimationFrame(animate);
        }}

        function generateButtons() {{
            const container = document.getElementById('state-buttons');
            container.innerHTML = '';

            Object.entries(SPRITE_CONFIG.states).forEach(([key, state]) => {{
                const btn = document.createElement('button');
                btn.className = 'state-btn' + (state.isDefault ? ' active' : '');
                btn.dataset.state = key;

                let modeText = state.mode === 'loop' ? '循环' :
                               state.mode === 'once' ? '单次' : '往复';
                let modeClass = state.mode;

                btn.innerHTML = state.name + '<span class="mode-badge ' + modeClass + '">' + modeText + '</span>';
                btn.onclick = () => switchState(key);
                container.appendChild(btn);
            }});
        }}

        function switchState(stateKey) {{
            currentState = stateKey;
            currentFrame = 0;
            playDirection = 1;

            const state = SPRITE_CONFIG.states[stateKey];

            // 更新UI
            document.getElementById('current-state').textContent = state.name;
            document.getElementById('current-mode').textContent =
                '模式: ' + (state.mode === 'loop' ? '循环播放' :
                           state.mode === 'once' ? '单次播放' : '往复循环');

            // 更新按钮状态
            document.querySelectorAll('.state-btn').forEach(btn => {{
                btn.classList.toggle('active', btn.dataset.state === stateKey);
            }});

            updateFrame();
        }}

        function updateFrame() {{
            const state = SPRITE_CONFIG.states[currentState];
            const img = document.getElementById('sprite-img');

            // 计算当前帧在 Sprite Sheet 中的位置
            const currentCol = state.colStart + currentFrame;
            const x = currentCol * SPRITE_CONFIG.frameWidth;
            const y = state.y;

            // 使用 CSS transform 移动图像，而不是 background-position
            img.style.setProperty('--offset-x', x + 'px');
            img.style.setProperty('--offset-y', y + 'px');

            // 更新帧信息
            document.getElementById('frame-info').textContent =
                '帧: ' + (currentFrame + 1) + '/' + state.frames +
                ' | 行: ' + (state.row + 1) + ' 列: ' + (currentCol + 1);
        }}

        function animate(timestamp) {{
            if (!lastTime) lastTime = timestamp;
            const delta = timestamp - lastTime;

            if (delta >= frameDuration) {{
                const state = SPRITE_CONFIG.states[currentState];

                if (state.mode === 'pingpong') {{
                    // 往复模式
                    currentFrame += playDirection;
                    if (currentFrame >= state.frames - 1) {{
                        playDirection = -1;
                        currentFrame = state.frames - 1;
                    }} else if (currentFrame <= 0) {{
                        playDirection = 1;
                        currentFrame = 0;
                    }}
                }} else {{
                    // 正常或单次模式
                    currentFrame++;
                    if (currentFrame >= state.frames) {{
                        if (state.mode === 'once') {{
                            // 单次播放完成，处理自动切换
                            handleOnceComplete(stateKey);
                            lastTime = timestamp;
                            animationId = requestAnimationFrame(animate);
                            return;
                        }}
                        currentFrame = 0;
                    }}
                }}

                updateFrame();
                lastTime = timestamp;
            }}

            animationId = requestAnimationFrame(animate);
        }}

        function handleOnceComplete(stateKey) {{
            if (stateKey === 'equip_glasses') {{
                setTimeout(() => switchState('coding'), 200);
            }} else if (stateKey === 'knock') {{
                setTimeout(() => switchState('idle_no_glasses'), 300);
            }} else if (stateKey === 'remove_glasses') {{
                setTimeout(() => switchState('idle_no_glasses'), 200);
            }}
        }}

        // 速度控制
        document.getElementById('speed-slider').addEventListener('input', (e) => {{
            const speed = parseFloat(e.target.value);
            frameDuration = 150 / speed;
            document.getElementById('speed-value').textContent = speed.toFixed(1) + 'x';
        }});

        // 启动
        init();
    </script>
</body>
</html>
'''

    with open('preview.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"\n✓ 生成精确状态机动画播放器: preview.html")

def main():
    if not os.path.exists(RAW_DIR):
        print(f"错误: {RAW_DIR} 文件夹不存在")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    image_extensions = ('*.png', '*.jpg', '*.jpeg', '*.gif', '*.bmp')
    image_files = []
    for ext in image_extensions:
        image_files.extend(glob.glob(os.path.join(RAW_DIR, ext)))

    if not image_files:
        print(f"错误: {RAW_DIR} 中没有找到图片文件")
        sys.exit(1)

    print(f"找到 {len(image_files)} 个图片文件\n")

    processed = []
    for img_path in sorted(image_files):
        filename = os.path.basename(img_path)
        name, ext = os.path.splitext(filename)
        output_path = os.path.join(OUTPUT_DIR, name + '.png')

        try:
            img = remove_green_screen(img_path, output_path)
            processed.append({
                'filename': name + '.png',
                'width': img.width,
                'height': img.height
            })
        except Exception as e:
            print(f"✗ 处理失败 {filename}: {e}")

    if processed:
        generate_preview(processed)
        print(f"\n=== 处理完成 ===")
        print(f"透明图片: {OUTPUT_DIR}/")
        print(f"状态机预览: preview.html")
        print(f"\n动画状态配置:")
        for key, cfg in ANIMATION_STATES.items():
            frames = cfg['colEnd'] - cfg['colStart'] + 1
            print(f"  - {cfg['name']}: 第{cfg['row']+1}行, 列{cfg['colStart']+1}-{cfg['colEnd']+1} ({frames}帧)")
    else:
        print("\n没有成功处理任何图片")

if __name__ == '__main__':
    main()
