# Vibe Layer 2 — JSONL Watcher 实现方案

> 任务对象：Kimi 2.6 执行
> 目标：把 question 状态检测从 30s TTL 降到 <2s，并修复 Stop 误判 idle 的 bug
> 预估工时：2-3 小时（含测试）

---

## 0. 背景速读（必看）

### 当前问题
1. **Stop 误判 idle**：`~/.claude/plugins/vibe-status/hooks/stop.js` 在每次 turn 结束时硬编码发送 `{running:0, waiting:0}` → 小鸟立即 idle。但 Stop 的真实语义是「turn 结束」，不等于「Agent 空闲」。模型可能刚问完用户「要继续吗？」就触发 Stop。
2. **PreToolUse 批准等待无信号**：当 Claude Code 弹出 Bash/Write 等工具的批准确认时，PreToolUse hook 在用户**点击批准之后**才触发；批准等待期间没有任何 hook，小鸟仍显示 coding。

### 已有架构（参考 `main.js:18-46`）
```
Layer 1: Hook heartbeat (精确, 已实现)
Layer 2: Session log watcher (TBD, 本方案要实现)
Layer 3: Process + CPU fallback (已实现)
```

### 不要动的东西
- `main.js:230-280` 的 HTTP server 接口契约 (`POST /vibe/heartbeat` body: `{running, waiting, source}`)
- `main.js:135-142` `heartbeatToState()` 的映射规则
- `src/renderer/pet.js` 的状态机和动画
- 资产目录 `assets/sprites/`

---

## 1. 验收标准（按此打分，全过才算完）

| # | 场景 | 期望表现 | 当前表现 |
|---|------|----------|----------|
| A1 | 用户提问后 Claude Code 开始生成 → 完成回答 → 普通陈述结尾 | 1-2s 内进入 idle | ✓ 已正常 |
| A2 | Claude Code 生成回答后**结尾问用户「要继续吗？」** | 进入 question 并保持 | ✗ 错误进 idle |
| A3 | Claude Code 调用 Bash 工具 → 弹出批准 prompt | 2s 内进入 question | ✗ 30s 内仍 coding |
| A4 | 用户批准 → 工具执行 | 立即回到 coding | ✓ 已正常（PreToolUse） |
| A5 | 多个并行 session（VS Code + 别的 cwd） | 任一 session 有事件即响应 | 需保证 |
| A6 | Vibe 重启 | 不重读历史 JSONL，只跟踪重启后新增内容 | 必须保证（防误触） |
| A7 | 关闭所有 Claude Code → 30s 后 | 回到 idle（Layer 3 fallback 接管） | ✓ 已正常 |

---

## 2. 实现拆分（两个 Phase，可独立提交）

### Phase 1：改造 stop.js — 区分「end_turn」与「question 结尾」

**文件**：`~/.claude/plugins/vibe-status/hooks/stop.js`

**当前代码**（已读，仅 5 行）：
```js
const { readStdin, notifyVibe } = require("./lib.js");
readStdin(() => {
  notifyVibe({ running: 0, waiting: 0, source: "Stop" });
});
```

**改造后逻辑**：
1. 读 stdin（Stop hook 输入包含 `session_id`、`transcript_path` 字段，**先 console.error 打印 input 字段名核实**，文档：https://docs.claude.com/en/docs/claude-code/hooks）
2. 用 `transcript_path`（如果有）或者根据 `cwd` 推算 JSONL 路径：
   - 路径模式：`~/.claude/projects/<encoded-cwd>/<session_id>.jsonl`
   - encoded-cwd 规则：把 `/` 替换为 `-`，例如 `/Users/mofashu` → `-Users-mofashu`
3. 读 JSONL 最后 50 行（防止文件过大），从后往前找最后一条 `type === "assistant"` 的 message
4. 取出 `message.stop_reason` 和 `message.content` 末尾文本：

| stop_reason | 末尾文本特征 | 动作 |
|-------------|--------------|------|
| `tool_use` | — | **不发心跳**（让 Layer 2 watcher 接管，避免误判） |
| `end_turn` | 末尾 200 字符匹配 question pattern（见下） | `notifyVibe({running:0, waiting:1, source:"Stop+question"})` |
| `end_turn` | 普通陈述 | `notifyVibe({running:0, waiting:0, source:"Stop"})` |
| 其他/解析失败 | — | `notifyVibe({running:0, waiting:0, source:"Stop+fallback"})` |

**Question pattern**（正则，宽松匹配，不要太严）：
```js
const QUESTION_PATTERNS = [
  /\?\s*$/,                              // 中英文问号结尾
  /？\s*$/,
  /\(\s*y\/n\s*\)/i,                     // (y/n)
  /\[\s*y\/n\s*\]/i,
  /Y\/N/,
  /要不要|要继续|是否|确认|要不要我|need.{0,5}confirm/i,
  /which.{0,30}\?/i,                     // "which option..."
  /shall.{0,20}\?/i,                     // "shall I..."
  /\b(yes|no)\b.{0,20}\?/i,
];
function isQuestion(text) {
  const tail = text.slice(-200);
  return QUESTION_PATTERNS.some(re => re.test(tail));
}
```

