# Vibe 皮肤系统 + 状态机数据驱动 — 实现方案

> 任务对象：Kimi 2.6 执行
> 目标：pet.js 从 STATES 硬编码 → manifest 驱动；支持运行时皮肤切换
> 预估工时：2-3 小时（Phase 1）+ 30 分钟（Phase 2 右键菜单）

---

## 0. 背景速读（必看）

### 已就绪的基础设施
- `assets/skins/_roles.json` — 16 个颜色角色定义 + 默认 HEX
- `assets/skins/<skin>.json` — 各皮肤的 overrides（已有 `blueberry` `mint`）
- `assets/skins/<skin>/sprites/<state>/<frame>.png` — `apply_skin.py --all` 已生成
- `assets/skins/<skin>/manifest.json` — 该皮肤的最终颜色快照
- `pic/apply_skin.py` — 添加新皮肤后跑 `./venv/bin/python apply_skin.py <name>` 即可

### 当前问题
[`src/renderer/pet.js`](src/renderer/pet.js) 把所有东西硬编码：
- `STATES` 对象（line 6-48）：路径写死 `../../assets/sprites/<state>`
- `computeAnimSequence()`（line 95-119）：转换规则用 `if (hasGlasses)` 硬编码
- 没有皮肤概念

→ 加新动画/换皮肤都要改 JS 代码。

### 不动的东西
- `assets/skins/` 目录结构（已建好的不要重组）
- `apply_skin.py`、`extract_sprites.py`、`build_palette_picker.py`
- `assets/sprites/`（原始 sprite，作为皮肤生成的源头保留）
- Layer 1/2/3 状态检测（`main.js` 检测层逻辑、Hook 插件）
- 拖拽、点击穿透、命中检测逻辑

---

## 1. 验收标准

| # | 验证 | 期望 |
|---|------|------|
| V1 | 启动 Vibe，默认显示 `default` 皮肤 | 视觉与原版一致（量化无损） |
| V2 | `curl 'http://localhost:3000/skin?name=blueberry'` | 200ms 内小鸟变蓝；眼镜/键盘/问号保留原色 |
| V3 | `curl 'http://localhost:3000/skin?name=mint'` | 同上变绿 |
| V4 | `curl 'http://localhost:3000/skin?name=不存在'` | 返回 4xx + JSON 错误，不崩 |
| V5 | `curl 'http://localhost:3000/skins/list'` | 返回 `["default","blueberry","mint"]` 之类 |
| V6 | 切换皮肤后退出 Vibe，重启 | 还是上次选的皮肤（持久化） |
| V7 | 切换皮肤时小鸟正在播 coding 动画 | 切换后立即继续 coding，不丢动画状态 |
| V8 | 任意添加一个新皮肤 JSON + 跑 `apply_skin.py <new>`，不重启 Vibe | `curl /skins/list` 能看到新皮肤 |
| V9 | 状态机重构后所有原有过渡正常 | idle ↔ coding（戴眼镜）、coding → idle（knock + 摘眼镜）、equip 一次性、knock 一次性 |
| V10 | 右键小鸟弹菜单，列出可用皮肤，点击切换 | 立即生效 |

---

## 2. 实现方案

### Phase 1：动画 manifest + 皮肤切换 API（核心，单 commit）

#### 2.1 新增 `assets/animation_manifest.json`

定义状态机参数（所有皮肤共享，因为同一只鸟的动作集合不变）：

