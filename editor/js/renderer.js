/**
 * Leviathan Visual Builder — paint renderer facade.
 * Prefer WebGPU scene-graph; fall back to DOM/CSS chrome when GPU is unavailable.
 */

import { createWebGpuBackend } from "./renderer-webgpu.js";
import { COLORS, circle, createScene, label, line, rect } from "./scene-graph.js";
import { HANDLE_DIRS } from "./constants.js";
import { handleHitPx, unionRect } from "./geometry.js";

/**
 * @param {object} ctx
 */
export function createRenderer(ctx) {
  let backend = null;
  let mode = "dom"; // 'webgpu' | 'dom'
  let host = null;
  let initPromise = null;
  const scene = createScene();
  const stats = {
    fps: 0,
    frameMs: 0,
    paintCount: 0,
    sceneNodes: 0,
    backend: "dom",
    samples: [],
  };
  let fpsWindow = [];
  let lastTs = 0;

  async function init(root) {
    host = root;
    if (initPromise) return initPromise;
    initPromise = (async () => {
      try {
        backend = await createWebGpuBackend(root);
        if (backend) {
          mode = "webgpu";
          stats.backend = "webgpu";
          root.classList.add("lvb-gpu-on");
          ctx.content?.setStatus?.("WebGPU chrome actief", "ok");
        } else {
          mode = "dom";
          stats.backend = "dom";
          root.classList.remove("lvb-gpu-on");
        }
      } catch (err) {
        mode = "dom";
        stats.backend = "dom";
        backend = null;
        console.warn("[lvb] WebGPU init failed — DOM paint fallback", err);
      }
      return mode;
    })();
    return initPromise;
  }

  function resize() {
    backend?.resize?.();
  }

  /**
   * Build scene from editor session and paint (GPU or DOM).
   * @param {object} ui chrome DOM refs (for DOM fallback + interactive handles)
   */
  function paint(ui) {
    const t0 = performance.now();
    scene.clear();
    const s = ctx.store.getState();
    if (!s.enabled || ctx.session.inlineEl) {
      if (mode === "webgpu") {
        backend?.draw?.(scene);
        hideDomChrome(ui, true);
      } else {
        hideDomChrome(ui, true);
      }
      tickStats(t0);
      return;
    }

    buildScene(scene, ctx, s);
    stats.sceneNodes = scene.count;

    if (mode === "webgpu" && backend) {
      backend.draw(scene);
      syncInteractiveHandles(ui, ctx, s);
      hideDomChrome(ui, false, { gpu: true });
    } else {
      paintDomFallback(ui, ctx, s);
    }
    tickStats(t0);
  }

  function tickStats(t0) {
    const dt = performance.now() - t0;
    stats.frameMs = dt;
    stats.paintCount += 1;
    const now = performance.now();
    if (lastTs) {
      const fps = 1000 / Math.max(now - lastTs, 0.001);
      fpsWindow.push(fps);
      if (fpsWindow.length > 60) fpsWindow.shift();
      stats.fps = fpsWindow.reduce((a, b) => a + b, 0) / fpsWindow.length;
    }
    lastTs = now;
    stats.samples.push({ t: now, ms: dt, nodes: stats.sceneNodes });
    if (stats.samples.length > 120) stats.samples.shift();
    ctx.diagnostics?.recordPaint?.(stats);
  }

  function getMode() {
    return mode;
  }

  function getStats() {
    return {
      ...stats,
      gpu: backend?.getStats?.() || null,
    };
  }

  function dispose() {
    backend?.dispose?.();
    backend = null;
  }

  return {
    init,
    resize,
    paint,
    getMode,
    backend: () => mode || "dom",
    getStats,
    dispose,
    scene,
  };
}