**`message.content` 末尾文本提取**：
- `content` 是数组，找最后一个 `type === "text"` 的元素，取 `.text`
- 如果末尾是 `tool_use` 类型，那 stop_reason 应该已经是 `"tool_use"`，按上表处理

**文件 IO 控制**：
- 用 Node 内置 `fs` 同步读，**不要引入新依赖**（lib.js 现在零依赖）
- 用 stat 拿文件大小，从末尾偏移 8KB 处读取（足够覆盖最后几条 message）
- 若读失败（文件不存在/损坏），退回到 `{running:0, waiting:0, source:"Stop+ioerr"}`，不要崩溃
- 整个 hook 必须在 5 秒内退出（`hooks.json` 的 timeout）

---

### Phase 2：main.js 新增 JSONL Watcher — 检测「等待批准」

**文件**：`/Users/mofashu/Desktop/petintable/main.js`

**位置**：在 `schedulePoll()` 函数后（约 177 行）插入新 section，在 `app.whenReady()` 中启动。

**核心思路**：
- 监听 `~/.claude/projects/` 下所有 jsonl 文件的追加写入
- 解析每条新增 line，根据 message 类型推断状态
- 这是 Layer 2，**必须尊重 Layer 1 的 heartbeatTTL**（不要覆盖 hook 的精确信号），仅在 hook 沉默或 hook 无法捕获的场景下接管

**实现细节**：

```js
// ── Layer 2: JSONL Watcher ──────────────────────────────
const fs = require("fs");
const PROJECTS_DIR = path.join(os.homedir(), ".claude", "projects");
const fileOffsets = new Map(); // path → 已读字节位置
const PENDING_TOOL_USE_TIMEOUT_MS = 2000; // tool_use 后 2s 无 result → 判 question
let pendingToolUseTimer = null;

function initWatcher() {
  if (!fs.existsSync(PROJECTS_DIR)) return;

  // 启动时记录所有 jsonl 当前 size，避免重读历史 (满足 A6)
  function snapshotExistingFiles() {
    const dirs = fs.readdirSync(PROJECTS_DIR);
    for (const d of dirs) {
      const sub = path.join(PROJECTS_DIR, d);
      if (!fs.statSync(sub).isDirectory()) continue;
      for (const f of fs.readdirSync(sub)) {
        if (!f.endsWith(".jsonl")) continue;
        const fp = path.join(sub, f);
        try { fileOffsets.set(fp, fs.statSync(fp).size); } catch (_) {}
      }
    }
  }
  snapshotExistingFiles();

  // 用 fs.watch 监听整个 projects 目录（递归 macOS 支持，Win 也支持）
  fs.watch(PROJECTS_DIR, { recursive: true }, (eventType, filename) => {
    if (!filename || !filename.endsWith(".jsonl")) return;
    const fp = path.join(PROJECTS_DIR, filename);
    handleJsonlChange(fp);
  });
}

function handleJsonlChange(fp) {
  let stat;
  try { stat = fs.statSync(fp); } catch (_) { return; }
  const lastOffset = fileOffsets.get(fp) ?? stat.size;
  if (stat.size <= lastOffset) {
    fileOffsets.set(fp, stat.size);
    return;
  }

  // 增量读
  const fd = fs.openSync(fp, "r");
  const buf = Buffer.alloc(stat.size - lastOffset);
  fs.readSync(fd, buf, 0, buf.length, lastOffset);
  fs.closeSync(fd);
  fileOffsets.set(fp, stat.size);

  const lines = buf.toString("utf8").split("\n").filter(Boolean);
  for (const line of lines) {
    let msg;
    try { msg = JSON.parse(line); } catch (_) { continue; }
    classifyAndAct(msg);
  }
}

function classifyAndAct(msg) {
  // 跳过非对话类记录（如 last-prompt 等元信息）
  if (!msg.type || (msg.type !== "assistant" && msg.type !== "user")) return;

  // assistant message + stop_reason === "tool_use"
  // → Agent 即将调用工具，可能等待 PreToolUse 批准
  // 启一个 2s 计时器，如果期间没看到对应 tool_result，就判 question
  if (msg.type === "assistant" && msg.message?.stop_reason === "tool_use") {
    if (pendingToolUseTimer) clearTimeout(pendingToolUseTimer);
    pendingToolUseTimer = setTimeout(() => {
      // 仍未收到 tool_result → 用户可能在看 Claude Code 的批准弹窗
      maybeSendStateFromWatcher("question", "Layer2:tool_use_pending");
    }, PENDING_TOOL_USE_TIMEOUT_MS);
    return;
  }

  // user message 含 tool_result → 用户已批准（或工具自动执行），回 coding
  if (msg.type === "user") {
    const content = msg.message?.content;
    const hasToolResult = Array.isArray(content) &&
      content.some(c => c?.type === "tool_result");
    if (hasToolResult) {
      if (pendingToolUseTimer) { clearTimeout(pendingToolUseTimer); pendingToolUseTimer = null; }
      maybeSendStateFromWatcher("coding", "Layer2:tool_result");
    }
    return;
  }
}

function maybeSendStateFromWatcher(state, source) {
  // 关键：尊重 Layer 1。若 heartbeat 仍活跃且不一致，让 hook 决定。
  // 但 question 的语义比 coding 更"渴望被显示"，给 watcher 一点优先权。
  if (heartbeatTTL > 0 && state === "coding" && currentState === "question") {
    return; // 不要把刚判断的 question 立刻推回 coding
  }
  if (currentState === state) return;
  console.log(`[Layer2] ${currentState} → ${state} (${source})`);
  sendState(state);
  // 不重置 heartbeatTTL，让 hook 继续正常工作
}
```

