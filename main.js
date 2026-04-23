const { app, BrowserWindow, ipcMain, screen, Menu } = require("electron");
const http = require("http");
const fs = require("fs");
const { execSync } = require("child_process");
const path = require("path");
const os = require("os");

const SKINS_DIR = path.join(__dirname, "assets", "skins");
const CONFIG_PATH = path.join(app.getPath("userData"), "vibe-config.json");
let currentSkin = "default";

// ── Electron startup tuning ─────────────────────────────
// A 64×64 pixel pet does not need GPU compositing. Disabling it
// removes the GPU process (~80-90 MB) and avoids waking the GPU
// on every frame.
app.commandLine.appendSwitch("disable-gpu");
app.commandLine.appendSwitch("disable-gpu-compositing");
app.commandLine.appendSwitch("disable-software-rasterizer");

let win = null;
let currentState = "idle_no_glasses";

// ── State Detection Architecture ─────────────────────────
//
// Three-layer fallback:
//   Layer 1: Hook heartbeat (highest precision)
//     Claude Code VS Code plugin sends lifecycle events via
//     POST /vibe/heartbeat { running, waiting }.
//     Directly maps to coding / question / idle. No debounce.
//     HEARTBEAT_TTL_MAX = 15 ticks (30s). If silent, falls back.
//
//   Layer 2: Session log watcher (medium precision, TBD)
//     Could watch ~/.claude/projects/*.jsonl for turn events.
//     Not yet implemented.
//
//   Layer 3: Process + CPU heuristic (lowest precision, fallback)
//     Terminal foreground + process existence + CPU threshold.
//     Used when heartbeat is silent (Claude Code CLI, OpenCode,
//     or VS Code plugin not loaded).
//
// Design principle: the bird represents the AGENT, not the user.
// When the user is typing, the agent is idle → bird rests.
// When the agent is generating content, bird types.
//
// Manual override: HTTP API /state?action=... still works and
// takes immediate effect, but may be overwritten by the next
// heartbeat if the agent is still active.

const POLL_INTERVAL = 2000;
const CPU_THRESHOLD = 3.0; // percent; tuned for macOS ps %cpu
const HEARTBEAT_TTL_MAX = 15; // 15 ticks * 2s = 30s of silence before fallback

let heartbeatTTL = 0;

const TERMINAL_APPS_MAC = [
  "Terminal", "iTerm2", "Warp", "Alacritty", "kitty", "WezTerm",
  "Hyper", "Kitty", "Visual Studio Code", "Code", "Cursor"
];
const TERMINAL_APPS_WIN = [
  "WindowsTerminal", "cmd", "ConEmu", "Cmder", "Warp",
  "Code", "VSCodium", "Cursor"
];

let pendingState = null;
let debounceCount = 0;
const DEBOUNCE_NEEDED = 3; // 6s stable before switching

function isActiveTerminal() {
  const isMac = os.platform() === "darwin";
  if (isMac) {
    try {
      const app = execSync(
        'osascript -e \'tell application "System Events" to get name of first process whose frontmost is true\'',
        { encoding: "utf8", timeout: 3000 }
      ).trim();
      return TERMINAL_APPS_MAC.some(t => app.toLowerCase().includes(t.toLowerCase()));
    } catch (_e) {
      return true;
    }
  } else {
    try {
      const app = execSync(
        "powershell -Command \"(Get-Process | Where-Object {$_.MainWindowHandle -ne 0} | Sort-Object -Property MainWindowHandle -Descending | Select-Object -First 1).ProcessName\"",
        { encoding: "utf8", timeout: 3000 }
      ).trim();
      return TERMINAL_APPS_WIN.some(t => app.toLowerCase().includes(t.toLowerCase()));
    } catch (_e) {
      return true;
    }
  }
}

function detectCCProcess() {
  const isMac = os.platform() === "darwin";
  try {
    if (isMac) {
      execSync(
        "ps -A -o command 2>/dev/null " +
        "| grep -iE 'opencode|claude' " +
        "| grep -v grep " +
        "| grep -vi petintable",
        { encoding: "utf8", timeout: 3000 }
      );
      return true;
    } else {
      execSync(
        "powershell -Command \"Get-Process | Where-Object {$_.ProcessName -match 'opencode|claude|node'} | Select-Object Id,ProcessName\"",
        { encoding: "utf8", timeout: 3000 }
      );
      return true;
    }
  } catch (_e) {
    return false;
  }
}

