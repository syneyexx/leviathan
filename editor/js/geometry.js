/**
 * Leviathan Visual Builder — geometry.
 * Pure rect math (snap, align, distribute, zoom, resize) plus DOM box reads.
 *
 * P0 resize bugs (interactions.js startResize / resizeMove) that this module kills:
 * 1. West handle flew left: press.left = parseFloat(style.left)||0 treated missing
 *    inline left as 0, then wrote left=0+dx → jumped to containing-block origin.
 * 2. West also wrote top (and north wrote left) via a combined w|n branch.
 * 3. Min-size clamp still applied leftover dx to left → walked off-canvas.
 * 4. Screen getBoundingClientRect mixed with layout style.left/top under camera zoom.
 * 5. East always wrote height → width-only drag scaled images (height:auto + object-fit).
 */

import { ZOOM_MAX, ZOOM_MIN } from "./constants.js";

export function clamp(n, min, max) {
  return Math.min(max, Math.max(min, n));
}

export function boxFromEl(el) {
  const r = el.getBoundingClientRect();
  return { left: r.left, top: r.top, width: r.width, height: r.height, right: r.right, bottom: r.bottom };
}

/**
 * Convert a screen-space DOMRect (under #root camera scale) into layout pixels.
 * Does not invent offsetParent left/top — only divides by zoom.
 */
export function layoutBoxFromScreen(rect, zoom = 1) {
  const z = zoom || 1;
  return {
    left: rect.left / z,
    top: rect.top / z,
    width: rect.width / z,
    height: rect.height / z,
  };
}

/**
 * Figma/Framer opposite-edge resize in layout pixels.
 * Camera zoom is an input only via already-converted dx/dy — never applied here.
 *
 * @param {{ left:number, top:number, width:number, height:number }} start
 * @param {string} dir  n|s|e|w|ne|nw|se|sw
 * @param {number} dx  layout px delta from pointerdown
 * @param {number} dy
 * @param {number} [minW=1]
 * @param {number} [minH=1]
 * @param {number|null} [aspect=null]  width/height when locked
 * @param {boolean} [fromCenter=false]  Alt — grow around start center
 */
export function resizeRect({
  start,
  dir = "se",
  dx = 0,
  dy = 0,
  minW = 1,
  minH = 1,
  aspect = null,
  fromCenter = false,
}) {
  const right = start.left + start.width;
  const bottom = start.top + start.height;
  const cx = start.left + start.width / 2;
  const cy = start.top + start.height / 2;

  const hasE = dir.includes("e");
  const hasW = dir.includes("w");
  const hasN = dir.includes("n");
  const hasS = dir.includes("s");

  let width = start.width;
  let height = start.height;

  if (fromCenter) {
    if (hasE) width = start.width + dx * 2;
    else if (hasW) width = start.width - dx * 2;
    if (hasS) height = start.height + dy * 2;
    else if (hasN) height = start.height - dy * 2;
  } else {
    if (hasE) width = start.width + dx;
    if (hasW) width = start.width - dx;
    if (hasS) height = start.height + dy;
    if (hasN) height = start.height - dy;
  }

  const ratio = aspect != null && Number.isFinite(aspect) && aspect > 0 ? aspect : null;
  if (ratio) {
    const affectsW = hasE || hasW;
    const affectsH = hasN || hasS;
    if (affectsW && affectsH) {
      const nextH = width / ratio;
      const nextW = height * ratio;
      const dw = Math.abs(width - start.width);
      const dh = Math.abs(height - start.height);
      if (dw >= dh) height = nextH;
      else width = nextW;
    } else if (affectsW) {
      height = width / ratio;
    } else if (affectsH) {
      width = height * ratio;
    }
  }

  // Clamp first — then derive left/top from the anchored opposite edge.
  // NEVER apply leftover dx to left after clamp.
  width = Math.max(minW, width);
  height = Math.max(minH, height);

  let left = start.left;
  let top = start.top;

  if (fromCenter) {
    left = cx - width / 2;
    top = cy - height / 2;
  } else {
    if (hasW) left = right - width;
    if (hasN) top = bottom - height;
    // E/S keep start.left / start.top (already set)
    // Aspect on E/W may change height — keep top frozen (start.top)
    // Aspect on N/S may change width — keep left frozen unless W also present
    if (ratio && (hasE || hasW) && !hasN && !hasS) {
      top = start.top;
    }
    if (ratio && (hasN || hasS) && !hasE && !hasW) {
      left = start.left;
    }
  }

  return { left, top, width, height };
}

/** Round a layout box to whole pixels (pointer-up / commit). */
export function roundLayoutBox(box) {
  return {
    left: Math.round(box.left),
    top: Math.round(box.top),
    width: Math.max(1, Math.round(box.width)),
    height: Math.max(1, Math.round(box.height)),
  };
}

export function intersects(a, b) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