function buildScene(scene, ctx, s) {
  const hover = ctx.session.hoverEl;
  const selected = ctx.session.selected.filter((el) => el.isConnected);
  const primary = ctx.session.primary?.isConnected ? ctx.session.primary : null;

  // Pixel / column grids stay DOM (camera-synced in chrome.syncCamera) for zoom fidelity.

  if (hover && hover !== primary && !selected.includes(hover)) {
    const r = hover.getBoundingClientRect();
    scene.push(rect(r.left, r.top, r.width, r.height, COLORS.goldFill, { stroke: COLORS.gold, strokeW: 1 }));
    scene.push(label(r.left, r.top - 12, ctx.selection.labelFor(hover), COLORS.gold));
  }

  const others = selected.filter((el) => el !== primary);
  for (const el of others) {
    const r = el.getBoundingClientRect();
    scene.push(rect(r.left, r.top, Math.max(r.width, 4), Math.max(r.height, 4), [0.84, 0.66, 0.34, 0.05], { stroke: COLORS.goldSoft, strokeW: 1 }));
  }
  if (selected.length > 1) {
    const u = unionRect(selected);
    if (u) scene.push(rect(u.left, u.top, u.width, u.height, [0, 0, 0, 0], { stroke: COLORS.goldSoft, strokeW: 1 }));
  }

  if (primary) {
    const r = primary.getBoundingClientRect();
    scene.push(rect(r.left, r.top, r.width, r.height, COLORS.goldFill, { stroke: COLORS.gold, strokeW: 2 }));
    const locked = ctx.selection.isLocked(primary);
    const region = ctx.selection.regionFor(primary);
    const dirs = region?.edge ? [region.edge] : HANDLE_DIRS;
    const zoom = s.zoom || 1;
    if (!locked) {
      for (const dir of dirs) {
        const h = handleRect(r, dir, zoom);
        scene.push(rect(h.x, h.y, h.w, h.h, COLORS.handle));
      }
      if (!region?.edge && !ctx.selection.isShell(primary)) {
        const hs = handleHitPx(zoom).visual;
        scene.push(circle(r.left + r.width / 2, r.top - 22, hs / 2, COLORS.handle));
        scene.push(line(r.left + r.width / 2, r.top - 16, r.left + r.width / 2, r.top, COLORS.gold, 1));
      }
    }
    const count = selected.length;
    const lock = locked ? " · lock" : "";
    const rot = primary.style.rotate ? ` · ${primary.style.rotate}` : "";
    const text = `${ctx.selection.labelFor(primary)}${lock}${rot}${count > 1 ? ` +${count - 1}` : ""}`;
    const dw = Math.round(r.width / zoom);
    const dh = Math.round(r.height / zoom);
    scene.push(label(r.left, r.top < 36 ? r.top + 14 : r.top - 12, text, COLORS.gold));
    scene.push(label(r.left + r.width / 2, r.bottom + 14, `${dw} × ${dh}`, COLORS.cyan, "center"));
  }

  // Guides from last snap payload
  const snap = ctx.session._snapGuides;
  if (snap?.lineX != null) {
    const c = snap.kindX === "center" ? COLORS.magenta : snap.kindX === "spacing" ? COLORS.cyan : COLORS.gold;
    scene.push(line(snap.lineX, 0, snap.lineX, window.innerHeight, c, 1));
    if (snap.gapX != null) scene.push(label(snap.lineX, window.innerHeight / 2, `${Math.round(snap.gapX)}px`, COLORS.cyan, "center"));
  }
  if (snap?.lineY != null) {
    const c = snap.kindY === "center" ? COLORS.magenta : snap.kindY === "spacing" ? COLORS.cyan : COLORS.gold;
    scene.push(line(0, snap.lineY, window.innerWidth, snap.lineY, c, 1));
    if (snap.gapY != null) scene.push(label(window.innerWidth / 2, snap.lineY, `${Math.round(snap.gapY)}px`, COLORS.cyan, "center"));
  }

  const marquee = ctx.session._marquee;
  if (marquee) {
    scene.push(rect(marquee.left, marquee.top, marquee.width, marquee.height, COLORS.marquee, { stroke: COLORS.gold, strokeW: 1 }));
  }

  const drop = ctx.session.dropEl;
  if (drop?.isConnected) {
    const r = drop.getBoundingClientRect();
    scene.push(rect(r.left, r.top, r.width, r.height, COLORS.drop, { stroke: COLORS.cyan, strokeW: 2 }));
  }

  const m = ctx.session.measure;
  if (m?.between) {
    const { labelX, labelY, dist, dx, dy } = m.between;
    if (labelX) {
      scene.push(line(labelX.x1, labelX.y, labelX.x2, labelX.y, COLORS.cyan, 1));
      scene.push(label((labelX.x1 + labelX.x2) / 2, labelX.y - 8, `${labelX.value}px`, COLORS.cyan, "center"));
    }
    if (labelY) {
      scene.push(line(labelY.x, labelY.y1, labelY.x, labelY.y2, COLORS.cyan, 1));
      scene.push(label(labelY.x + 8, (labelY.y1 + labelY.y2) / 2, `${labelY.value}px`, COLORS.cyan));
    }
    if (!labelX && !labelY) scene.push(label(24, 48, `${dist}px · Δ${dx},${dy}`, COLORS.gold));
  } else if (m?.a) {
    const a = ctx.camera.localToScreen(m.a.x, m.a.y);
    const end = m.b || m.live;
    scene.push(circle(a.x, a.y, 4, COLORS.gold));
    if (end) {
      const b = ctx.camera.localToScreen(end.x, end.y);
      scene.push(line(a.x, a.y, b.x, a.y, COLORS.ghost, 1));
      scene.push(line(b.x, a.y, b.x, b.y, COLORS.ghost, 1));
      scene.push(line(a.x, a.y, b.x, b.y, COLORS.gold, 1.5));
      scene.push(circle(b.x, b.y, 3.5, COLORS.gold));
      const dx = Math.round(end.x - m.a.x);
      const dy = Math.round(end.y - m.a.y);
      const dist = Math.round(Math.hypot(dx, dy));
      scene.push(label((a.x + b.x) / 2 + 8, (a.y + b.y) / 2 - 8, `${dist}px`, COLORS.gold));
      scene.push(label((a.x + b.x) / 2, a.y - 8, `Δx ${dx}`, COLORS.gold, "center"));
      scene.push(label(b.x + 8, (a.y + b.y) / 2, `Δy ${dy}`, COLORS.gold));
    }
  }
}

