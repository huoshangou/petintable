(function () {
  const canvas = document.getElementById("pet");
  const ctx = canvas.getContext("2d");

  // ── Sprite config ──────────────────────────────────────
  const STATES = {
    idle_no_glasses: {
      frames: 8,
      mode: "loop",
      dir: "../../assets/sprites/idle_no_glasses",
      fps: 6,
    },
    // equip_glasses is an automatic transition, triggered when
    // switching FROM idle_no_glasses TO coding.
    equip_glasses: {
      frames: 8,
      mode: "once",
      dir: "../../assets/sprites/equip_glasses",
      fps: 10,
    },
    coding: {
      frames: 8,
      mode: "loop",
      dir: "../../assets/sprites/coding",
      fps: 8,
    },
    question: {
      frames: 8,
      mode: "loop",
      dir: "../../assets/sprites/question",
      fps: 6,
    },
    // knock + remove_glasses are automatic transitions when
    // leaving coding/question → idle_no_glasses.
    knock: {
      frames: 8,
      mode: "once",
      dir: "../../assets/sprites/knock",
      fps: 10,
    },
    remove_glasses: {
      frames: 8,
      mode: "once",
      dir: "../../assets/sprites/equip_glasses",
      reverse: true,
      fps: 10,
    },
  };

  // ── State machine ──────────────────────────────────────
  // The main process owns the "logical" state and sends events here.
  // This state machine handles the animation transitions.
  //
  // Transition table:
  //   logical → idle:   if wearing glasses → knock → remove → idle, else → idle
  //   logical → coding:  if no glasses → equip → coding, else → coding
  //   logical → question: if no glasses → equip → question(coding anim used), else → question

  let currentAnimState = "idle_no_glasses"; // what's currently playing
  let hasGlasses = false;
  let frameIndex = 0;
  let images = {};
  let dragStart = null;
  let animQueue = null; // queued animation after once completes
  let animTimer = null; // setTimeout handle, null when not ticking

  // ── Preload images ─────────────────────────────────────
  function preloadAll() {
    const promises = [];
    for (const [key, cfg] of Object.entries(STATES)) {
      const arr = [];
      for (let i = 0; i < cfg.frames; i++) {
        const idx = String(i).padStart(2, "0");
        const src = `${cfg.dir}/frame_${idx}.png`;
        const img = new Image();
        arr.push(img);
        promises.push(
          new Promise((resolve) => {
            img.onload = resolve;
            img.onerror = () => {
              console.error("Failed to load", src);
              resolve();
            };
            img.src = src;
          })
        );
      }
      images[key] = arr;
    }
    return Promise.all(promises);
  }

  // ── Transition logic ────────────────────────────────────

  function computeAnimSequence(logicalState) {
    // Returns an array of animation states to play in sequence
    if (logicalState === "idle_no_glasses") {
      if (hasGlasses) {
        hasGlasses = false;
        return ["knock", "remove_glasses", "idle_no_glasses"];
      }
      return ["idle_no_glasses"];
    }
    if (logicalState === "coding") {
      if (!hasGlasses) {
        hasGlasses = true;
        return ["equip_glasses", "coding"];
      }
      return ["coding"];
    }
    if (logicalState === "question") {
      if (!hasGlasses) {
        hasGlasses = true;
        return ["equip_glasses", "question"];
      }
      return ["question"];
    }
    return [logicalState];
  }

  function transitionTo(logicalState) {
    const seq = computeAnimSequence(logicalState);
    playSequence(seq);
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

  // ── Render loop ─────────────────────────────────────────
  // Use setTimeout instead of requestAnimationFrame to tick only at
  // the animation's target FPS. When a "once" animation finishes and
  // nothing is queued, the timer stops completely — zero CPU.

  function tick() {
    const cfg = STATES[currentAnimState];
    if (!cfg) { animTimer = null; return; }

    frameIndex++;

    if (cfg.mode === "once" && frameIndex >= cfg.frames) {
      // once animation finished, play next in queue or hold last frame
      if (animQueue && animQueue.length > 0) {
        playSequence(animQueue);
        return; // playSequence restarts the timer
      }
      frameIndex = cfg.frames - 1;
      drawFrame();
      animTimer = null; // stop ticking, hold last frame
      return;
    }

    if (cfg.mode === "loop") {
      frameIndex = frameIndex % cfg.frames;
    }

    drawFrame();

    // schedule next tick at the state's target FPS
    animTimer = setTimeout(tick, 1000 / cfg.fps);
  }

  function startTicking() {
    if (animTimer) clearTimeout(animTimer);
    animTimer = setTimeout(tick, 1000 / STATES[currentAnimState].fps);
  }

  function drawFrame() {
    const cfg = STATES[currentAnimState];
    if (!cfg) return;
    let idx = frameIndex;

    if (cfg.reverse) {
      idx = cfg.frames - 1 - frameIndex;
    }

    const img = images[currentAnimState] ? images[currentAnimState][idx] : null;
    ctx.clearRect(0, 0, 64, 64);

    if (img && img.complete && img.naturalWidth > 0) {
      ctx.drawImage(img, 0, 0, 64, 64);
    }
  }

  // ── IPC: receive state from main process ────────────────
  window.petAPI.onStateChange((state) => {
    transitionTo(state);
  });

  // ── Hitbox ──────────────────────────────────────────────
  function isPixelTransparent(x, y) {
    const pixel = ctx.getImageData(x, y, 1, 1).data;
    return pixel[3] === 0;
  }

  canvas.addEventListener("mousemove", (e) => {
    const transparent = isPixelTransparent(e.offsetX, e.offsetY);
    window.petAPI.setIgnoreMouseEvents(transparent);
    canvas.style.cursor = transparent ? "default" : "grab";
  });

  // ── Drag ────────────────────────────────────────────────
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

  // ── Init ────────────────────────────────────────────────
  preloadAll().then(() => {
    drawFrame();
    startTicking();
  });
})();