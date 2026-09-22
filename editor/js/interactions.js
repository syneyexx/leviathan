/**
 * Leviathan Visual Builder — pointer machine.
 * idle | select | drag | resize | rotate | pan | reparent | marquee | measure
 *
 * Resize/move math lives in geometry.resizeRect; capture/promote in layout.
 * P0: never parseFloat(style.left)||0 for resize origins — promote first.
 */

import { collectGuides, intersects, measureBetween, resizeRect, roundLayoutBox, snapRect } from "./geometry.js";
import { SNAP_THRESHOLD } from "./constants.js";

export function createInteractions(ctx) {
  let press = null;

  function enabled() {
    return ctx.store.getState().enabled !== false;
  }

  function setPhase(phase) {
    ctx.session.phase = phase;
    document.body.classList.toggle("lvb-panning", phase === "pan");
  }

  function typing(event) {
    const el = event.target;
    if (!(el instanceof Element)) return false;
    if (el.closest("#lvb-root")) return el.matches("input, textarea") || el.isContentEditable;
    return el.matches("input, textarea") || el.isContentEditable;
  }

  function onPointerDown(event) {
    if (!enabled() || ctx.session.inlineEl) return;
    if (ctx.selection.isBuilderNode(event.target)) return;
    const tool = ctx.store.getState().tool || "select";
    if (event.button === 1 || (ctx.session.space && event.button === 0) || (tool === "hand" && event.button === 0)) {
      event.preventDefault();
      startPan(event);
      return;
    }
    if (event.button !== 0) return;
    if (tool === "measure") {
      event.preventDefault();
      addMeasure(event);
      ctx.session.swallow = true;
      return;
    }
    const background = ctx.selection.isBackgroundHit(event.target);
    if (background && tool === "select") {
      press = { kind: "marquee", x: event.clientX, y: event.clientY, shift: event.shiftKey };
      setPhase("select");
      event.preventDefault();
      return;
    }
    const deep = event.metaKey || (event.ctrlKey && !event.shiftKey);
    const hit = ctx.selection.resolveHit(event.target, { deep });
    if (!hit) {
      press = { kind: "marquee", x: event.clientX, y: event.clientY, shift: event.shiftKey };
      setPhase("select");
      return;
    }
    press = { kind: "press", x: event.clientX, y: event.clientY, hit, shift: event.shiftKey, alt: event.altKey };
    setPhase("select");
    event.preventDefault();
  }

  function onPointerMove(event) {
    if (ctx.session.phase === "idle") return;
    if (ctx.session.phase === "pan") return panMove(event);
    if (ctx.session.phase === "drag" || ctx.session.phase === "reparent") return dragMove(event);
    if (ctx.session.phase === "resize") return resizeMove(event);
    if (ctx.session.phase === "rotate") return rotateMove(event);
    if (ctx.session.phase === "marquee") return marqueeMove(event);
    if (ctx.session.phase === "measure") return measureMove(event);
    if (!press) return;
    if (Math.hypot(event.clientX - press.x, event.clientY - press.y) < 4) return;
    if (press.kind === "marquee") {
      setPhase("marquee");
      marqueeMove(event);
      return;
    }
    if (press.kind !== "press") return;
    const el = press.hit;
    if (ctx.store.getState().tool === "rotate" && ctx.selection.canMutate(el)) {
      focusHit(el, press.shift);
      startRotate(event, el);
      return;
    }
    if (ctx.selection.canMutate(el, "move")) {
      focusHit(el, press.shift);
      startDrag(event);
    }
  }

  function onPointerUp(event) {
    const phase = ctx.session.phase;
    if (phase === "drag" || phase === "reparent") finishDrag(event);
    else if (phase === "resize") finishResize();
    else if (phase === "rotate") finishRotate();
    else if (phase === "marquee") finishMarquee(event);
    else if (phase === "pan") setPhase("idle");
    else if (phase === "measure") {
      // Stay in measure until second click completes (handled in addMeasure).
      press = null;
      ctx.session.swallow = true;
      ctx.chrome.schedulePaint();
      return;
    } else if (press?.kind === "press") {
      if (press.shift) ctx.selection.toggle(press.hit);
      else ctx.selection.set([press.hit], press.hit);
    } else if (press?.kind === "marquee") {
      const shell = event.target instanceof Element && ctx.selection.isShell(event.target) ? event.target : null;
      if (shell) {
        if (press.shift) ctx.selection.toggle(shell);
        else ctx.selection.set([shell], shell);
      } else if (!press.shift) ctx.selection.clear();
    }
    press = null;
    if (phase !== "idle") ctx.session.swallow = true;
    if (ctx.session.phase !== "idle") setPhase("idle");
    ctx.chrome.clearGuides();
    ctx.chrome.showMarquee(null);
    ctx.chrome.schedulePaint();
  }

  function focusHit(el, shift) {
    if (shift) {
      if (!ctx.session.selected.includes(el)) ctx.selection.toggle(el);
      return;
    }
    if (!ctx.session.selected.includes(el)) ctx.selection.set([el], el);
    else if (ctx.session.primary !== el) ctx.selection.set(ctx.session.selected, el);
  }

  function startPan(event) {
    const s = ctx.store.getState();
    press = { kind: "pan", x: event.clientX, y: event.clientY, panX: s.panX, panY: s.panY };
    setPhase("pan");
  }

  function panMove(event) {
    ctx.camera.setCamera({
      panX: press.panX + (event.clientX - press.x),
      panY: press.panY + (event.clientY - press.y),
    });
  }

  function startDrag(event) {
    let els = ctx.selection.mutable("move");
    if (!els.length) return;

    // Alt at drag start → duplicate in place, then drag the clones (Figma-style).
    // Ctrl/Meta during drag → reparent (see dragMove).
    if (event.altKey) {
      const clones = ctx.widgets.duplicateInPlace?.(els) || [];
      if (clones.length) {
        ctx.selection.set(clones, clones[0]);
        els = clones.filter((el) => ctx.selection.canMutate(el, "move"));
      }
    }

    const origins = [];
    for (const el of els) {
      const box = ctx.layout.ensureFreeTransform(el);
      if (!box) {
        ctx.content.setStatus("Verplaatsen geannuleerd — box niet vastgelegd", "dirty");
        return;
      }
      origins.push({ el, left: box.left, top: box.top, width: box.width, height: box.height });
    }
    ctx.commands.beginGesture(event.altKey ? "dupliceren+verplaatsen" : "verplaatsen");
    const ignore = new Set(origins.map((o) => o.el));
    const guides = ctx.store.getState().snap
      ? collectGuides(origins[0].el, ignore, { peers: [], includeViewport: true })
      : { guidesX: [], guidesY: [] };
    press = {
      kind: "drag",
      x: event.clientX,
      y: event.clientY,
      z: ctx.store.getState().zoom || 1,
      origins,
      guideCache: guides,
    };
    setPhase("drag");
  }

  function dragMove(event) {
    if (!press?.origins) return;
    const z = press.z || 1;
    let dx = (event.clientX - press.x) / z;
    let dy = (event.clientY - press.y) / z;
    if (event.shiftKey) {
      if (Math.abs(event.clientX - press.x) > Math.abs(event.clientY - press.y)) dy = 0;
      else dx = 0;
    }

    const primary = press.origins[0];
    const minL = Math.min(...press.origins.map((o) => o.left));
    const minT = Math.min(...press.origins.map((o) => o.top));
    const maxR = Math.max(...press.origins.map((o) => o.left + o.width));
    const maxB = Math.max(...press.origins.map((o) => o.top + o.height));
    const groupW = maxR - minL;
    const groupH = maxB - minT;

    const base = primary.el.getBoundingClientRect();
    const curLeft = parseFloat(primary.el.style.left) || 0;
    const curTop = parseFloat(primary.el.style.top) || 0;
    // Screen rect of the whole selection AABB after proposed delta
    const rect = {
      left: base.left + (primary.left + dx - curLeft) * z - (primary.left - minL) * z,
      top: base.top + (primary.top + dy - curTop) * z - (primary.top - minT) * z,
      width: groupW * z,
      height: groupH * z,
    };

    let snap = { dx: 0, dy: 0, lineX: null, lineY: null, kindX: null, kindY: null };
    if (ctx.store.getState().snap) {
      const guides = press.guideCache || collectGuides(primary.el, new Set(press.origins.map((o) => o.el)));
      snap = snapRect(rect, guides.guidesX, guides.guidesY, SNAP_THRESHOLD);
    }
    const fdx = dx + snap.dx / z;
    const fdy = dy + snap.dy / z;
    for (const origin of press.origins) {
      origin.el.style.left = `${origin.left + fdx}px`;
      origin.el.style.top = `${origin.top + fdy}px`;
    }
    ctx.chrome.setGuides(snap);

    // Ctrl/Meta = reparent widgets (Alt is reserved for duplicate-on-start)
    if (event.ctrlKey || event.metaKey) {
      const drop = findDrop(event, press.origins.map((o) => o.el));
      setPhase("reparent");
      ctx.chrome.showDrop(drop);
      press.drop = drop;
    } else {
      if (ctx.session.phase !== "drag") setPhase("drag");
      ctx.chrome.showDrop(null);
      press.drop = null;
    }
    ctx.chrome.schedulePaint();
  }

  function finishDrag() {
    if (press?.drop && ctx.session.phase === "reparent") {
      for (const origin of press.origins) {
        if (!origin.el.dataset.lvbId || !ctx.selection.canMutate(origin.el, "reparent")) continue;
        if (press.drop === origin.el || origin.el.contains(press.drop)) continue;
        press.drop.appendChild(origin.el);
        const content = ctx.content.ensure();
        const node = content.nodes.find((n) => n.id === origin.el.dataset.lvbId);
        if (node) node.parent = ctx.selection.selectorFor(press.drop);
      }
      ctx.content.markContentDirty();
    }
    for (const origin of press?.origins || []) ctx.layout.commitBox(origin.el);
    ctx.commands.endGesture();
    ctx.content.setStatus(press?.drop && ctx.session.phase === "reparent" ? "Verplaatst en genest" : "Verplaatst", "ok");
  }

  function findDrop(event, dragging) {
    const stack = document.elementsFromPoint(event.clientX, event.clientY);
    for (const node of stack) {
      if (!(node instanceof Element) || ctx.selection.isBuilderNode(node)) continue;
      if (dragging.some((el) => el === node || el.contains(node))) continue;
      const hit = ctx.selection.pickEditable(node);
      if (!hit || dragging.some((el) => el === hit || el.contains(hit))) continue;
      if (hit.dataset.lvbId || ctx.selection.isShell(hit)) return hit;
    }
    return document.querySelector(".lv-main");
  }

  function startResize(event, dir) {
    const el = ctx.session.primary;
    if (!el || ctx.selection.isLocked(el)) return;
    const region = ctx.selection.regionFor(el);
    const z = ctx.store.getState().zoom || 1;
    const rect = el.getBoundingClientRect();

    // Shell regions keep CSS-variable resize — never free-transform math.
    if (region?.varKey) {
      ctx.commands.beginGesture("shell");
      press = {
        kind: "resize",
        x: event.clientX,
        y: event.clientY,
        dir,
        region,
        z,
        width: rect.width,
        height: rect.height,
        el,
      };
      try {
        event.currentTarget?.setPointerCapture?.(event.pointerId);
      } catch {
        /* capture optional */
      }
      setPhase("resize");
      return;
    }

    if (!ctx.selection.canMutate(el)) return;
    const box = ctx.layout.ensureFreeTransform(el);
    if (!box) {
      ctx.content.setStatus("Formaat geannuleerd — box niet vastgelegd", "dirty");
      return;
    }
    ctx.commands.beginGesture("formaat");
    press = {
      kind: "resize",
      x: event.clientX,
      y: event.clientY,
      dir,
      region: null,
      z,
      el,
      start: { left: box.left, top: box.top, width: box.width, height: box.height },
      aspect: box.width && box.height ? box.width / box.height : 1,
    };
    setPhase("resize");
  }

  function resizeMove(event) {
    const el = press.el;
    const z = press.z || 1;
    const dx = (event.clientX - press.x) / z;
    const dy = (event.clientY - press.y) / z;
    if (press.region?.varKey) {
      let px;
      if (press.region.edge === "e") px = press.width / z + dx;
      else if (press.region.edge === "w") px = press.width / z - dx;
      else if (press.region.edge === "s") px = press.height / z + dy;
      else px = press.height / z - dy;
      px = Math.min(press.region.max, Math.max(press.region.min, px));
      ctx.content.setRegionPx(press.region, px);
      ctx.chrome.schedulePaint();
      return;
    }
    if (!el || !press.start || !ctx.selection.canMutate(el)) return;

    // Aspect lock ONLY when Shift is held OR inspector lock is explicitly ON.
    const lockAspect = event.shiftKey || !!ctx.session.aspectLock;
    const aspect = lockAspect ? (ctx.session.aspectLock && ctx.session.aspect ? ctx.session.aspect : press.aspect) : null;

    const next = resizeRect({
      start: press.start,
      dir: press.dir,
      dx,
      dy,
      minW: 16,
      minH: 16,
      aspect,
      fromCenter: event.altKey,
    });

    const dir = press.dir || "se";
    const hasE = dir.includes("e");
    const hasW = dir.includes("w");
    const hasN = dir.includes("n");
    const hasS = dir.includes("s");
    const corner = (hasE || hasW) && (hasN || hasS);
    const writeW = hasE || hasW || (aspect && (hasN || hasS));
    const writeH = hasN || hasS || corner || (aspect && (hasE || hasW));

    // Opposite-edge / fromCenter may move left or top — write when changed.
    if (next.left !== press.start.left) el.style.left = `${next.left}px`;
    if (next.top !== press.start.top) el.style.top = `${next.top}px`;
    if (writeW) el.style.width = `${next.width}px`;
    // Width-only unlocked: do NOT set height (keeps frozen promote height / auto semantics).
    if (writeH) el.style.height = `${next.height}px`;

    // Snap resized edges to guides (screen space)
    if (ctx.store.getState().snap && !event.altKey) {
      const screen = el.getBoundingClientRect();
      const guides = collectGuides(el, new Set([el]), { includeViewport: true });
      const snap = snapRect(screen, guides.guidesX, guides.guidesY, SNAP_THRESHOLD);
      if (snap.dx || snap.dy) {
        const zl = z;
        if ((hasE || hasW) && snap.dx) {
          if (hasW && !hasE) {
            el.style.left = `${parseFloat(el.style.left) + snap.dx / zl}px`;
            el.style.width = `${parseFloat(el.style.width) - snap.dx / zl}px`;
          } else if (hasE) {
            el.style.width = `${parseFloat(el.style.width) + snap.dx / zl}px`;
          }
        }
        if ((hasN || hasS) && snap.dy) {
          if (hasN && !hasS) {
            el.style.top = `${parseFloat(el.style.top) + snap.dy / zl}px`;
            el.style.height = `${parseFloat(el.style.height) - snap.dy / zl}px`;
          } else if (hasS) {
            el.style.height = `${parseFloat(el.style.height) + snap.dy / zl}px`;
          }
        }
        ctx.chrome.setGuides(snap);
      } else ctx.chrome.clearGuides();
    }

    ctx.chrome.schedulePaint();
  }

  function finishResize() {
    if (!press?.region?.varKey && press?.el) {
      const el = press.el;
      const written = ctx.layout.readWrittenBox(el);
      if (written) {
        const rounded = roundLayoutBox(written);
        el.style.left = `${rounded.left}px`;
        el.style.top = `${rounded.top}px`;
        el.style.width = `${rounded.width}px`;
        // Only round height if it was explicitly set (width-only may leave prior height).
        if (el.style.height) el.style.height = `${rounded.height}px`;
      }
      ctx.layout.commitBox(el);
    }
    ctx.commands.endGesture();
  }

  function startRotate(event, el) {
    ctx.commands.beginGesture("rotatie");
    const rect = el.getBoundingClientRect();
    const read = ctx.content.readProp?.(el, "rotate");
    const fromProp = parseFloat(String(read?.value || "").replace("deg", ""));
    const start = Number.isFinite(fromProp) ? fromProp : parseFloat(el.style.rotate) || 0;
    press = {
      kind: "rotate",
      el,
      cx: rect.left + rect.width / 2,
      cy: rect.top + rect.height / 2,
      a0: Math.atan2(event.clientY - (rect.top + rect.height / 2), event.clientX - (rect.left + rect.width / 2)),
      start,
    };
    setPhase("rotate");
  }

  function rotateMove(event) {
    const a1 = Math.atan2(event.clientY - press.cy, event.clientX - press.cx);
    let deg = press.start + ((a1 - press.a0) * 180) / Math.PI;
    if (event.shiftKey) deg = Math.round(deg / 15) * 15;
    press.el.style.rotate = `${Math.round(deg * 10) / 10}deg`;
    ctx.chrome.schedulePaint();
  }

  function finishRotate() {
    if (press?.el) ctx.layout.commitBox(press.el, { rotate: press.el.style.rotate });
    ctx.commands.endGesture();
  }

  function marqueeMove(event) {
    const left = Math.min(press.x, event.clientX);
    const top = Math.min(press.y, event.clientY);
    const rect = { left, top, width: Math.abs(event.clientX - press.x), height: Math.abs(event.clientY - press.y), right: Math.max(press.x, event.clientX), bottom: Math.max(press.y, event.clientY) };
    press.rect = rect;
    ctx.chrome.showMarquee(rect);
  }

  function finishMarquee() {
    const rect = press?.rect;
    if (!rect || rect.width < 3 || rect.height < 3) return;
    const root = document.getElementById("root");
    if (!root) return;
    const hits = [];
    // Prefer editable candidates over querySelectorAll("*")
    const candidates = root.querySelectorAll("[data-lvb-id], img, [class*='lv-']");
    candidates.forEach((el) => {
      if (ctx.selection.isBuilderNode(el) || ctx.selection.isShell(el)) return;
      if (!ctx.selection.canMutate(el) && ctx.selection.isLocked(el)) return;
      const box = el.getBoundingClientRect();
      if (box.width < 2 || box.height < 2) return;
      if (intersects(rect, box)) hits.push(el);
    });
    const set = new Set(hits);
    const top = hits.filter((el) => {
      let parent = el.parentElement;
      while (parent) {
        if (set.has(parent)) return false;
        parent = parent.parentElement;
      }
      return true;
    });
    if (press.shift) {
      const merged = [...ctx.session.selected];
      for (const el of top) if (!merged.includes(el)) merged.push(el);
      ctx.selection.set(merged, merged[merged.length - 1] || null);
    } else ctx.selection.set(top, top[0] || null);
  }

  function addMeasure(event) {
    const local = ctx.camera.screenToLocal(event.clientX, event.clientY);
    const point = { x: local.x, y: local.y };
    if (!ctx.session.measure?.a || ctx.session.measure.b) {
      ctx.session.measure = { a: point, b: null, live: null, between: null };
      setPhase("measure");
      press = { kind: "measure", x: event.clientX, y: event.clientY };
    } else {
      ctx.session.measure.b = point;
      ctx.session.measure.live = null;
      const dx = Math.round(point.x - ctx.session.measure.a.x);
      const dy = Math.round(point.y - ctx.session.measure.a.y);
      ctx.content.setStatus(`Meet ${Math.round(Math.hypot(dx, dy))}px · Δx ${dx} · Δy ${dy}`, "ok");
      setPhase("idle");
    }
    ctx.chrome.schedulePaint();
  }

  function measureMove(event) {
    if (!ctx.session.measure?.a || ctx.session.measure.b) return;
    const local = ctx.camera.screenToLocal(event.clientX, event.clientY);
    ctx.session.measure.live = { x: local.x, y: local.y };
    ctx.chrome.schedulePaint();
  }

  function onSelectChrome(event) {
    if (!enabled()) return;
    const rotateHandle = event.target.closest?.(".lvb-rotate");
    if (rotateHandle) {
      event.preventDefault();
      event.stopPropagation();
      const el = ctx.session.primary;
      if (el && ctx.selection.canMutate(el)) {
        startRotate(event, el);
        try {
          rotateHandle.setPointerCapture?.(event.pointerId);
        } catch {
          /* optional */
        }
      }
      return;
    }
    const handle = event.target.closest?.(".lvb-handle");
    if (handle) {
      event.preventDefault();
      event.stopPropagation();
      startResize(event, handle.dataset.dir || "se");
      try {
        handle.setPointerCapture?.(event.pointerId);
      } catch {
        /* optional */
      }
      return;
    }
    const el = ctx.session.primary;
    if (!el || ctx.selection.isShell(el)) return;
    event.preventDefault();
    event.stopPropagation();
    if (ctx.store.getState().tool === "rotate" && ctx.selection.canMutate(el)) startRotate(event, el);
    else if (ctx.selection.canMutate(el, "move")) startDrag(event);
  }

  function onDoubleClick(event) {
    if (!enabled() || ctx.selection.isBuilderNode(event.target)) return;
    const primary = ctx.session.primary;
    const next = ctx.selection.resolveHit(event.target, { drillFrom: primary });
    if (next && next !== primary) {
      event.preventDefault();
      event.stopPropagation();
      ctx.selection.set([next], next);
      return;
    }
    if (!primary || primary.tagName === "IMG" || !ctx.selection.canMutate(primary)) return;
    event.preventDefault();
    event.stopPropagation();
    ctx.session.inlineEl = primary;
    primary.contentEditable = "true";
    primary.classList.add("lvb-inline-editing");
    primary.focus();
    ctx.commands.beginGesture("tekst");
    const onBlur = () => {
      primary.removeEventListener("blur", onBlur);
      primary.contentEditable = "false";
      primary.classList.remove("lvb-inline-editing");
      const text = primary.textContent || "";
      ctx.session.inlineEl = null;
      const baseline = ctx.content.stageText(primary, text);
      ctx.commands.endGesture();
      if (baseline && baseline !== text && !primary.dataset.lvbId) ctx.content.replaceSource(baseline, text);
      ctx.chrome.schedulePaint();
    };
    primary.addEventListener("blur", onBlur);
  }

  function onContextMenu(event) {
    if (!enabled()) return;
    if (ctx.selection.isBuilderNode(event.target) && !event.target.closest(".lvb-select")) return;
    const hit = ctx.selection.isBuilderNode(event.target) ? ctx.session.primary : ctx.selection.pickEditable(event.target);
    if (!hit && !ctx.session.primary) return;
    event.preventDefault();
    event.stopPropagation();
    if (hit && !ctx.session.selected.includes(hit)) ctx.selection.set([hit], hit);
    ctx.chrome.showMenu(event.clientX, event.clientY, menuItems());
  }

  function menuItems() {
    const el = ctx.session.primary;
    return [
      { id: "copy", label: "Kopiëren", kbd: "⌘C", run: () => ctx.registry.run("copy") },
      { id: "paste", label: "Plakken", kbd: "⌘V", run: () => ctx.registry.run("paste") },
      { id: "duplicate", label: "Dupliceren", kbd: "⌘D", run: () => ctx.registry.run("duplicate") },
      { sep: true },
      { id: "delete", label: "Verwijderen", kbd: "Del", disabled: el && !ctx.selection.canMutate(el, "delete"), run: () => ctx.registry.run("delete") },
      { id: "lock", label: el && ctx.selection.isLocked(el) ? "Unlock" : "Lock", run: () => ctx.registry.run("lock") },
      { sep: true },
      { id: "align-left", label: "Links uitlijnen", kbd: "Alt+L", run: () => ctx.registry.run("align-left") },
      { id: "align-center", label: "Horizontaal midden", kbd: "Alt+C", run: () => ctx.registry.run("align-center") },
      { id: "align-right", label: "Rechts uitlijnen", kbd: "Alt+R", run: () => ctx.registry.run("align-right") },
      { id: "distribute-h", label: "Verdeel horizontaal", kbd: "Alt+Shift+H", run: () => ctx.registry.run("distribute-h") },
      { sep: true },
      { id: "component", label: "Maak component", run: () => ctx.registry.run("component-create") },
      { id: "insert-text", label: "Insert tekst", run: () => ctx.registry.run("insert-text") },
      { id: "insert-image", label: "Image toevoegen…", run: () => ctx.registry.run("insert-image") },
      { id: "front", label: "Naar voren", run: () => ctx.registry.run("forward") },
      { id: "back", label: "Naar achter", run: () => ctx.registry.run("backward") },
      { id: "group", label: "Groeperen", kbd: "⌘G", run: () => ctx.registry.run("group") },
      { id: "ungroup", label: "Degroeperen", run: () => ctx.registry.run("ungroup") },
      { id: "copy-style", label: "Kopieer stijl", run: () => ctx.registry.run("copy-style") },
      { id: "paste-style", label: "Plak stijl", run: () => ctx.registry.run("paste-style") },
      { id: "detach", label: "Detach component", run: () => ctx.registry.run("detach"), disabled: !el?.dataset?.lvbComponentId },
    ];
  }

  function onKeyDown(event) {
    if (!enabled()) return;
    if (event.key === " " && !typing(event) && !ctx.palette?.isOpen?.()) {
      ctx.session.space = true;
      document.body.classList.add("lvb-space");
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    if (typing(event) || ctx.palette?.isOpen?.()) return;
    const step = event.shiftKey ? 10 : 1;
    const arrows = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (arrows[event.key]) {
      event.preventDefault();
      event.stopImmediatePropagation();
      ctx.layout.nudge(...arrows[event.key]);
      return;
    }
    if (event.key === "Escape") {
      ctx.chrome.hideMenu();
      ctx.session.measure = { a: null, b: null };
      if (ctx.session.phase && ctx.session.phase !== "idle") {
        ctx.commands.cancelGesture?.();
        press = null;
        setPhase("idle");
        ctx.chrome.clearGuides?.();
        ctx.chrome.schedulePaint();
        return;
      }
      if (ctx.session.inlineEl) ctx.session.inlineEl.blur();
      else ctx.selection.clear();
      ctx.chrome.schedulePaint();
    }
  }

  function onKeyUp(event) {
    if (event.key === " ") {
      ctx.session.space = false;
      document.body.classList.remove("lvb-space");
    }
  }

  function onDropFiles(event) {
    if (!enabled() || ctx.selection.isBuilderNode(event.target)) return;
    const file = [...(event.dataTransfer?.files || [])].find((item) => item.type.startsWith("image/"));
    if (!file) return;
    event.preventDefault();
    ctx.widgets.uploadFile(file, "insert").then(() => {
      const el = ctx.session.primary;
      const parent = el?.parentElement;
      if (!el || !parent) return;
      const pr = parent.getBoundingClientRect();
      const z = ctx.store.getState().zoom || 1;
      el.style.position = "relative";
      el.style.left = `${Math.max(0, Math.round((event.clientX - pr.left) / z - 40))}px`;
      el.style.top = `${Math.max(0, Math.round((event.clientY - pr.top) / z - 40))}px`;
      ctx.layout.commitBox(el);
    }).catch((err) => ctx.content.setStatus(String(err.message || err), "dirty"));
  }

  function watchMutations() {
    const mo = new MutationObserver((records) => {
      if (ctx.session.applying || ctx.session.inlineEl || ctx.session.phase !== "idle") return;
      const relevant = records.some((rec) => {
        const target = rec.target;
        if (!(target instanceof Node)) return false;
        const el = target.nodeType === 1 ? target : target.parentElement;
        if (!el) return false;
        if (el.id === "lvb-live-overrides" || el.closest?.("#lvb-root")) return false;
        return true;
      });
      if (!relevant) return;
      clearTimeout(mo._t);
      mo._t = setTimeout(() => {
        if (ctx.session.phase !== "idle" || ctx.session.applying) return;
        ctx.content.applyContentOverrides();
        ctx.content.mountNodes();
        ctx.chrome.schedulePaint();
        ctx.chrome.invalidate("layers");
      }, 120);
    });
    const arm = () => {
      const root = document.getElementById("root");
      if (!root) return false;
      mo.observe(root, { childList: true, subtree: true, characterData: true });
      return true;
    };
    if (!arm()) {
      const timer = setInterval(() => {
        if (arm()) clearInterval(timer);
      }, 250);
    }
  }

  function cancelActiveGesture() {
    if (!press && ctx.session.phase === "idle") return;
    ctx.commands.cancelGesture?.();
    press = null;
    setPhase("idle");
    ctx.chrome.clearGuides?.();
    ctx.chrome.schedulePaint();
  }

  function attach() {
    document.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("pointermove", onPointerMove, true);
    window.addEventListener("pointerup", onPointerUp, true);
    window.addEventListener("pointercancel", () => cancelActiveGesture(), true);
    window.addEventListener("lostpointercapture", () => {
      if (ctx.session.phase !== "idle") cancelActiveGesture();
    }, true);
    window.addEventListener("blur", () => cancelActiveGesture());
    document.addEventListener("dblclick", onDoubleClick, true);
    document.addEventListener("contextmenu", onContextMenu, true);
    document.addEventListener("click", (event) => {
      if (!ctx.session.swallow) return;
      ctx.session.swallow = false;
      if (!ctx.selection.isBuilderNode(event.target)) {
        event.preventDefault();
        event.stopPropagation();
      }
    }, true);
    document.addEventListener("mousemove", (event) => {
      if (!enabled() || ctx.session.phase !== "idle" || ctx.session.inlineEl) return;
      if (ctx.selection.isBuilderNode(event.target)) {
        ctx.session.hoverEl = null;
      } else {
        const next = ctx.selection.pickEditable(event.target);
        if (next !== ctx.session.hoverEl) {
          ctx.session.hoverEl = next;
          ctx.chrome.schedulePaint();
        }
      }
      // Alt+hover over another element while something is selected → spacing measure
      if (event.altKey && ctx.session.primary && ctx.session.hoverEl && ctx.session.hoverEl !== ctx.session.primary) {
        const between = measureBetween(ctx.session.primary.getBoundingClientRect(), ctx.session.hoverEl.getBoundingClientRect());
        ctx.session.measure = { ...(ctx.session.measure || {}), between, a: ctx.session.measure?.a || null, b: ctx.session.measure?.b || null };
        ctx.chrome.schedulePaint();
      } else if (ctx.session.measure?.between) {
        ctx.session.measure.between = null;
        ctx.chrome.schedulePaint();
      }
    }, true);
    window.addEventListener("keydown", onKeyDown, true);
    window.addEventListener("keyup", onKeyUp, true);
    window.addEventListener("wheel", (event) => {
      if (!enabled() || !(event.ctrlKey || event.metaKey)) return;
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.08 : 1 / 1.08;
      ctx.camera.zoomAt(event.clientX, event.clientY, (ctx.store.getState().zoom || 1) * factor);
    }, { passive: false });
    window.addEventListener("dragover", (event) => {
      if (enabled()) event.preventDefault();
    });
    window.addEventListener("drop", onDropFiles);
    const box = ctx.chrome.selectBox();
    box?.addEventListener("pointerdown", onSelectChrome);
    watchMutations();
  }

  return { attach, cancelActiveGesture };
}
