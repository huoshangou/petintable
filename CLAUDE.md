# Vibe — 工程规范

> 定位：桌面宠物 = Agent 状态镜像。用户打字时小鸟休息，Agent 生成时小鸟工作。
> 原则：约束先行，文档驱动，可交接。

---

## 1. 状态机语义（改前先改文档）

| 状态 | 语义 | 触发 |
|------|------|------|
| idle | Agent 休息 | 无活跃 heartbeat / TTL 过期 |
| coding | Agent 生成中 | Hook heartbeat `running>0` |
| question | Agent 等确认 | Hook `waiting>0` / JSONL watcher tool_use pending / 手动 API |

自动路径：idle → equip_glasses(once) → coding(loop) ↔ question → knock(once) → remove_glasses(reverse) → idle

三层检测（优先级）：
1. **Hook heartbeat**（VS Code Claude Code）— `~/.claude/plugins/vibe-status/`
2. **JSONL watcher**（`~/.claude/projects/*.jsonl`）— tool_use pending / stop+question
3. **Process + CPU**（fallback）— CLI 版、OpenCode

---

## 2. 工程结构

```
petintable/
├── main.js              # Electron 主进程 + HTTP API + 三层检测
├── preload.js           # IPC 桥接
├── src/renderer/
│   ├── index.html       # 64×64 canvas
│   ├── styles.css
│   └── pet.js           # 动画状态机 + 交互
├── assets/sprites/      # 运行时资源（64×64 PNG）
├── pic/                 # 美术工作区
│   ├── assets/          # 原始 sprite sheet
│   ├── extract_sprites.py
│   └── verify_sprites.html
└── CLAUDE.md / CHANGELOG.md
```

边界：`pic/` → `extract_sprites.py` → `assets/sprites/`。`assets/sprites/` 只保留最终动画组。

---

## 3. 动画资产（脚锚点对齐 v2）

流程：`pic/assets/` 放入素材 → 更新 `STATE_MAP` → `python3 extract_sprites.py` → 浏览器打开 `verify_sprites.html` → 自动同步到 `assets/sprites/`。

对齐约束：
- **脚锚点**：bbox 下方 25% 非透明像素的 x 中位数，对齐 canvas 水平中心。
- **组级统一缩放**：`scale = min(canvas/max_w, canvas/max_h, 1.0)`，禁止逐帧独立缩放。
- **底部对齐**：角色站在同一基线。

验收：叠加对比脚重合（±1px），高度差 ≤ 2px，实播 5s 无抖动/呼吸感。
详细经验：`~/Desktop/obsidian-warehouse/my-llm-base-wiki/raw/sprite-anchor-alignment.md`

---

## 4. 性能约束

- 动画：`setTimeout` 按目标 FPS（6-10）调度，禁止 60fps `requestAnimationFrame` 空转。
- 轮询：heartbeat 活跃时 10s，fallback 时 2s。
- GPU：`--disable-gpu`，64×64 不需要硬件加速。
- 内存：Electron 基线 ~150MB，图片预加载 ~1MB。

---

## 5. 交接阅读顺序

1. `CLAUDE.md` → 理念与约束
2. `CHANGELOG.md` → 当前状态与已知问题
3. `main.js` → 检测层
4. `pet.js` → 动画与渲染
5. `extract_sprites.py` → 资产处理

**修改状态机语义必须先改本文档，再改代码。** 文档与代码不一致是最高优先级 bug。

---

## 6. 已知限制

- **VS Code only Hook**：CLI / OpenCode 走 Layer 3 fallback。
- **纯文本生成无 turn 结束信号**：无 tool_use 时 30s TTL 后才回退。
- **Windows**：CPU 检测未实现，fallback 行为较粗。
- **macOS Accessibility**：前台检测需要权限，否则默认 terminal 始终在前。