function getCCProcessCPU() {
  const isMac = os.platform() === "darwin";
  if (!isMac) return 100; // Windows fallback: treat as active

  try {
    const output = execSync(
      "ps -A -o %cpu,command | grep -iE 'opencode|claude' | grep -v grep | grep -vi petintable | awk '{sum+=$1} END {print sum+0}'",
      { encoding: "utf8", timeout: 3000 }
    ).trim();
    return parseFloat(output) || 0;
  } catch (_e) {
    return 0;
  }
}

function computeNextState() {
  if (!isActiveTerminal()) return "idle_no_glasses";
  if (!detectCCProcess()) return "idle_no_glasses";

  const cpu = getCCProcessCPU();
  return cpu >= CPU_THRESHOLD ? "coding" : "idle_no_glasses";
}

function heartbeatToState(data) {
  // Official Desktop Buddy format: { total, running, waiting, msg, entries, tokens, prompt }
  const waiting = data.waiting || 0;
  const running = data.running || 0;
  if (waiting > 0) return "question";
  if (running > 0) return "coding";
  return "idle_no_glasses";
}

function schedulePoll() {
  // Layer 1: Hook heartbeat (highest precision)
  // When heartbeat is active we still need to decrement TTL, but we
  // can do it at a much lower cadence — no shell commands are run.
  if (heartbeatTTL > 0) {
    heartbeatTTL--;
    setTimeout(schedulePoll, POLL_INTERVAL * 5); // 10 s while heartbeat active
    return;
  }

  // Layer 2: Process detection (fallback when heartbeat is silent)
  const next = computeNextState();

  // Preserve manual "question" state while CC is still running.
  // Only override question when CC exits (→ idle).
  if (currentState === "question" && next !== "idle_no_glasses") {
    setTimeout(schedulePoll, POLL_INTERVAL);
    return;
  }

  if (next === pendingState) {
    debounceCount++;
  } else {
    pendingState = next;
    debounceCount = 1;
  }

  if (debounceCount >= DEBOUNCE_NEEDED) {
    sendState(next);
  }

  setTimeout(schedulePoll, POLL_INTERVAL);
}

// ── Layer 2: JSONL Watcher ──────────────────────────────
// Detects "pending approval" (tool_use without immediate tool_result)
// that Layer 1 Hook cannot capture. Respects Layer 1 heartbeatTTL.

const PROJECTS_DIR = path.join(os.homedir(), ".claude", "projects");
const fileOffsets = new Map(); // path → bytes already read
const PENDING_TOOL_USE_TIMEOUT_MS = 2000;
let pendingToolUseTimer = null;

function initWatcher() {
  if (!fs.existsSync(PROJECTS_DIR)) {
    console.log("[Layer2] projects dir not found, skipping watcher");
    return;
  }

  // Record current file sizes so we ignore history (A6)
  function snapshotExistingFiles() {
    const dirs = fs.readdirSync(PROJECTS_DIR);
    for (const d of dirs) {
      const sub = path.join(PROJECTS_DIR, d);
      let stat;
      try { stat = fs.statSync(sub); } catch (_) { continue; }
      if (!stat.isDirectory()) continue;
      let files;
      try { files = fs.readdirSync(sub); } catch (_) { continue; }
      for (const f of files) {
        if (!f.endsWith(".jsonl")) continue;
        const fp = path.join(sub, f);
        try { fileOffsets.set(fp, fs.statSync(fp).size); } catch (_) {}
      }
    }
  }
  snapshotExistingFiles();

  fs.watch(PROJECTS_DIR, { recursive: true }, (eventType, filename) => {
    if (!filename || !filename.endsWith(".jsonl")) return;
    const fp = path.join(PROJECTS_DIR, filename);
    handleJsonlChange(fp);
  });

  console.log("[Layer2] JSONL watcher started");
}

