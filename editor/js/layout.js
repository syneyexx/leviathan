/**
 * Leviathan Visual Builder — align, distribute, nudge, live geometry commit.
 */

import { alignItems, distributeItems } from "./geometry.js";

export function createLayout(ctx) {
  function ensurePositioned(el) {
    const pos = getComputedStyle(el).position;
    if (pos === "static") el.style.position = "relative";
  }

  function moveBy(el, dx, dy) {
    ensurePositioned(el);
    const left = (parseFloat(el.style.left) || 0) + dx;
    const top = (parseFloat(el.style.top) || 0) + dy;
    el.style.left = `${Math.round(left)}px`;
    el.style.top = `${Math.round(top)}px`;
  }

  function commitBox(el, extra = {}) {
    const props = {
      position: el.style.position || "relative",
      left: el.style.left,
      top: el.style.top,
      ...extra,
    };
    if (el.style.width) props.width = el.style.width;
    if (el.style.height) props.height = el.style.height;
    if (el.style.rotate) props.rotate = el.style.rotate;
    if (el.style.zIndex) props["z-index"] = el.style.zIndex;
    for (const [key, value] of Object.entries(props)) {
      if (value != null && value !== "") ctx.content.applyProp(el, key, value);
    }
  }

  function zoom() {
    return ctx.store.getState().zoom || 1;
  }

  function align(mode) {
    const els = ctx.selection.mutable("move");
    if (els.length < 2) {
      ctx.content.setStatus("Selecteer minstens 2 elementen", "dirty");
      return;
    }
    ctx.commands.capture(`uitlijnen-${mode}`, () => {
      const z = zoom();
      const rects = els.map((el) => {
        const r = el.getBoundingClientRect();
        return { el, left: r.left, top: r.top, width: r.width, height: r.height };
      });
      const next = alignItems(rects, mode);
      next.forEach((item, i) => {
        moveBy(rects[i].el, (item.left - rects[i].left) / z, (item.top - rects[i].top) / z);
        commitBox(rects[i].el);
      });
    });
    ctx.chrome?.schedulePaint?.();
    ctx.content.setStatus("Uitgelijnd", "ok");
  }

  function distribute(axis) {
    const els = ctx.selection.mutable("move");
    if (els.length < 3) {
      ctx.content.setStatus("Verdelen vraagt minstens 3 elementen", "dirty");
      return;
    }
    ctx.commands.capture(axis === "x" ? "verdeel-h" : "verdeel-v", () => {
      const z = zoom();
      const rects = els.map((el, i) => {
        const r = el.getBoundingClientRect();
        return { i, el, left: r.left, top: r.top, width: r.width, height: r.height };
      });
      const placed = distributeItems(rects, axis);
      const byIndex = new Map(placed.map((item) => [item.i, item]));
      for (const rect of rects) {
        const item = byIndex.get(rect.i);
        moveBy(rect.el, (item.left - rect.left) / z, (item.top - rect.top) / z);
        commitBox(rect.el);
      }
    });
    ctx.chrome?.schedulePaint?.();
    ctx.content.setStatus(axis === "x" ? "Horizontaal verdeeld" : "Verticaal verdeeld", "ok");
  }

  function nudge(dx, dy) {
    const els = ctx.selection.mutable("move");
    if (!els.length) return;
    ctx.commands.capture("nudge", () => {
      for (const el of els) {
        moveBy(el, dx, dy);
        commitBox(el);
      }
    });
    ctx.chrome?.schedulePaint?.();
  }

  return { ensurePositioned, moveBy, commitBox, align, distribute, nudge };
}
