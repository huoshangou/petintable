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

  // ── Context menu ───────────────────────────────────────
  canvas.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    if (isPixelTransparent(e.offsetX, e.offsetY)) return;
    window.petAPI.showContextMenu();
  });

  boot();
})();