export function snapToGuides(value, guides, threshold = 6) {
  let best = null;
  for (const guide of guides) {
    const at = typeof guide === "number" ? guide : guide.at;
    const kind = typeof guide === "number" ? "edge" : guide.kind || "edge";
    const dist = Math.abs(value - at);
    if (dist <= threshold && (!best || dist < best.dist)) best = { at, kind, dist };
  }
  return best;
}

export function alignItems(items, mode) {
  if (!items.length) return [];
  const left = Math.min(...items.map((i) => i.left));
  const top = Math.min(...items.map((i) => i.top));
  const right = Math.max(...items.map((i) => i.left + i.width));
  const bottom = Math.max(...items.map((i) => i.top + i.height));
  const cx = (left + right) / 2;
  const cy = (top + bottom) / 2;
  return items.map((i) => {
    let nextLeft = i.left;
    let nextTop = i.top;
    if (mode === "left") nextLeft = left;
    if (mode === "right") nextLeft = right - i.width;
    if (mode === "center") nextLeft = cx - i.width / 2;
    if (mode === "top") nextTop = top;
    if (mode === "bottom") nextTop = bottom - i.height;
    if (mode === "middle") nextTop = cy - i.height / 2;
    return { ...i, left: nextLeft, top: nextTop };
  });
}

export function distributeItems(items, axis) {
  if (items.length < 3) return items.map((i) => ({ ...i }));
  const key = axis === "x" ? "left" : "top";
  const size = axis === "x" ? "width" : "height";
  const sorted = [...items].sort((a, b) => a[key] - b[key] || a.i - b.i);
  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  const span = last[key] + last[size] - first[key];
  const sum = sorted.reduce((acc, it) => acc + it[size], 0);
  const gap = (span - sum) / (sorted.length - 1);
  let cursor = first[key];
  return sorted.map((it) => {
    const next = { ...it, [key]: cursor };
    cursor += it[size] + gap;
    return next;
  });
}

export function zoomToCursor({ zoom, panX, panY, clientX, clientY, nextZoom, originX = 0, originY = 0 }) {
  const z = clamp(nextZoom, ZOOM_MIN, ZOOM_MAX);
  const safe = zoom || 1;
  const localX = (clientX - originX - panX) / safe;
  const localY = (clientY - originY - panY) / safe;
  return {
    zoom: z,
    panX: clientX - originX - localX * z,
    panY: clientY - originY - localY * z,
  };
}

/** Union AABB of elements (screen space). */
export function unionRect(els) {
  let left = Infinity;
  let top = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  let any = false;
  for (const el of els || []) {
    if (!(el instanceof Element) || !el.isConnected) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 0.5 && r.height < 0.5) continue;
    any = true;
    left = Math.min(left, r.left);
    top = Math.min(top, r.top);
    right = Math.max(right, r.right);
    bottom = Math.max(bottom, r.bottom);
  }
  if (!any) return null;
  return { left, top, width: right - left, height: bottom - top, right, bottom };
}

/**
 * Edge/center/spacing distances between two screen rects (Figma-style measure).
 * Returns null if rects are missing.
 */
export function measureBetween(a, b) {
  if (!a || !b) return null;
  const aR = a.right ?? a.left + a.width;
  const aB = a.bottom ?? a.top + a.height;
  const bR = b.right ?? b.left + b.width;
  const bB = b.bottom ?? b.top + b.height;
  const gapLeft = b.left - aR;
  const gapRight = a.left - bR;
  const gapTop = b.top - aB;
  const gapBottom = a.top - bB;
  let dx = 0;
  let dy = 0;
  let labelX = null;
  let labelY = null;
  // Horizontal gap (non-overlapping preferred)
  if (gapLeft >= 0) {
    dx = gapLeft;
    labelX = { x1: aR, x2: b.left, y: (Math.max(a.top, b.top) + Math.min(aB, bB)) / 2, value: Math.round(dx) };
  } else if (gapRight >= 0) {
    dx = gapRight;
    labelX = { x1: bR, x2: a.left, y: (Math.max(a.top, b.top) + Math.min(aB, bB)) / 2, value: Math.round(dx) };
  } else {
    dx = Math.round(b.left + b.width / 2 - (a.left + a.width / 2));
  }
  if (gapTop >= 0) {
    dy = gapTop;
    labelY = { y1: aB, y2: b.top, x: (Math.max(a.left, b.left) + Math.min(aR, bR)) / 2, value: Math.round(dy) };
  } else if (gapBottom >= 0) {
    dy = gapBottom;
    labelY = { y1: bB, y2: a.top, x: (Math.max(a.left, b.left) + Math.min(aR, bR)) / 2, value: Math.round(dy) };
  } else {
    dy = Math.round(b.top + b.height / 2 - (a.top + a.height / 2));
  }
  return { dx, dy, dist: Math.round(Math.hypot(dx, dy)), labelX, labelY };
}

