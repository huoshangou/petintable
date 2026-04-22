# Vibe 🐦 — Claude Code Desktop Pet

A pixel-art desktop pet that lives on your screen and mirrors your Claude Code status in real-time.

![idle](assets/preview/idle.gif)
![coding](assets/preview/coding.gif)
![question](assets/preview/question.gif)

## What It Does

Vibe is a frameless, transparent, always-on-top pixel bird. It tracks your Claude Code (or OpenCode) session and changes its animation to reflect what's happening:

| State | Animation | Trigger |
|-------|-----------|---------|
| **Idle** | Bird stands still, no glasses | Agent resting / user typing / no session active |
| **Coding** | Bird puts on glasses and types furiously | Agent is actively generating (via VS Code Hook heartbeat) |
| **Question** | Bird tilts head with a question mark | Agent waiting for your input (via VS Code Hook heartbeat or manual API) |
| **Finished** | Bird pecks screen, removes glasses, returns to idle | Claude Code process exits |

Transitions happen automatically:
- `idle` → `equip glasses` → `coding`
- `coding` ↔ `question` (seamless, glasses stay on)
- `coding` → `knock` → `remove glasses` → `idle`

## Install

### macOS

1. Download `Vibe-x.x.x-arm64.dmg` (Apple Silicon) or `Vibe-x.x.x-x64.dmg` (Intel) from [Releases](../../releases).
2. Open the DMG and drag `Vibe.app` to **Applications**.
3. Launch `Vibe.app`.
4. On first launch, macOS may ask for **Accessibility permission** (required to detect which app is in the foreground). Go to **System Settings → Privacy & Security → Accessibility** and enable `Vibe.app`.
   - If you deny it, Vibe will still work, but it can't tell whether your terminal is in the foreground — it will react to any running Claude Code process.

### Windows

1. Download `Vibe-Setup-x.x.x.exe` from [Releases](../../releases).
2. Run the installer and follow the prompts.
3. Launch `Vibe` from the Start Menu.

## Usage

Just double-click to launch. Vibe runs silently in the background:

- **No terminal needed** — fully self-contained.
- **Draggable** — click and drag the bird to move it anywhere on screen.
- **Click-through** — clicks on transparent areas pass through to your desktop.
- **Always on top** — stays visible above other windows.

### Manual Control (HTTP API)

Vibe exposes a local HTTP server on `localhost:3000`. You can override its state manually:

```bash
curl "http://localhost:3000/state?action=start"   # force coding
curl "http://localhost:3000/state?action=wait"    # force question
curl "http://localhost:3000/state?action=done"    # force idle
curl "http://localhost:3000/state"                # query current state
```

### Integrating with Claude Code / OpenCode

Add these aliases to your shell profile (`~/.zshrc`, `~/.bashrc`, etc.):

```bash
alias cc-start='curl -s "http://localhost:3000/state?action=start"'
alias cc-wait='curl -s "http://localhost:3000/state?action=wait"'
alias cc-done='curl -s "http://localhost:3000/state?action=done"'
```

Or use the built-in process watcher — Vibe detects Claude Code automatically every 2 seconds.

## How It Works

Vibe uses a three-layer detection system. Higher layers override lower ones.

### Layer 1: Hook Heartbeat (VS Code Claude Code only)

A Claude Code plugin (`~/.claude/plugins/vibe-status/`) pushes precise lifecycle events directly to Vibe:

| Event | Vibe State | Meaning |
|-------|-----------|---------|
| `UserPromptSubmit` / `PreToolUse` / `PostToolUse` | **coding** | Agent is actively working |
| `Stop` | **idle** | Session ended |

This is **semantic detection** — Vibe knows the Agent's intent, not just its CPU usage.

### Layer 2: Process Detection (Fallback)

For CLI users or when the Hook plugin is not loaded:

1. **Foreground detection** (macOS: `osascript`, Windows: PowerShell) — checks if your terminal/editor is active.
2. **Process detection** — scans for `opencode` or `claude` processes.
3. **CPU heuristic** (macOS) — high CPU = agent generating; low CPU = user typing or agent idle.
4. **Debounced state changes** — a state must be stable for 6 seconds before switching, preventing flicker.

## Build from Source

```bash
git clone https://github.com/YOURNAME/petintable.git
cd petintable
npm install
npm start        # dev mode
npm run build    # build for current platform
```

Platform-specific builds:
```bash
npm run build:mac   # macOS .dmg
npm run build:win   # Windows .exe (run on Windows)
```

## Project Structure

```
petintable/
├── main.js              # Electron main process + process watcher + HTTP server
├── preload.js           # Secure IPC bridge
├── package.json
├── src/renderer/
│   ├── index.html       # 64×64 canvas
│   ├── styles.css       # Transparent, pixelated
│   └── pet.js           # Animation state machine + hitbox + drag
└── assets/sprites/      # Frame sequences (64×64 PNGs)
    ├── idle_no_glasses/
    ├── equip_glasses/
    ├── coding/
    ├── question/
    └── knock/
```

## Troubleshooting

**Bird doesn't react to Claude Code**
- Make sure Claude Code / OpenCode process name contains `claude` or `opencode`.
- On macOS, grant Accessibility permission (see Install step 4).
- Check `curl http://localhost:3000/state` to see what Vibe thinks the state is.

**"App can't be opened" on macOS**
- Right-click `Vibe.app` → Open, or go to **System Settings → Privacy & Security** and allow it.

**Bird types while I'm typing**
- If you use VS Code Claude Code, make sure the `vibe-status` plugin is active in `~/.claude/plugins/`. With Hook heartbeat, the bird only types when the Agent is actually generating.
- If you use CLI Claude Code or OpenCode, Vibe falls back to CPU detection. On macOS, low CPU = idle. On Windows, CPU detection is not yet implemented.

**Bird flickers between states**
- Hook heartbeat (VS Code) does not flicker — it uses exact semantic events.
- If using CLI / OpenCode (process fallback), debounce (6s stable) prevents flicker.

## License

MIT