function handleRect(r, dir, zoom = 1) {
  const { visual } = handleHitPx(zoom);
  const half = visual / 2;
  const hx = {
    n: r.left + r.width / 2 - half,
    s: r.left + r.width / 2 - half,
    e: r.right - half,
    w: r.left - half,
    ne: r.right - half,
    nw: r.left - half,
    se: r.right - half,
    sw: r.left - half,
  };
  const hy = {
    n: r.top - half,
    s: r.bottom - half,
    e: r.top + r.height / 2 - half,
    w: r.top + r.height / 2 - half,
    ne: r.top - half,
    nw: r.top - half,
    se: r.bottom - half,
    sw: r.bottom - half,
  };
  return { x: hx[dir] ?? r.left, y: hy[dir] ?? r.top, w: visual, h: visual };
}

function layoutDomHandles(selectEl, dirs, showRotate, zoom) {
  const { visual, hit } = handleHitPx(zoom);
  const pad = Math.max(0, (hit - visual) / 2);
  selectEl.querySelectorAll(".lvb-handle").forEach((handle) => {
    const dir = handle.dataset.dir;
    handle.style.width = `${visual}px`;
    handle.style.height = `${visual}px`;
    handle.style.margin = "0";
    handle.style.padding = `${pad}px`;
    handle.style.boxSizing = "content-box";
    // Position relative to select box (0,0 = top-left of selection)
    const map = {
      n: { left: "50%", top: "0%", tx: "-50%", ty: "-50%" },
      s: { left: "50%", top: "100%", tx: "-50%", ty: "-50%" },
      e: { left: "100%", top: "50%", tx: "-50%", ty: "-50%" },
      w: { left: "0%", top: "50%", tx: "-50%", ty: "-50%" },
      ne: { left: "100%", top: "0%", tx: "-50%", ty: "-50%" },
      nw: { left: "0%", top: "0%", tx: "-50%", ty: "-50%" },
      se: { left: "100%", top: "100%", tx: "-50%", ty: "-50%" },
      sw: { left: "0%", top: "100%", tx: "-50%", ty: "-50%" },
    };
    const pos = map[dir] || map.se;
    handle.style.left = pos.left;
    handle.style.top = pos.top;
    handle.style.transform = `translate(${pos.tx}, ${pos.ty})`;
  });
  const rot = selectEl.querySelector(".lvb-rotate");
  if (rot) {
    rot.style.width = `${visual}px`;
    rot.style.height = `${visual}px`;
    rot.style.left = "50%";
    rot.style.top = "-28px";
    rot.style.transform = "translateX(-50%)";
  }
}