```json
{
  "version": 1,
  "default_state": "idle_no_glasses",
  "default_tag": "no_glasses",
  "states": {
    "idle_no_glasses": { "frames": 8, "mode": "loop", "fps": 6 },
    "equip_glasses":   { "frames": 8, "mode": "once", "fps": 10, "sets_tag": "glasses" },
    "coding":          { "frames": 8, "mode": "loop", "fps": 8 },
    "question":        { "frames": 8, "mode": "loop", "fps": 6 },
    "knock":           { "frames": 8, "mode": "once", "fps": 10 },
    "remove_glasses":  { "frames": 8, "mode": "once", "fps": 10, "reverse": true, "source": "equip_glasses", "sets_tag": "no_glasses" }
  },
  "transitions": {
    "idle_no_glasses": [
      { "if_tag": "glasses",    "sequence": ["knock", "remove_glasses", "idle_no_glasses"] },
      { "default": true,        "sequence": ["idle_no_glasses"] }
    ],
    "coding": [
      { "if_tag": "no_glasses", "sequence": ["equip_glasses", "coding"] },
      { "default": true,        "sequence": ["coding"] }
    ],
    "question": [
      { "if_tag": "no_glasses", "sequence": ["equip_glasses", "question"] },
      { "default": true,        "sequence": ["question"] }
    ]
  }
}
```

**字段语义**：
- `states.<name>.source`：可选，复用其他状态的 sprite 目录（如 `remove_glasses` 用 `equip_glasses` 的图反向播）
- `states.<name>.sets_tag`：状态播放完后把 hasGlasses 的 tag 切到这个值
- `transitions.<logical>`：按顺序匹配第一个 `if_tag === currentTag` 的条目，否则用 `default: true`

#### 2.2 改造 `pet.js` 为 manifest 解释器

完整重写思路（不要在原文件上 edit，直接覆盖）：

```js
(function () {
  const canvas = document.getElementById("pet");
  const ctx = canvas.getContext("2d");

  let manifest = null;
  let currentSkin = "default";
  let images = {};            // { state_name: [Image, ...] }
  let currentAnimState = null;
  let currentTag = null;      // 当前佩戴标签
  let frameIndex = 0;
  let animQueue = null;
  let animTimer = null;
  let pendingLogicalState = null;  // 切皮肤时缓存
  let dragStart = null;

  // ── Boot ───────────────────────────────────────────────
  async function boot() {
    manifest = await fetch("../../assets/animation_manifest.json").then(r => r.json());
    currentSkin = await window.petAPI.getCurrentSkin();
    currentAnimState = manifest.default_state;
    currentTag = manifest.default_tag;
    await preloadAll(currentSkin);
    drawFrame();
    startTicking();
  }

  // ── Preload (per skin) ─────────────────────────────────
  function preloadAll(skin) {
    const newImages = {};
    const promises = [];
    for (const [name, cfg] of Object.entries(manifest.states)) {
      const sourceName = cfg.source || name;
      const dir = `../../assets/skins/${skin}/sprites/${sourceName}`;
      const arr = [];
      for (let i = 0; i < cfg.frames; i++) {
        const idx = String(i).padStart(2, "0");
        const img = new Image();
        arr.push(img);
        promises.push(new Promise(resolve => {
          img.onload = resolve;
          img.onerror = () => { console.error("Failed to load", img.src); resolve(); };
          img.src = `${dir}/frame_${idx}.png`;
        }));
      }
      newImages[name] = arr;
    }
    return Promise.all(promises).then(() => { images = newImages; });
  }

  // ── Skin switch ────────────────────────────────────────
  async function switchSkin(skinName) {
    if (skinName === currentSkin) return;
    try {
      await preloadAll(skinName);
      currentSkin = skinName;
      drawFrame();  // 立刻用新皮肤重绘当前帧，不打断动画
    } catch (err) {
      console.error("[skin] switch failed:", err);
    }
  }

  // ── Transitions ────────────────────────────────────────
  function computeAnimSequence(logicalState) {
    const rules = manifest.transitions[logicalState];
    if (!rules) return [logicalState];
    for (const rule of rules) {
      if (rule.default || rule.if_tag === currentTag) {
        return [...rule.sequence];
      }
    }
    return [logicalState];
  }

  function transitionTo(logicalState) {
    playSequence(computeAnimSequence(logicalState));
  }

  function playSequence(seq) {
    if (seq.length === 0) return;
    const first = seq.shift();
    animQueue = seq.length > 0 ? seq : null;
    currentAnimState = first;
    frameIndex = 0;
    drawFrame();
    startTicking();
  }

  // ── Render loop ────────────────────────────────────────
  function tick() {
    const cfg = manifest.states[currentAnimState];
    if (!cfg) { animTimer = null; return; }
    frameIndex++;
    if (cfg.mode === "once" && frameIndex >= cfg.frames) {
      // 播完，更新 tag
      if (cfg.sets_tag) currentTag = cfg.sets_tag;
      if (animQueue && animQueue.length > 0) {
        playSequence(animQueue);
        return;
      }
      frameIndex = cfg.frames - 1;
      drawFrame();
      animTimer = null;
      return;
    }
    if (cfg.mode === "loop") frameIndex = frameIndex % cfg.frames;
    drawFrame();
    animTimer = setTimeout(tick, 1000 / cfg.fps);
  }

  function startTicking() {
    if (animTimer) clearTimeout(animTimer);
    animTimer = setTimeout(tick, 1000 / manifest.states[currentAnimState].fps);
  }

  function drawFrame() {
    const cfg = manifest.states[currentAnimState];
    if (!cfg) return;
    let idx = frameIndex;
    if (cfg.reverse) idx = cfg.frames - 1 - frameIndex;
    const img = images[currentAnimState] ? images[currentAnimState][idx] : null;
    ctx.clearRect(0, 0, 64, 64);
    if (img && img.complete && img.naturalWidth > 0) {
      ctx.drawImage(img, 0, 0, 64, 64);
    }
  }

  // ── IPC ────────────────────────────────────────────────
  window.petAPI.onStateChange((state) => transitionTo(state));
  window.petAPI.onSkinChange((skin) => switchSkin(skin));

  // ── Drag / hitbox（保持原样，不要改） ─────────────────
  function isPixelTransparent(x, y) {
    return ctx.getImageData(x, y, 1, 1).data[3] === 0;
  }
  canvas.addEventListener("mousemove", (e) => {
    const transparent = isPixelTransparent(e.offsetX, e.offsetY);
    window.petAPI.setIgnoreMouseEvents(transparent);
    canvas.style.cursor = transparent ? "default" : "grab";
  });
  canvas.addEventListener("mousedown", (e) => {
    if (isPixelTransparent(e.offsetX, e.offsetY)) return;
    dragStart = { x: e.screenX, y: e.screenY };
    canvas.style.cursor = "grabbing";
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragStart) return;
    const dx = e.screenX - dragStart.x;
    const dy = e.screenY - dragStart.y;
    dragStart = { x: e.screenX, y: e.screenY };
    window.petAPI.moveWindow(dx, dy);
  });
  window.addEventListener("mouseup", () => {
    dragStart = null;
    canvas.style.cursor = "grab";
  });

  boot();
})();
```

