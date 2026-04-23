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

## Develop

Run from source:

```bash
git clone https://github.com/YOURNAME/petintable.git
cd petintable
npm install
npm start         # launches Vibe in dev mode
```

### Switch skins at runtime

```bash
curl 'http://localhost:3000/skins/list'             # list available skins
curl 'http://localhost:3000/skin?name=blueberry'    # switch
```

Or **right-click the bird** → pick a skin from the menu.

### Add a new skin

1. Copy an existing skin JSON, edit the color overrides:

   ```bash
   cp assets/skins/blueberry.json assets/skins/cherry.json
   # edit cherry.json — keys are role names from assets/skins/_roles.json
   ```

2. Generate the sprite frames:

   ```bash
   ./pic/venv/bin/python pic/apply_skin.py cherry
   ```

3. The new skin appears in `/skins/list` and the right-click menu immediately. No restart needed.

### What are the color "roles"?

`assets/skins/_roles.json` defines 16 named color slots (like `body_main`, `belly_shadow_1`, `glasses_frame`). A skin is just a partial override of these slots. To visually inspect what each role covers in the original sprites, regenerate the picker tool:

```bash
./pic/venv/bin/python pic/build_palette_picker.py
open pic/_palette_picker/index.html
```

## Build for Distribution

```bash
npm run build:mac   # macOS .dmg
npm run build:win   # Windows .exe (run on Windows)
```

Output goes to `dist/`.

## Project Structure

```
petintable/
├── main.js                    # Electron main: detection layers, HTTP API, skin manager
├── preload.js                 # Secure IPC bridge
├── package.json
├── src/renderer/
│   ├── index.html             # 64×64 canvas
│   ├── styles.css
│   └── pet.js                 # Animation manifest interpreter + hitbox + drag
└── assets/
    ├── animation_manifest.json   # State machine (states, transitions, tags)
    ├── sprites/                  # Original sprite frames (skin source of truth)
    └── skins/
        ├── _roles.json           # 16 color role definitions
        ├── <skin>.json           # Per-skin color overrides
        └── <skin>/sprites/       # Generated sprite frames per skin (apply_skin.py output)

pic/                          # Asset pipeline (not shipped to users)
├── extract_sprites.py        # Sheet → per-frame PNGs with foot-anchor alignment
├── apply_skin.py             # Apply a skin's overrides → assets/skins/<skin>/sprites/
├── analyze_palette.py        # Palette diagnostics
├── build_palette_picker.py   # Generates the interactive role-naming tool
└── verify_sprites.html       # Visual frame-by-frame verification
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