**在 `app.whenReady().then(...)` 中调用**（main.js:284 附近）：
```js
app.whenReady().then(() => {
  createWindow();
  startHttpServer();
  schedulePoll();
  initWatcher();   // ← 新增
  ...
});
```

---

## 3. 测试步骤（每条都要跑一遍）

### 3.1 单元验证（不开 Vibe）
```bash
# 测试 stop.js 的判定逻辑（写个临时测试 driver）
cd ~/.claude/plugins/vibe-status/hooks/
node -e '
const { execSync } = require("child_process");
// 模拟 stdin 输入 + 检查 console 输出
// 用法详见下面 "构造测试 fixture"
'
```

**构造测试 fixture**：
- 在 `/tmp/vibe-test/` 下生成几个假 JSONL 文件，覆盖：
  - 末尾是 `stop_reason:"end_turn"` + 普通文本
  - 末尾是 `stop_reason:"end_turn"` + 含 "要不要继续？"
  - 末尾是 `stop_reason:"tool_use"`
- 把 stop.js 的 `~/.claude/projects/...` 路径临时改成读 `/tmp/vibe-test/`，跑通三种情况

### 3.2 端到端验证（开 Vibe）
```bash
cd ~/Desktop/petintable
npm start
# 打开第二个终端
```

逐条对照 §1 验收表 A1-A7：
- **A2**：在 VS Code Claude Code 里让模型回答一个问题并以「要不要我继续？」结尾。观察小鸟应在 1-2s 内变 question（带眼镜+问号），不应回 idle。
- **A3**：让 Claude Code 执行 `bash ls`，**不要**点批准。观察小鸟应在 2-3s 内变 question。点批准后立即回 coding。
- **A6**：手动 `kill` 掉 Vibe 主进程后立刻 `npm start`，确认启动后没有读历史 JSONL 触发误状态切换（看 `[Layer2]` 日志应为空，直到下一次真实事件）。

### 3.3 回归验证
- A1、A4、A7（已正常的功能）必须不退化。
- 进程检测 fallback：关掉 VS Code 30s 后小鸟应回 idle。

---

## 4. 提交建议

分两个 commit，方便回滚：
1. `feat(stop): jsonl-aware semantic detection for Stop hook`
2. `feat(main): add Layer 2 jsonl watcher for tool_use pending detection`

每个 commit 单独跑一遍 §3.2 验收。

---

## 5. 不要做的事

- ❌ 不要引入新 npm 依赖（chokidar 等都不要）。fs.watch + 内置模块够用。
- ❌ 不要修改心跳协议字段（`{running, waiting, source}`）。
- ❌ 不要改 `pet.js` 渲染层。
- ❌ 不要"顺手"重构 main.js 的其他部分。本次只新增 Layer 2，不动 Layer 1/3。
- ❌ 不要给 question pattern 加复杂 NLP，正则够了。误判一两次比漏判好。
- ❌ 不要在 watcher 里写文件、不要打开网络请求。watcher 必须纯本地、零副作用。

---

## 6. 已知边界（不要尝试在本次 PR 里解决）

- **Claude Code 批准弹窗在 webview 里**：纯 webview UI 提示（不走 tool_use 的那种文本确认）暂时无法捕获。Layer 2 只覆盖工具调用类的批准。
- **OpenCode 不写 JSONL**：本方案对 OpenCode 无效，OpenCode 用户继续走 Layer 3 fallback。
- **多账号 / 多 ~/.claude 目录**：默认只监听当前用户主目录下的 .claude/projects/。

---

## 7. 完成后给 Steve 的反馈

跑完 §3 所有验收后，回复：
- 哪些验收通过、哪些失败
- 任何需要 Steve 确认的边界情况
- 如果 question pattern 有误判/漏判，列出具体反例和你的建议
- 提交的 commit hash