#### 2.3 改造 `main.js` — 皮肤管理 + HTTP API

**新增模块（在 main.js 顶部 require 之后）**：

```js
const SKINS_DIR = path.join(__dirname, "assets", "skins");
const CONFIG_PATH = path.join(app.getPath("userData"), "vibe-config.json");

let currentSkin = "default";

function loadConfig() {
  try {
    const data = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
    if (typeof data.skin === "string") currentSkin = data.skin;
  } catch (_) { /* first run */ }
}

function saveConfig() {
  try {
    fs.mkdirSync(path.dirname(CONFIG_PATH), { recursive: true });
    fs.writeFileSync(CONFIG_PATH, JSON.stringify({ skin: currentSkin }), "utf8");
  } catch (e) { console.error("[config] save failed:", e); }
}

function listSkins() {
  // 一个皮肤合法的判断：assets/skins/<name>/sprites/ 目录存在
  if (!fs.existsSync(SKINS_DIR)) return [];
  return fs.readdirSync(SKINS_DIR).filter(name => {
    const sub = path.join(SKINS_DIR, name);
    return fs.statSync(sub).isDirectory()
      && fs.existsSync(path.join(sub, "sprites"));
  }).sort();
}

function setSkin(name) {
  const valid = listSkins();
  if (!valid.includes(name)) {
    return { ok: false, error: "skin not found", valid };
  }
  currentSkin = name;
  saveConfig();
  if (win && !win.isDestroyed()) {
    win.webContents.send("skin-change", name);
  }
  return { ok: true, skin: name };
}
```