/** Keep DOM handles for pointer capture when GPU paints visuals. */
function syncInteractiveHandles(ui, ctx, s) {
  const primary = ctx.session.primary?.isConnected ? ctx.session.primary : null;
  if (!primary || !ui.select) {
    if (ui.select) ui.select.hidden = true;
    return;
  }
  const r = primary.getBoundingClientRect();
  ui.select.hidden = false;
  ui.select.style.left = `${r.left}px`;
  ui.select.style.top = `${r.top}px`;
  ui.select.style.width = `${Math.max(r.width, 8)}px`;
  ui.select.style.height = `${Math.max(r.height, 8)}px`;
  ui.select.classList.add("lvb-select-hitonly");

  const region = ctx.selection.regionFor(primary);
  const dirs = region?.edge ? [region.edge] : HANDLE_DIRS.slice();
  const locked = ctx.selection.isLocked(primary);
  const showRotate = !locked && !region?.edge && !ctx.selection.isShell(primary);
  const sig = `gpu|${dirs.join("")}|${locked ? 1 : 0}|${showRotate ? 1 : 0}|${Math.round((s.zoom || 1) * 100)}`;
  if (ui.select.dataset.handleSig !== sig) {
    ui.select.dataset.handleSig = sig;
    ui.select.querySelectorAll(".lvb-handle, .lvb-rotate, .lvb-label").forEach((n) => n.remove());
    if (!locked) {
      for (const dir of dirs) {
        const handle = document.createElement("div");
        handle.className = "lvb-handle";
        handle.dataset.dir = dir;
        ui.select.appendChild(handle);
      }
      if (showRotate) {
        const rot = document.createElement("div");
        rot.className = "lvb-rotate";
        rot.title = "Roteren (Shift = 15°)";
        ui.select.appendChild(rot);
      }
    }
  }
  layoutDomHandles(ui.select, dirs, showRotate, s.zoom || 1);
}

function hideDomChrome(ui, clear, opts = {}) {
  if (!ui) return;
  if (clear) {
    if (ui.hover) ui.hover.hidden = true;
    if (ui.select) ui.select.hidden = true;
    if (ui.multis) ui.multis.innerHTML = "";
    if (ui.guides) ui.guides.innerHTML = "";
    if (ui.marquee) ui.marquee.hidden = true;
    if (ui.drop) ui.drop.hidden = true;
    if (ui.measure) ui.measure.hidden = true;
    return;
  }
  if (opts.gpu) {
    if (ui.hover) ui.hover.hidden = true;
    if (ui.multis) ui.multis.innerHTML = "";
    if (ui.guides) ui.guides.innerHTML = "";
    if (ui.marquee) ui.marquee.hidden = true;
    if (ui.drop) ui.drop.hidden = true;
    if (ui.measure) ui.measure.hidden = true;
    if (ui.selectLabel) ui.selectLabel.hidden = true;
  }
}

