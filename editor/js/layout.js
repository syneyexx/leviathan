/**
 * Leviathan Visual Builder — align, distribute, nudge, free-transform capture.
 *
 * ensurePositioned() only flipped static→relative and never captured the visual
 * box — move/resize then wrote style.left from parseFloat||0 and jumped in-flow
 * images. ensureFreeTransform captures the border-box in writable absolute
 * coordinates (no visual jump) before any left/top/width/height writes.
 */

import { alignItems, distributeItems, layoutBoxFromScreen, resizeGroupMembers, resizeRect, roundLayoutBox } from "./geometry.js";
import { captureElementChrome, restoreElementChrome } from "./gesture-draft.js";

export function createLayout(ctx) {
  /** @deprecated use ensureFreeTransform — kept for any stray callers */
  function ensurePositioned(el) {
    ensureFreeTransform(el);
  }

  function zoom() {
    return ctx.store.getState().zoom || 1;
  }

  function parsePx(value) {
    if (value == null || value === "") return null;
    const n = parseFloat(value);
    return Number.isFinite(n) ? n : null;
  }

  /** Nearest containing block for position:absolute (padding edge). */
  function absoluteContainingBlock(el) {
    let node = el.parentElement;
    while (node && node !== document.documentElement) {
      if (node === document.body) return node;
      const pos = getComputedStyle(node).position;
      if (pos && pos !== "static") return node;
      node = node.parentElement;
    }
    return document.body;
  }

  /**
   * Convert the element's screen border-box into writable left/top/width/height
   * for position:absolute relative to its absolute containing block.
   * Works at zoom != 1 (camera scale on #root).
   */
  function captureLayoutBox(el) {
    if (!(el instanceof Element)) return null;
    const z = zoom();
    const rect = el.getBoundingClientRect();
    if (rect.width < 0.5 && rect.height < 0.5) return null;

    const cb = absoluteContainingBlock(el);
    const cbRect = cb.getBoundingClientRect();
    const cbStyle = getComputedStyle(cb);
    const borderLeft = parseFloat(cbStyle.borderLeftWidth) || 0;
    const borderTop = parseFloat(cbStyle.borderTopWidth) || 0;
    // Borders scale with the #root camera transform in screen space.
    const padLeftScreen = cbRect.left + borderLeft * z;
    const padTopScreen = cbRect.top + borderTop * z;

    return {
      left: (rect.left - padLeftScreen) / z + (cb.scrollLeft || 0),
      top: (rect.top - padTopScreen) / z + (cb.scrollTop || 0),
      width: rect.width / z,
      height: rect.height / z,
    };
  }

  function readWrittenBox(el) {
    const left = parsePx(el.style.left);
    const top = parsePx(el.style.top);
    const width = parsePx(el.style.width);
    const height = parsePx(el.style.height);
    if (left == null || top == null || width == null || height == null) return null;
    if (width < 0.5 || height < 0.5) return null;
    return { left, top, width, height };
  }

  function visualMatchesWritten(el, box, tolerancePx = 1) {
    const z = zoom();
    const before = el.getBoundingClientRect();
    const expected = captureLayoutBox(el);
    if (!expected) return false;
    return (
      Math.abs(expected.left - box.left) <= tolerancePx &&
      Math.abs(expected.top - box.top) <= tolerancePx &&
      Math.abs(before.width / z - box.width) <= tolerancePx &&
      Math.abs(before.height / z - box.height) <= tolerancePx
    );
  }

  function applyBox(el, box, { round = false } = {}) {
    const next = round ? roundLayoutBox(box) : box;
    el.style.position = "absolute";
    el.style.left = `${next.left}px`;
    el.style.top = `${next.top}px`;
    el.style.width = `${next.width}px`;
    el.style.height = `${next.height}px`;
    el.style.right = "auto";
    el.style.bottom = "auto";
    el.style.maxWidth = "none";
    el.style.margin = "0";
    return next;
  }

  /**
   * Promote a non-shell element to the free-transform model (absolute box)
   * without a visual jump. Returns the writable layout box or null on abort.
   * On failure, restores exact prior style/attribute chrome (P0-D).
   */
  function ensureFreeTransform(el) {
    if (!(el instanceof Element)) return null;
    if (ctx.selection?.isShell?.(el)) return null;
    if (ctx.selection?.isBuilderNode?.(el)) return null;

    // Register with open gesture draft before first mutation
    ctx.commands?.gestureDraft?.note?.(el);
    const pre = captureElementChrome(el);

    const z = zoom();
    const before = el.getBoundingClientRect();
    if (before.width < 0.5 && before.height < 0.5) {
      ctx.content?.setStatus?.("Kan box niet vastleggen", "dirty");
      return null;
    }

    const pos = getComputedStyle(el).position;
    const written = readWrittenBox(el);
    const rotated = !!(el.style.rotate || (getComputedStyle(el).rotate && getComputedStyle(el).rotate !== "none"));
    // Rotated elements: getBoundingClientRect is an AABB — trust written box (axis-aligned resize MVP).
    if ((pos === "absolute" || pos === "fixed") && written && (rotated || visualMatchesWritten(el, written, 1))) {
      el.style.maxWidth = "none";
      return { ...written };
    }

    const box = captureLayoutBox(el);
    if (!box || !Number.isFinite(box.left) || !Number.isFinite(box.top)) {
      ctx.content?.setStatus?.("Kan box niet vastleggen", "dirty");
      if (pre) restoreElementChrome(pre);
      return null;
    }

    // Freeze computed size (images with height:auto) into px before leaving flow.
    applyBox(el, box);

    const after = el.getBoundingClientRect();
    const dLeft = (before.left - after.left) / z;
    const dTop = (before.top - after.top) / z;
    if (Math.abs(dLeft) > 0.01 || Math.abs(dTop) > 0.01) {
      box.left += dLeft;
      box.top += dTop;
      applyBox(el, box);
    }

    const check = el.getBoundingClientRect();
    if (
      Math.abs(check.left - before.left) > 1 ||
      Math.abs(check.top - before.top) > 1 ||
      Math.abs(check.width - before.width) > 1 ||
      Math.abs(check.height - before.height) > 1
    ) {
      ctx.content?.setStatus?.("Transform vastleggen mislukt — geen sprong toegestaan", "dirty");
      if (pre) restoreElementChrome(pre);
      return null;
    }

    const finalBox = readWrittenBox(el) || box;
    return { ...finalBox };
  }

  function writeLiveBox(el, box) {
    el.style.left = `${box.left}px`;
    el.style.top = `${box.top}px`;
    el.style.width = `${box.width}px`;
    el.style.height = `${box.height}px`;
  }

  /** Apply resize result; edge-only skips axes the handle does not own. */
  function applyResizeBox(el, start, next, dir) {
    const hasE = dir.includes("e");
    const hasW = dir.includes("w");
    const hasN = dir.includes("n");
    const hasS = dir.includes("s");
    const affectsW = hasE || hasW;
    const affectsH = hasN || hasS;

    if (hasW || (hasE && next.left !== start.left)) {
      el.style.left = `${next.left}px`;
    }
    if (hasN || (hasS && next.top !== start.top)) {
      el.style.top = `${next.top}px`;
    }
    // fromCenter changes the opposite edge too — always write left/top when they moved
    if (next.left !== start.left) el.style.left = `${next.left}px`;
    if (next.top !== start.top) el.style.top = `${next.top}px`;

    if (affectsW) el.style.width = `${next.width}px`;
    if (affectsH) el.style.height = `${next.height}px`;
    // Aspect on E/W also changes height — caller passes that via next; write when changed
    if (!affectsH && next.height !== start.height) el.style.height = `${next.height}px`;
    if (!affectsW && next.width !== start.width) el.style.width = `${next.width}px`;
  }

  function moveBy(el, dx, dy) {
    const box = ensureFreeTransform(el);
    if (!box) return;
    box.left += dx;
    box.top += dy;
    writeLiveBox(el, box);
  }

  function commitBox(el, extra = {}) {
    const written = readWrittenBox(el);
    if (written) {
      const rounded = roundLayoutBox(written);
      applyBox(el, rounded, { round: false });
    }
    const props = {
      position: el.style.position || "absolute",
      left: el.style.left,
      top: el.style.top,
      ...extra,
    };
    if (el.style.width) props.width = el.style.width;
    if (el.style.height) props.height = el.style.height;
    if (el.style.maxWidth) props["max-width"] = el.style.maxWidth;
    if (el.style.margin) props.margin = el.style.margin;
    if (el.style.rotate) props.rotate = el.style.rotate;
    if (el.style.zIndex) props["z-index"] = el.style.zIndex;
    for (const [key, value] of Object.entries(props)) {
      if (value != null && value !== "") ctx.content.applyProp(el, key, value);
    }
  }

  function align(mode) {
    const els = ctx.selection.mutable("move");
    if (els.length < 2) {
      ctx.content.setStatus("Selecteer minstens 2 elementen", "dirty");
      return;
    }
    ctx.commands.capture(`uitlijnen-${mode}`, () => {
      const boxes = [];
      for (const el of els) {
        const box = ensureFreeTransform(el);
        if (!box) continue;
        boxes.push({ el, ...box });
      }
      if (boxes.length < 2) return;
      const next = alignItems(boxes, mode);
      next.forEach((item, i) => {
        const el = boxes[i].el;
        writeLiveBox(el, { left: item.left, top: item.top, width: boxes[i].width, height: boxes[i].height });
        commitBox(el);
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
      const boxes = [];
      for (const el of els) {
        const box = ensureFreeTransform(el);
        if (!box) continue;
        boxes.push({ i: boxes.length, el, ...box });
      }
      if (boxes.length < 3) return;
      const placed = distributeItems(boxes, axis);
      const byIndex = new Map(placed.map((item) => [item.i, item]));
      for (const box of boxes) {
        const item = byIndex.get(box.i);
        writeLiveBox(box.el, {
          left: item.left,
          top: item.top,
          width: box.width,
          height: box.height,
        });
        commitBox(box.el);
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

  /** Parse min/max size constraints from document entry + computed style. */
  function readConstraints(el) {
    const entry = ctx.content?.getEntry?.(ctx.selection.selectorFor(el));
    const styles = entry?.styles || {};
    const cs = typeof getComputedStyle === "function" ? getComputedStyle(el) : null;
    const px = (raw, fallback) => {
      if (raw == null || raw === "" || raw === "none" || raw === "auto") return fallback;
      const n = parseFloat(raw);
      return Number.isFinite(n) ? n : fallback;
    };
    return {
      minW: Math.max(1, px(styles["min-width"] || el.style.minWidth, px(cs?.minWidth, 16))),
      minH: Math.max(1, px(styles["min-height"] || el.style.minHeight, px(cs?.minHeight, 16))),
      maxW: (() => {
        const v = px(styles["max-width"] || el.style.maxWidth, px(cs?.maxWidth, null));
        return v != null && v < 1e6 ? v : null;
      })(),
      maxH: (() => {
        const v = px(styles["max-height"] || el.style.maxHeight, px(cs?.maxHeight, null));
        return v != null && v < 1e6 ? v : null;
      })(),
    };
  }

  /**
   * Keyboard resize through the same resizeRect path (Alt+arrows).
   * Arrow maps to SE growth/shrink; Ctrl/Cmd = fromCenter; Shift = 10px.
   */
  function resizeByKeyboard(dir, step, { fromCenter = false, aspect = null } = {}) {
    const els = ctx.selection.mutable("edit");
    if (!els.length) return;
    const mode = ctx.session.groupResizeMode === "independent" ? "independent" : "scale";
    ctx.commands.capture("formaat-toets", () => {
      const primary = ctx.session.primary && els.includes(ctx.session.primary) ? ctx.session.primary : els[0];
      const members = [];
      for (const el of els) {
        const box = ensureFreeTransform(el);
        if (!box) continue;
        members.push({ el, ...box });
      }
      if (!members.length) return;
      const primaryIndex = Math.max(0, members.findIndex((m) => m.el === primary));
      const hasE = dir.includes("e");
      const hasW = dir.includes("w");
      const hasN = dir.includes("n");
      const hasS = dir.includes("s");
      const dx = hasE ? step : hasW ? -step : 0;
      const dy = hasS ? step : hasN ? -step : 0;
      const lockAspect = aspect != null || !!ctx.session.aspectLock;
      const ratio = lockAspect
        ? aspect || ctx.session.aspect || members[primaryIndex].width / members[primaryIndex].height
        : null;
      const constraints = readConstraints(members[primaryIndex].el);
      if (mode === "independent" || members.length === 1) {
        const m = members[primaryIndex];
        const next = resizeRect({
          start: m,
          dir,
          dx,
          dy,
          minW: constraints.minW,
          minH: constraints.minH,
          maxW: constraints.maxW,
          maxH: constraints.maxH,
          aspect: ratio,
          fromCenter,
        });
        applyResizeBox(m.el, m, next, dir);
        // Image-aware: width-only unlocked keeps height unless aspect changed it.
        if (!(hasE || hasW) || hasN || hasS || ratio) {
          /* height already written by applyResizeBox */
        } else if (m.el.tagName === "IMG" && !ratio && next.height === m.height) {
          /* leave height style as-is for height:auto semantics after promote */
        }
        commitBox(m.el);
      } else {
        const starts = members.map(({ left, top, width, height }) => ({ left, top, width, height }));
        const nexts = resizeGroupMembers({
          members: starts,
          primaryIndex,
          dir,
          dx,
          dy,
          mode: "scale",
          aspect: ratio,
          fromCenter,
          minW: constraints.minW,
          minH: constraints.minH,
          maxW: constraints.maxW,
          maxH: constraints.maxH,
        });
        members.forEach((m, i) => {
          writeLiveBox(m.el, roundLayoutBox(nexts[i]));
          commitBox(m.el);
        });
      }
    });
    ctx.chrome?.schedulePaint?.();
  }

  /** Batch style writes during multi-drag preview (single paint). */
  function writeLiveBoxes(entries) {
    for (const { el, box } of entries || []) {
      if (!el || !box) continue;
      writeLiveBox(el, box);
    }
  }

  /** Change position mode without jumping the visual box. */
  function setPositionMode(el, mode) {
    if (!(el instanceof Element) || ctx.selection?.isShell?.(el)) return;
    const z = zoom();
    const before = el.getBoundingClientRect();

    if (mode === "absolute" || mode === "fixed") {
      const box = ensureFreeTransform(el);
      if (!box) return;
      el.style.position = mode;
      ctx.content.applyProp(el, "position", mode);
      commitBox(el);
      return;
    }

    if (mode === "static") {
      // Static returns to flow and usually jumps — keep free-transform absolute instead.
      const box = ensureFreeTransform(el);
      if (!box) return;
      ctx.content.setStatus("Static zou verspringen — absolute gehouden", "dirty");
      return;
    }

    // relative / sticky: zero offsets, measure flow landing, then set left/top to restore visual.
    el.style.position = mode;
    el.style.left = "0px";
    el.style.top = "0px";
    el.style.right = "auto";
    el.style.bottom = "auto";
    const landed = el.getBoundingClientRect();
    el.style.left = `${(before.left - landed.left) / z}px`;
    el.style.top = `${(before.top - landed.top) / z}px`;
    const check = el.getBoundingClientRect();
    if (Math.abs(check.left - before.left) > 1 || Math.abs(check.top - before.top) > 1) {
      const cb = absoluteContainingBlock(el);
      const cbRect = cb.getBoundingClientRect();
      const cbStyle = getComputedStyle(cb);
      const borderLeft = parseFloat(cbStyle.borderLeftWidth) || 0;
      const borderTop = parseFloat(cbStyle.borderTopWidth) || 0;
      applyBox(el, {
        left: (before.left - (cbRect.left + borderLeft * z)) / z + (cb.scrollLeft || 0),
        top: (before.top - (cbRect.top + borderTop * z)) / z + (cb.scrollTop || 0),
        width: before.width / z,
        height: before.height / z,
      });
      ctx.content.setStatus("Positie-modus zou verspringen — absolute gehouden", "dirty");
      commitBox(el);
      return;
    }
    ctx.content.applyProp(el, "position", mode);
    commitBox(el);
  }

  return {
    ensurePositioned,
    ensureFreeTransform,
    captureLayoutBox,
    readWrittenBox,
    writeLiveBox,
    writeLiveBoxes,
    applyResizeBox,
    applyBox,
    moveBy,
    commitBox,
    align,
    distribute,
    nudge,
    resizeByKeyboard,
    readConstraints,
    setPositionMode,
    layoutBoxFromScreen: (rect) => layoutBoxFromScreen(rect, zoom()),
  };
}