function handleJsonlChange(fp) {
  let stat;
  try { stat = fs.statSync(fp); } catch (_) { return; }
  const lastOffset = fileOffsets.get(fp) ?? stat.size;
  if (stat.size <= lastOffset) {
    fileOffsets.set(fp, stat.size);
    return;
  }

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
  // Only care about assistant / user dialogue records
  if (!msg.type || (msg.type !== "assistant" && msg.type !== "user")) return;

  // assistant message requesting tool use → maybe waiting for approval
  if (msg.type === "assistant" && msg.message?.stop_reason === "tool_use") {
    if (pendingToolUseTimer) clearTimeout(pendingToolUseTimer);
    pendingToolUseTimer = setTimeout(() => {
      maybeSendStateFromWatcher("question", "Layer2:tool_use_pending");
    }, PENDING_TOOL_USE_TIMEOUT_MS);
    return;
  }

  // user message containing tool_result → user approved, back to coding
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
  // Respect Layer 1 heartbeat when it disagrees with coding.
  // Exception: tool_result means user explicitly approved, allow override.
  const isToolResult = source === "Layer2:tool_result";
  if (heartbeatTTL > 0 && state === "coding" && currentState === "question" && !isToolResult) {
    return;
  }
  if (currentState === state) return;
  console.log(`[Layer2] ${currentState} → ${state} (${source})`);
  sendState(state);
}

// ── Window ────────────────────────────────────────────────

function createWindow() {
  const { width: sw, height: sh } = screen.getPrimaryDisplay().workAreaSize;

  win = new BrowserWindow({
    width: 128,
    height: 128,
    x: sw - 180,
    y: sh - 180,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.loadFile("src/renderer/index.html");
  win.setIgnoreMouseEvents(true, { forward: true });
  win.on("closed", () => { win = null; });
}

function sendState(state) {
  if (currentState === state) return;
  currentState = state;
  if (win && !win.isDestroyed()) {
    win.webContents.send("state-change", state);
  }
}

// ── Skin management ──────────────────────────────────────

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

// ── HTTP API ───────────────────────────────────────────────

function handleAction(action) {
  switch (action) {
    case "start":   currentState = "coding"; break;
    case "wait":    currentState = "question"; break;
    case "done":    currentState = "idle_no_glasses"; break;
    case "idle":    currentState = "idle_no_glasses"; break;
    default: return { error: "unknown action", valid: ["start", "wait", "done", "idle"] };
  }
  if (win && !win.isDestroyed()) {
    win.webContents.send("state-change", currentState);
  }
  return { state: currentState };
}

function startHttpServer() {
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://localhost:3000");

    if (url.pathname === "/state") {
      res.writeHead(200, { "Content-Type": "application/json" });
      if (req.method === "GET") {
        const action = url.searchParams.get("action");
        if (action) {
          res.end(JSON.stringify(handleAction(action)));
        } else {
          res.end(JSON.stringify({ state: currentState }));
        }
      } else {
        res.end(JSON.stringify({ state: currentState }));
      }
      return;
    }

    if (url.pathname === "/vibe/heartbeat") {
      if (req.method !== "POST") {
        res.writeHead(405);
        res.end(JSON.stringify({ error: "method not allowed" }));
        return;
      }
      let body = "";
      req.on("data", (chunk) => { body += chunk; });
      req.on("end", () => {
        try {
          const data = JSON.parse(body);
          const state = heartbeatToState(data);
          heartbeatTTL = HEARTBEAT_TTL_MAX;
          sendState(state);
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ ok: true, state }));
        } catch (_e) {
          res.writeHead(400, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: "invalid json" }));
        }
      });
      return;
    }

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

    if (url.pathname === "/skins/list") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ current: currentSkin, available: listSkins() }));
      return;
    }

    res.writeHead(404);
    res.end("not found");
  });

  server.listen(3000, "127.0.0.1", () => {
    console.log("Vibe IPC server on http://localhost:3000");
  });
}

// ── Lifecycle ─────────────────────────────────────────────

app.whenReady().then(() => {
  loadConfig();
  createWindow();
  startHttpServer();
  schedulePoll();
  initWatcher();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => { app.quit(); });

ipcMain.handle("get-current-skin", () => currentSkin);

ipcMain.on("set-ignore-mouse-events", (_event, ignore) => {
  if (win && !win.isDestroyed()) win.setIgnoreMouseEvents(ignore, { forward: true });
});

ipcMain.on("window-move", (_event, dx, dy) => {
  if (win && !win.isDestroyed()) {
    const [x, y] = win.getPosition();
    win.setPosition(x + dx, y + dy);
  }
});

ipcMain.on("show-context-menu", () => showSkinMenu());