/**
 * Collect edge + center + equal-spacing guides for a moving rect.
 * @param {Element} el
 * @param {Set<Element>} [ignore]
 * @param {{ peers?: Element[], includeViewport?: boolean }} [opts]
 */
export function collectGuides(el, ignore, opts = {}) {
  const parent = el?.parentElement || document.body;
  const guidesX = [];
  const guidesY = [];
  const boxes = [];

  const push = (node, includeCenter) => {
    if (!node || ignore?.has(node)) return;
    if (node.id === "lvb-root" || node.closest?.("#lvb-root")) return;
    const r = node.getBoundingClientRect();
    if (r.width < 1 && r.height < 1) return;
    boxes.push({ left: r.left, top: r.top, width: r.width, height: r.height, right: r.right, bottom: r.bottom });
    guidesX.push({ at: r.left, kind: "edge" }, { at: r.right, kind: "edge" });
    guidesY.push({ at: r.top, kind: "edge" }, { at: r.bottom, kind: "edge" });
    if (includeCenter) {
      guidesX.push({ at: r.left + r.width / 2, kind: "center" });
      guidesY.push({ at: r.top + r.height / 2, kind: "center" });
    }
  };

  push(parent, true);
  const kids = parent.children ? [...parent.children] : [];
  for (const sib of kids) {
    if (sib === el || ignore?.has(sib)) continue;
    push(sib, true);
  }

  // Peer selection members (multi-drag neighbors already ignored)
  for (const peer of opts.peers || []) {
    if (peer === el || ignore?.has(peer)) continue;
    push(peer, true);
  }

  // App / main frame bounds
  const frame = document.querySelector(".lv-app") || document.querySelector(".lv-main");
  if (frame && frame !== parent) push(frame, true);

  if (opts.includeViewport !== false) {
    guidesX.push({ at: 0, kind: "edge" }, { at: window.innerWidth / 2, kind: "center" }, { at: window.innerWidth, kind: "edge" });
    guidesY.push({ at: 0, kind: "edge" }, { at: window.innerHeight / 2, kind: "center" }, { at: window.innerHeight, kind: "edge" });
  }

  // Equal-distance midpoints between sibling pairs (spacing guides)
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i];
      const b = boxes[j];
      if (a.right < b.left) {
        const mid = (a.right + b.left) / 2;
        guidesX.push({ at: mid, kind: "spacing", gap: b.left - a.right });
      } else if (b.right < a.left) {
        const mid = (b.right + a.left) / 2;
        guidesX.push({ at: mid, kind: "spacing", gap: a.left - b.right });
      }
      if (a.bottom < b.top) {
        const mid = (a.bottom + b.top) / 2;
        guidesY.push({ at: mid, kind: "spacing", gap: b.top - a.bottom });
      } else if (b.bottom < a.top) {
        const mid = (b.bottom + a.top) / 2;
        guidesY.push({ at: mid, kind: "spacing", gap: a.top - b.bottom });
      }
    }
  }

  return { guidesX, guidesY, boxes };
}

/**
 * Snap rect; also returns spacing labels when hitting a spacing guide.
 * threshold is in screen pixels.
 */
export function snapRect(rect, guidesX, guidesY, threshold = 6) {
  const xs = [
    { pos: rect.left, kind: "edge" },
    { pos: rect.left + rect.width / 2, kind: "center" },
    { pos: rect.left + rect.width, kind: "edge" },
  ];
  const ys = [
    { pos: rect.top, kind: "edge" },
    { pos: rect.top + rect.height / 2, kind: "center" },
    { pos: rect.top + rect.height, kind: "edge" },
  ];
  let bestX = null;
  let bestY = null;
  for (const c of xs) {
    const hit = snapToGuides(c.pos, guidesX, threshold);
    if (!hit) continue;
    const delta = hit.at - c.pos;
    if (!bestX || Math.abs(delta) < Math.abs(bestX.delta)) {
      bestX = { delta, at: hit.at, kind: hit.kind, gap: guidesX.find((g) => (typeof g === "number" ? g : g.at) === hit.at)?.gap };
    }
  }
  for (const c of ys) {
    const hit = snapToGuides(c.pos, guidesY, threshold);
    if (!hit) continue;
    const delta = hit.at - c.pos;
    if (!bestY || Math.abs(delta) < Math.abs(bestY.delta)) {
      bestY = { delta, at: hit.at, kind: hit.kind, gap: guidesY.find((g) => (typeof g === "number" ? g : g.at) === hit.at)?.gap };
    }
  }
  return {
    dx: bestX?.delta || 0,
    dy: bestY?.delta || 0,
    lineX: bestX ? bestX.at : null,
    lineY: bestY ? bestY.at : null,
    kindX: bestX?.kind || null,
    kindY: bestY?.kind || null,
    gapX: bestX?.gap ?? null,
    gapY: bestY?.gap ?? null,
  };
}