**在 `app.whenReady().then(...)` 里加 `loadConfig()`**（在 createWindow 之前）。

**HTTP server 加两个 route**：
```js
if (url.pathname === "/skin") {
  const name = url.searchParams.get("name");
  res.writeHead(name ? 200 : 400, { "Content-Type": "application/json" });
  if (!name) {
    res.end(JSON.stringify({ error: "missing name", valid: listSkins() }));
    return;
  }
  const result = setSkin(name);
  res.writeHead(result.ok ? 200 : 404, { "Content-Type": "application/json" });
  res.end(JSON.stringify(result));
  return;
}
if (url.pathname === "/skins/list") {
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ current: currentSkin, available: listSkins() }));
  return;
}
```

注意：上面 if 块里 `res.writeHead` 被调用了两次（一次是 missing name 的 400，一次是 setSkin 后），整理一下避免双调用：

```js
if (url.pathname === "/skin") {
  const name = url.searchParams.get("name");
  if (!name) {
    res.writeHead(400, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "missing name", valid: listSkins() }));
    return;
  }
  const result = setSkin(name);
  res.writeHead(result.ok ? 200 : 404, { "Content-Type": "application/json" });
  res.end(JSON.stringify(result));
  return;
}
```

**新增 IPC handler**：renderer 启动时要拿当前 skin。

```js
ipcMain.handle("get-current-skin", () => currentSkin);
```

#### 2.4 改造 `preload.js`

```js
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("petAPI", {
  onStateChange: (callback) => ipcRenderer.on("state-change", (_, s) => callback(s)),
  onSkinChange:  (callback) => ipcRenderer.on("skin-change",  (_, s) => callback(s)),
  getCurrentSkin: () => ipcRenderer.invoke("get-current-skin"),
  setIgnoreMouseEvents: (ignore) => ipcRenderer.send("set-ignore-mouse-events", ignore),
  moveWindow: (dx, dy) => ipcRenderer.send("window-move", dx, dy),
});
```

（保留原有方法，仅新增 onSkinChange 和 getCurrentSkin。）

---

### Phase 2：右键菜单切换器（次 commit，必做）

**用 Electron 原生 Menu**（不在 renderer 里写 DOM 菜单，原生菜单更轻量、风格统一）。

在 `main.js` 加：

```js
const { Menu } = require("electron");

function showSkinMenu() {
  const skins = listSkins();
  const template = skins.map(name => ({
    label: (name === currentSkin ? "✓ " : "  ") + name,
    click: () => setSkin(name),
  }));
  template.push({ type: "separator" });
  template.push({
    label: "退出 Vibe",
    click: () => app.quit(),
  });
  const menu = Menu.buildFromTemplate(template);
  if (win) menu.popup({ window: win });
}

ipcMain.on("show-context-menu", () => showSkinMenu());
```

**preload.js 暴露**：
```js
showContextMenu: () => ipcRenderer.send("show-context-menu"),
```

**pet.js 监听右键**：
```js
canvas.addEventListener("contextmenu", (e) => {
  e.preventDefault();
  if (isPixelTransparent(e.offsetX, e.offsetY)) return;
  window.petAPI.showContextMenu();
});
```

注意：现在 `setIgnoreMouseEvents(true)` 时鼠标事件会穿透，但右键菜单需要点中鸟才能弹。命中检测保留 `isPixelTransparent` 即可，逻辑跟现有拖拽一致。

---

## 3. 测试步骤

### 3.1 Phase 1 验收
```bash
cd ~/Desktop/petintable
npm start

# 终端 2:
curl -s 'http://localhost:3000/skins/list' | python3 -m json.tool   # V5
curl -s 'http://localhost:3000/skin?name=blueberry' | python3 -m json.tool  # V2
curl -s 'http://localhost:3000/skin?name=mint'      | python3 -m json.tool  # V3
curl -s 'http://localhost:3000/skin?name=ghost'     | python3 -m json.tool  # V4 应 404
```