/** Original DOM paint path (fallback). */
function paintDomFallback(ui, ctx, s) {
  if (!ui?.select) return;
  ui.select.classList.remove("lvb-select-hitonly");
  if (ui.selectLabel) ui.selectLabel.hidden = false;

  const hover = ctx.session.hoverEl;
  const selected = ctx.session.selected.filter((el) => el.isConnected);
  const primary = ctx.session.primary?.isConnected ? ctx.session.primary : null;

  if (hover && hover !== primary && !selected.includes(hover)) {
    placeBox(ui.hover, hover.getBoundingClientRect());
    if (ui.hoverLabel) ui.hoverLabel.textContent = ctx.selection.labelFor(hover);
  } else if (ui.hover) ui.hover.hidden = true;

  const others = selected.filter((el) => el !== primary);
  if (others.length && ui.multis) {
    ui.multis.innerHTML = others
      .map((el) => {
        const r = el.getBoundingClientRect();
        return `<div class="lvb-multi" style="left:${r.left}px;top:${r.top}px;width:${Math.max(r.width, 4)}px;height:${Math.max(r.height, 4)}px"></div>`;
      })
      .join("");
    const union = unionRect(selected);
    if (union && selected.length > 1) {
      ui.multis.insertAdjacentHTML(
        "beforeend",
        `<div class="lvb-multi-bounds" style="left:${union.left}px;top:${union.top}px;width:${union.width}px;height:${union.height}px"></div>`,
      );
    }
  } else if (ui.multis) ui.multis.innerHTML = "";

  if (!primary) {
    ui.select.hidden = true;
    return;
  }
  const rect = primary.getBoundingClientRect();
  placeBox(ui.select, rect);
  const region = ctx.selection.regionFor(primary);
  const dirs = region?.edge ? [region.edge] : HANDLE_DIRS.slice();
  const locked = ctx.selection.isLocked(primary);
  const showRotate = !locked && !region?.edge && !ctx.selection.isShell(primary);
  const sig = `dom|${dirs.join("")}|${locked ? 1 : 0}|${showRotate ? 1 : 0}|${Math.round((s.zoom || 1) * 100)}`;
  if (ui.select.dataset.handleSig !== sig) {
    ui.select.dataset.handleSig = sig;
    ui.select.querySelectorAll(".lvb-handle, .lvb-rotate").forEach((n) => n.remove());
    if (!locked) {
      for (const dir of dirs) {
        const handle = document.createElement("div");
        handle.className = "lvb-handle";
        handle.dataset.dir = dir;
        ui.select.appendChild(handle);
      }
      if (showRotate) {
        const rot = document.createElement("div");
        rot.className = "lvb-rotate";
        rot.title = "Roteren (Shift = 15°)";
        ui.select.appendChild(rot);
      }
    }
  }
  layoutDomHandles(ui.select, dirs, showRotate, s.zoom || 1);
  const count = selected.length;
  const lock = locked ? " · lock" : "";
  const rot = primary.style.rotate ? ` · ${primary.style.rotate}` : "";
  const z = s.zoom || 1;
  const dw = Math.round(rect.width / z);
  const dh = Math.round(rect.height / z);
  if (ui.selectLabel) {
    ui.selectLabel.textContent = `${ctx.selection.labelFor(primary)}${lock}${rot}${count > 1 ? ` +${count - 1}` : ""} · ${dw}×${dh}`;
    ui.selectLabel.style.top = rect.top < 36 ? "2px" : "-22px";
  }

  // Guides / marquee / drop / measure — keep existing DOM helpers via session mirrors
  paintDomGuides(ui, ctx);
  paintDomMeasure(ui, ctx);
}

function placeBox(node, rect) {
  if (!node) return;
  node.style.left = `${rect.left}px`;
  node.style.top = `${rect.top}px`;
  node.style.width = `${Math.max(rect.width, 8)}px`;
  node.style.height = `${Math.max(rect.height, 8)}px`;
  node.hidden = false;
}

function paintDomGuides(ui, ctx) {
  const snap = ctx.session._snapGuides;
  if (!ui.guides) return;
  if (!snap) {
    ui.guides.innerHTML = "";
  } else {
    const lines = [];
    if (snap.lineX != null) {
      lines.push(`<div class="lvb-guide is-x is-${snap.kindX || "edge"}" style="left:${snap.lineX}px"></div>`);
      if (snap.gapX != null) lines.push(`<div class="lvb-guide-label is-x" style="left:${snap.lineX}px;top:50%">${Math.round(snap.gapX)}px</div>`);
    }
    if (snap.lineY != null) {
      lines.push(`<div class="lvb-guide is-y is-${snap.kindY || "edge"}" style="top:${snap.lineY}px"></div>`);
      if (snap.gapY != null) lines.push(`<div class="lvb-guide-label is-y" style="top:${snap.lineY}px;left:50%">${Math.round(snap.gapY)}px</div>`);
    }
    ui.guides.innerHTML = lines.join("");
  }
  const marquee = ctx.session._marquee;
  if (ui.marquee) {
    if (!marquee) ui.marquee.hidden = true;
    else {
      ui.marquee.hidden = false;
      ui.marquee.style.left = `${marquee.left}px`;
      ui.marquee.style.top = `${marquee.top}px`;
      ui.marquee.style.width = `${marquee.width}px`;
      ui.marquee.style.height = `${marquee.height}px`;
    }
  }
  const drop = ctx.session.dropEl;
  if (ui.drop) {
    if (!drop) ui.drop.hidden = true;
    else {
      const r = drop.getBoundingClientRect();
      ui.drop.hidden = false;
      ui.drop.style.left = `${r.left}px`;
      ui.drop.style.top = `${r.top}px`;
      ui.drop.style.width = `${r.width}px`;
      ui.drop.style.height = `${r.height}px`;
    }
  }
}

