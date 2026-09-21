/**
 * Leviathan Visual Builder — geometry.
 * Pure rect math (snap, align, distribute, zoom) plus DOM box reads.
 */

import { ZOOM_MAX, ZOOM_MIN } from "./constants.js";

export function clamp(n, min, max) {
  return Math.min(max, Math.max(min, n));
}

export function boxFromEl(el) {
  const r = el.getBoundingClientRect();
  return { left: r.left, top: r.top, width: r.width, height: r.height, right: r.right, bottom: r.bottom };
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

/** Snap a screen-space rect to vertical/horizontal guides. Returns pixel deltas. */
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
    if (!bestX || Math.abs(delta) < Math.abs(bestX.delta)) bestX = { delta, at: hit.at, kind: hit.kind };
  }
  for (const c of ys) {
    const hit = snapToGuides(c.pos, guidesY, threshold);
    if (!hit) continue;
    const delta = hit.at - c.pos;
    if (!bestY || Math.abs(delta) < Math.abs(bestY.delta)) bestY = { delta, at: hit.at, kind: hit.kind };
  }
  return {
    dx: bestX?.delta || 0,
    dy: bestY?.delta || 0,
    lineX: bestX ? bestX.at : null,
    lineY: bestY ? bestY.at : null,
    kindX: bestX?.kind || null,
    kindY: bestY?.kind || null,
  };
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

export function collectGuides(el, ignore) {
  const parent = el?.parentElement || document.body;
  const guidesX = [];
  const guidesY = [];
  const push = (node, includeCenter) => {
    if (!node || ignore?.has(node)) return;
    const r = node.getBoundingClientRect();
    if (r.width < 1 && r.height < 1) return;
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
    if (sib.id === "lvb-root" || sib.closest?.("#lvb-root")) continue;
    push(sib, true);
  }
  return { guidesX, guidesY };
}
