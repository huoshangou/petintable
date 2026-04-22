const { app, BrowserWindow, ipcMain, screen } = require("electron");
const http = require("http");
const { execSync } = require("child_process");
const path = require("path");
const os = require("os");

let win = null;
let currentState = "idle_no_glasses";

// ── Process Watcher ──────────────────────────────────────
//
// Logic:
//   1. Is a terminal app the frontmost window?
//      - No  → idle_no_glasses (user isn't looking at CC)
//      - Yes → check if CC process is running
//   2. Is CC process running?
//      - No  → idle_no_glasses
//      - Yes → check CPU usage
//   3. CPU high (>3%) → coding
//      CPU low for 10s   → question (waiting for user input)
//
// Debounce: state must be stable for 3 consecutive polls (6s)
// before switching, to prevent flickering.

const POLL_INTERVAL = 2000;
const LOW_CPU_THRESHOLD = 3.0;
const LOW_CPU_CONSECUTIVE_NEEDED = 5; // 5 × 2s = 10s
const DEBOUNCE_NEEDED = 3; // same state for 3 polls before changing

const TERMINAL_APPS_MAC = [
  "Terminal", "iTerm2", "Warp", "Alacritty", "kitty", "WezTerm",
  "Hyper", "Kitty", "Visual Studio Code", "Code", "Cursor"
];
const TERMINAL_APPS_WIN = [
  "WindowsTerminal", "cmd", "ConEmu", "Cmder", "Warp",
  "Code", "VSCodium", "Cursor"
];

let lowCpuCount = 0;
let pendingState = null;
let debounceCount = 0;

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
      // osascript may fail if accessibility not granted; fall back to true
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
    let out;
    if (isMac) {
      out = execSync(
        "ps -A -o pid,%cpu,command 2>/dev/null " +
        "| grep -iE 'opencode|claude' " +
        "| grep -v grep " +
        "| grep -vi petintable",
        { encoding: "utf8", timeout: 3000 }
      ).trim();
    } else {
      out = execSync(
        "powershell -Command \"Get-Process | Where-Object {$_.ProcessName -match 'opencode|claude|node'} | Select-Object Id,CPU,ProcessName | Format-Table -HideTableHeaders\"",
        { encoding: "utf8", timeout: 3000 }
      ).trim();
    }
    if (!out) return null;

    if (isMac) {
      let totalCpu = 0;
      for (const line of out.split("\n").filter(Boolean)) {
        const parts = line.trim().split(/\s+/);
        if (parts.length >= 2) totalCpu += parseFloat(parts[1]) || 0;
      }
      return { totalCpu };
    } else {
      return { totalCpu: 5 }; // Windows: assume active if exists
    }
  } catch (_e) {
    return null;
  }
}

function computeNextState() {
  // Step 1: is user looking at a terminal?
  if (!isActiveTerminal()) {
    lowCpuCount = 0;
    return "idle_no_glasses";
  }

  // Step 2: is CC running?
  const proc = detectCCProcess();
  if (!proc) {
    lowCpuCount = 0;
    return "idle_no_glasses";
  }

  // Step 3: check CPU
  if (proc.totalCpu < LOW_CPU_THRESHOLD) {
    lowCpuCount++;
  } else {
    lowCpuCount = 0;
  }

  if (lowCpuCount >= LOW_CPU_CONSECUTIVE_NEEDED) {
    return "question";
  }
  return "coding";
}

function processWatchTick() {
  const next = computeNextState();

  if (next === pendingState) {
    debounceCount++;
  } else {
    pendingState = next;
    debounceCount = 1;
  }

  // Only switch state after debounce
  if (debounceCount >= DEBOUNCE_NEEDED) {
    sendState(next);
  }
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
    } else {
      res.writeHead(404);
      res.end("not found");
    }
  });

  server.listen(3000, "127.0.0.1", () => {
    console.log("Vibe IPC server on http://localhost:3000");
  });
}

// ── Lifecycle ─────────────────────────────────────────────

app.whenReady().then(() => {
  createWindow();
  startHttpServer();
  setInterval(processWatchTick, POLL_INTERVAL);
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => { app.quit(); });

ipcMain.on("set-ignore-mouse-events", (_event, ignore) => {
  if (win && !win.isDestroyed()) win.setIgnoreMouseEvents(ignore, { forward: true });
});

ipcMain.on("window-move", (_event, dx, dy) => {
  if (win && !win.isDestroyed()) {
    const [x, y] = win.getPosition();
    win.setPosition(x + dx, y + dy);
  }
});