V6 验证：切到 mint → 退出 Vibe（dock 右键 quit / `pkill electron`）→ 重启 → 应是 mint。
V7 验证：先 `curl /state?action=start`（coding）等小鸟戴上眼镜，再切皮肤，眼镜状态保持。
V8 验证：手动 `cp assets/skins/blueberry.json assets/skins/cherry.json`，编辑改色 → 跑 `pic/venv/bin/python pic/apply_skin.py cherry` → `curl /skins/list` 应该能看到 cherry。
V9 验证：手动触发 `/state?action=start` → `/state?action=wait` → `/state?action=done`，肉眼检查 equip/knock/remove_glasses 一次性动画播放正确。

### 3.2 Phase 2 验收
- 右键小鸟（命中非透明像素），原生菜单弹出
- 列出 default / blueberry / mint，当前选中前面有 ✓
- 点击切换立即生效

### 3.3 回归
- 拖拽、点击穿透、Layer 1/2/3 状态检测全部正常
- 关闭 VS Code → 30s 后回 idle

---

## 4. 提交建议

两个 commit：
1. `feat(skin): manifest-driven state machine + runtime skin switching API`
2. `feat(skin): native context menu for skin selection`

每个 commit 单独跑对应 Phase 的验收。

---

## 5. 不要做的事

- ❌ 不要把 `STATES` 和 `manifest.states` 的字段语义合并/重命名（保持现有名字，否则后续维护困惑）
- ❌ 不要在 pet.js 里直接 `require('fs')` 读 manifest——用 `fetch` 走 web 协议，符合 contextIsolation
- ❌ 不要加任何 npm 依赖（electron-store 也不要，简单 fs.writeFileSync 够用）
- ❌ 不要"顺手"把 main.js 的检测层逻辑也重构一遍
- ❌ 不要在切皮肤时清空 image cache 之前就 swap 引用——必须 await preloadAll 完成再赋值（防止半途渲染空帧）
- ❌ 不要做"皮肤覆盖部分动画"这种花活（皮肤只换色，动画结构所有皮肤共享）
- ❌ 不要给右键菜单加"打开设置窗口""关于"等额外项，本次只做皮肤切换 + 退出

---

## 6. 已知边界

- **皮肤切换瞬间会有一帧旧图**：因为切换是异步 preload，在 await 完成前还在画旧帧。这是可接受的（切换 < 500ms）。
- **不支持热重载 manifest**：改了 `animation_manifest.json` 要重启 Vibe 生效。
- **文件不存在的皮肤目录**：listSkins 已过滤，但如果 `_roles.json` 被误删 pet.js 会卡在 boot——不处理（属于人为破坏）。

---

## 7. 完成后给 Steve 的反馈

```
✅ 皮肤系统 Phase 1+2 完成

Phase 1 验收:
  V1 默认皮肤启动: [通过/失败]
  V2 切 blueberry: [通过/失败 + 切换耗时 ms]
  V3 切 mint: [通过/失败]
  V4 不存在皮肤: [通过/失败 + 实际响应]
  V5 列表 API: [通过/失败 + 返回内容]
  V6 重启持久化: [通过/失败 + config 文件路径]
  V7 切皮肤不丢动画: [通过/失败]
  V8 新增皮肤热生效: [通过/失败]
  V9 状态机过渡: [通过/失败 + 哪些过渡测了]

Phase 2 验收:
  V10 右键菜单: [通过/失败]

回归:
  拖拽: [正常/异常]
  点击穿透: [正常/异常]
  状态检测 Layer 1/2/3: [正常/异常]

commit hashes: [phase1 hash] / [phase2 hash]
异常或边界发现: [...]
```

如果某项不通过，**先停下来报告**，不要自己改方案。manifest schema 或目录结构如果需要调整，由 Steve 决定。
