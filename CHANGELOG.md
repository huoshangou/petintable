# Changelog

所有版本迭代、已知问题与待办事项按时间倒序记录。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

---

## [Unreleased]

### Added
- **精确状态切换（Hook Heartbeat）**：新增 Claude Code VS Code Hook 插件 `vibe-status`，通过生命周期事件（`UserPromptSubmit` / `PreToolUse` / `PostToolUse` / `Stop`）向 Vibe 推送语义精确的状态心跳。完全取代 CPU 启发式作为首要检测手段。
  - 插件位置：`~/.claude/plugins/vibe-status/`
  - 端点：`POST /vibe/heartbeat`（兼容官方 Desktop Buddy 格式 `{ running, waiting }`）
  - TTL：30 秒无心跳后自动 fallback 到进程检测
- **三层检测架构**：Hook heartbeat → Session log watcher → Process + CPU fallback。
- **Layer 2 JSONL Watcher**：监听 `~/.claude/projects/*.jsonl` 增量变化，检测 `tool_use` 批准等待（2s 超时判 question）和 `tool_result` 用户批准（回 coding）。
- **Stop Hook 语义化**：`stop.js` 不再一律发 idle，而是读取 JSONL 最后一条 assistant message：
  - `stop_reason === "tool_use"` → 跳过（Layer 2 接管）
  - `stop_reason === "end_turn"` + 末尾匹配 question 正则 → `waiting:1`
  - `stop_reason === "end_turn"` + 普通陈述 → `waiting:0`
- **性能优化**：
  - Renderer 动画从 `requestAnimationFrame` 60fps 空转改为 `setTimeout` 按需调度（目标 fps 6-10），预计消除 ~2.5% 持续 CPU 占用。
  - 禁用 GPU  compositing（`--disable-gpu`），移除 GPU 进程（~88MB 内存）。
  - 轮询改为 `setTimeout` 递归：heartbeat 活跃时从每 2s 降低到每 10s，减少定时器唤醒次数。

### Fixed
- **状态机反应错误**：加入 macOS CPU 阈值检测（`CPU_THRESHOLD = 3.0`）。小鸟不再在用户 typing 时错误地播放 coding 动画；只有当 Agent（CC/OpenCode）进程 CPU ≥ 3% 时才进入 coding 状态。
- **动画水平位移与呼吸感**：重写 `pic/extract_sprites.py` 对齐逻辑（v2）。引入**脚锚点（Foot Anchor）**对齐 + **组级统一缩放（Group Scale）**：
  - 脚锚点：取 bbox 下方 25% 非透明像素的 x 中位数，替代 bbox 几何中心——鸟伸手/探头时脚不动，锚点稳定
  - 组级统一缩放：整组动画共用 `min(canvas/max_w, canvas/max_h, 1.0)`，消除逐帧独立缩放导致的「呼吸感」
  - knock 高度差从 5px+ 降至 1px，question 高度差 0px

### Changed
- 建立 `CLAUDE.md` 工程规范与 `CHANGELOG.md` 迭代日志，确保可交接。
- 更新 `README.md` 状态说明，区分 heartbeat 精确检测与进程检测 fallback。

### Known Issues
- **纯文本生成无 turn 结束信号**：Agent 生成文本期间若无 tool_use，heartbeat TTL（30s）过期后才回退。Layer 2 已覆盖 tool_use 场景，纯文本场景仍需 TTL。
- **Stop Hook 依赖 JSONL 文件**：若 Claude Code 未写入 JSONL（极少数情况）或文件权限问题，stop.js 会 fallback 到 idle。
- **Question pattern 是启发式正则**：中文/英文 question 检测基于末尾 200 字符正则匹配，可能误判（如陈述句含问号）或漏判（如委婉询问不含问号）。
- Windows 平台 CPU 检测未实现，仍回退到"进程存在即 coding"。
- `ps %cpu` 是进程生命周期平均 CPU，非严格瞬时采样；阈值 3.0 在大多数场景下有效，但极端长会话中可能漂移。

---

## [0.1.0] — 2025-04-21

### Added
- 初始版本：Electron 无边框透明窗口 + 64×64 canvas 像素鸟。
- 5 组动画状态：idle_no_glasses、equip_glasses、coding、question、knock。
- 自动进程检测（前台 terminal + CC/opencode 进程存在）。
- HTTP API (`localhost:3000/state`) 支持手动覆盖状态。
- 拖拽移动 + 透明区域点击穿透。
- GitHub Actions 自动构建 macOS / Windows。

### Known Issues (历史归档)
- [FIXED in Unreleased] 用户 typing 时小鸟错误进入 coding（进程存在即 coding，未区分用户/Agent）。
- [FIXED in Unreleased] typing / question 动画存在水平位移（单帧切分后按各自 bbox 居中导致）。
- question 状态无法自动检测，只能手动 API 触发（by design，但文档未清晰说明）。

---

## 待办池 (Backlog)

按优先级排序，完成时移至对应版本。

### High
- [ ] **Layer 2 日志监听**：解析 `~/.claude/projects/*.jsonl` 检测 turn 完成事件，消除 30s TTL 延迟。
- [ ] Windows 平台实现瞬时 CPU 检测，消除与 macOS 的行为差异。
- [x] ~~验证 CPU 阈值 3.0 在长会话（>1h）中的有效性~~ — 已被 Hook heartbeat 取代，优先级降低。

### Medium
- [ ] 增加 `idle_with_glasses` 状态：Agent 短暂暂停生成（CPU 低于阈值但 terminal 仍在前台），小鸟戴眼镜发呆，而非立即摘下眼镜。
- [ ] 为 coding/question 动画增加随机眨眼或微动作，减少循环单调感。
- [x] ~~自动同步脚本：`pic/sync_assets.py`~~ — `extract_sprites.py` 已内置 `sync_to_assets()`。

### Low
- [ ] 支持多显示器，记住窗口位置。
- [ ] 配置面板（右键菜单）调整阈值、开关 always-on-top。
- [ ] 响应系统深色/浅色主题，自动切换 bird 色调（远景）。

---

## 命名规范

- 版本号：`x.y.z`
  - `x`：重大架构或状态语义变更
  - `y`：新功能或新动画状态
  - `z`：bugfix、性能优化、文档更新
- 提交信息：中英双语，`type(scope): 中文描述 / English desc`
  - type: `feat`, `fix`, `docs`, `refactor`, `build`
  - scope: `watcher`, `anim`, `api`, `assets`, `build`