function paintDomMeasure(ui, ctx) {
  const m = ctx.session.measure;
  if (!ui.measure) return;
  if (!m?.a && !m?.live && !m?.between && !m?.pinned) {
    ui.measure.hidden = true;
    return;
  }
  ui.measure.hidden = false;
  ui.measure.setAttribute("width", String(window.innerWidth));
  ui.measure.setAttribute("height", String(window.innerHeight));
  const label = (x, y, text) =>
    `<g class="lvb-measure-label">
      <rect x="${x - 4}" y="${y - 12}" width="${Math.max(28, String(text).length * 7)}" height="16" rx="2" />
      <text x="${x}" y="${y}">${text}</text>
    </g>`;
  if (m.between) {
    const { labelX, labelY, dist, dx, dy } = m.between;
    const parts = [];
    if (labelX) {
      parts.push(`<line class="is-dim" x1="${labelX.x1}" y1="${labelX.y}" x2="${labelX.x2}" y2="${labelX.y}" />
        ${label((labelX.x1 + labelX.x2) / 2, labelX.y - 6, `${labelX.value}px`)}`);
    }
    if (labelY) {
      parts.push(`<line class="is-dim" x1="${labelY.x}" y1="${labelY.y1}" x2="${labelY.x}" y2="${labelY.y2}" />
        ${label(labelY.x + 8, (labelY.y1 + labelY.y2) / 2, `${labelY.value}px`)}`);
    }
    if (!labelX && !labelY) parts.push(label(24, 48, `${dist}px · Δ${dx},${dy}`));
    ui.measure.innerHTML = parts.join("");
    return;
  }
  // Permanent pin survives tool switch
  if (m.pinned && !m.a) {
    const a = ctx.camera.localToScreen(m.pinned.a.x, m.pinned.a.y);
    const b = ctx.camera.localToScreen(m.pinned.b.x, m.pinned.b.y);
    ui.measure.innerHTML = `
      <line class="is-ghost" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${a.y}" />
      <line class="is-ghost" x1="${b.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" />
      <line class="is-pin" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" />
      <circle cx="${a.x}" cy="${a.y}" r="3.5" /><circle cx="${b.x}" cy="${b.y}" r="3.5" />
      ${label((a.x + b.x) / 2 + 8, (a.y + b.y) / 2 - 8, `${m.pinned.dist}px`)}`;
    return;
  }
  if (!m.a) {
    ui.measure.hidden = true;
    return;
  }
  const a = ctx.camera.localToScreen(m.a.x, m.a.y);
  const end = m.b || m.live;
  const b = end ? ctx.camera.localToScreen(end.x, end.y) : null;
  if (!b) {
    ui.measure.innerHTML = `<circle cx="${a.x}" cy="${a.y}" r="4" />`;
    return;
  }
  const dx = Math.round(end.x - m.a.x);
  const dy = Math.round(end.y - m.a.y);
  const dist = Math.round(Math.hypot(dx, dy));
  ui.measure.innerHTML = `
    <line class="is-ghost" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${a.y}" />
    <line class="is-ghost" x1="${b.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" />
    <line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" />
    <circle cx="${a.x}" cy="${a.y}" r="3.5" /><circle cx="${b.x}" cy="${b.y}" r="3.5" />
    ${label((a.x + b.x) / 2 + 8, (a.y + b.y) / 2 - 8, `${dist}px`)}
    ${label((a.x + b.x) / 2, a.y - 8, `Δx ${dx}`)}
    ${label(b.x + 8, (a.y + b.y) / 2, `Δy ${dy}`)}`;
}
