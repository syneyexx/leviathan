/**
 * Leviathan Visual Builder — selection.
 * Primary + multi-select, shell rules, selectors, hit testing.
 */

import { REGIONS, SHELL_LOCK, TEXTISH } from "./constants.js";

export function createSelection(ctx) {
  const session = ctx.session;

  function isBuilderNode(node) {
    if (!node) return false;
    const el = node.nodeType === 1 ? node : node.parentElement;
    if (!el) return false;
    return !!(el.closest && el.closest("#lvb-root"));
  }

  function isShell(el) {
    if (!(el instanceof Element)) return false;
    return [...el.classList].some((c) => SHELL_LOCK.has(`.${c}`));
  }

  function regionFor(el) {
    if (!(el instanceof Element)) return null;
    return REGIONS.find((r) => el.matches?.(r.selector)) || null;
  }

  function selectorFor(el) {
    if (!(el instanceof Element)) return "unknown";
    if (el.dataset?.lvbId) return `[data-lvb-id="${el.dataset.lvbId}"]`;
    if (el.tagName === "IMG") {
      const src = el.getAttribute("src");
      if (src) return `img[src="${src}"]`;
      return "img";
    }
    const lv = [...el.classList].filter((c) => c.startsWith("lv-") && !c.startsWith("lvb-"));
    if (lv.length === 1) return `.${lv[0]}`;
    if (lv.length > 1) return `.${lv.join(".")}`;
    if (el.id && el.id !== "root") return `#${el.id}`;
    const tag = el.tagName.toLowerCase();
    const parent = el.parentElement;
    if (parent && parent !== document.body) {
      const idx = [...parent.children].indexOf(el) + 1;
      return `${selectorFor(parent)} > ${tag}:nth-child(${idx})`;
    }
    return tag;
  }

  function labelFor(el) {
    if (!(el instanceof Element)) return "";
    if (el.dataset?.lvbLabel) return el.dataset.lvbLabel;
    if (el.dataset?.lvbId) return el.dataset.lvbId;
    if (el.tagName === "IMG") return "image";
    const lv = [...el.classList].find((c) => c.startsWith("lv-") && !c.startsWith("lvb-"));
    if (lv) return `.${lv}`;
    const text = (el.textContent || "").trim().slice(0, 28);
    return text || el.tagName.toLowerCase();
  }

  function isLocked(el) {
    if (!(el instanceof Element)) return true;
    if (el.dataset?.lvbLocked === "1") return true;
    const entry = ctx.content?.getEntry?.(selectorFor(el));
    return !!entry?.locked;
  }

  function canMutate(el, action = "edit") {
    if (!(el instanceof Element) || isBuilderNode(el)) return false;
    if (isLocked(el)) return false;
    if (isShell(el) && (action === "move" || action === "delete" || action === "reparent")) return false;
    return true;
  }

  function pickEditable(target) {
    if (!(target instanceof Element) || isBuilderNode(target)) return null;
    const img = target.closest?.("img");
    if (img && !isBuilderNode(img)) return img;
    let el = target;
    while (el && el !== document.body && el.id !== "root") {
      if (isBuilderNode(el)) return null;
      if (el.dataset?.lvbId) return el;
      if ([...el.classList].some((c) => c.startsWith("lv-") && !c.startsWith("lvb-"))) return el;
      if (TEXTISH.has(el.tagName) || el.tagName === "DIV" || el.tagName === "SECTION" || el.tagName === "ARTICLE") {
        return el;
      }
      el = el.parentElement;
    }
    return null;
  }

  function pickDeep(target) {
    if (!(target instanceof Element) || isBuilderNode(target)) return null;
    if (target === document.body || target === document.documentElement || target.id === "root") return null;
    return target;
  }

  function drill(target, from) {
    if (!(from instanceof Element) || !from.contains(target) || from === target) return pickEditable(target);
    const child = [...from.children].find((c) => c === target || c.contains(target));
    if (child && !isBuilderNode(child)) return child;
    return pickDeep(target) || from;
  }

  function resolveHit(target, { deep = false, drillFrom = null } = {}) {
    if (drillFrom) return drill(target, drillFrom);
    if (deep) return pickDeep(target);
    return pickEditable(target);
  }

  function keys() {
    return session.selected.map((el) => selectorFor(el));
  }

  function publish() {
    ctx.store.setState({
      sel: keys().join("|"),
      selCount: session.selected.length,
    });
    ctx.chrome?.schedulePaint?.();
  }

  function set(els, primary) {
    const list = [];
    for (const el of els || []) {
      if (el instanceof Element && !isBuilderNode(el) && !list.includes(el)) list.push(el);
    }
    session.selected = list;
    session.primary = primary && list.includes(primary) ? primary : list[list.length - 1] || null;
    publish();
  }

  function toggle(el) {
    if (!(el instanceof Element)) return;
    if (session.selected.includes(el)) {
      session.selected = session.selected.filter((n) => n !== el);
    } else {
      session.selected = [...session.selected, el];
    }
    if (!session.selected.includes(session.primary)) {
      session.primary = session.selected[session.selected.length - 1] || null;
    }
    publish();
  }

  function clear() {
    session.selected = [];
    session.primary = null;
    publish();
  }

  function reselect(selectors) {
    const found = [];
    for (const sel of selectors || []) {
      try {
        const el = document.querySelector(sel);
        if (el instanceof Element && !isBuilderNode(el)) found.push(el);
      } catch {
        /* invalid selector after structural edit */
      }
    }
    set(found, found[0] || null);
  }

  function replaceElement(prev, next) {
    session.selected = session.selected.map((el) => (el === prev ? next : el));
    if (session.primary === prev) session.primary = next;
    publish();
  }

  function mutable(action = "edit") {
    return session.selected.filter((el) => canMutate(el, action));
  }

  function path(el) {
    const parts = [];
    let cur = el;
    while (cur && cur !== document.body && cur.id !== "root") {
      if (!isBuilderNode(cur)) parts.push(cur);
      cur = cur.parentElement;
    }
    return parts.reverse();
  }

  function isBackgroundHit(target) {
    if (!(target instanceof Element)) return true;
    if (isBuilderNode(target)) return false;
    if (target === document.body || target === document.documentElement || target.id === "root") return true;
    if (isShell(target)) return true;
    return false;
  }

  return {
    isBuilderNode,
    isShell,
    isLocked,
    canMutate,
    regionFor,
    selectorFor,
    labelFor,
    pickEditable,
    pickDeep,
    resolveHit,
    keys,
    set,
    toggle,
    clear,
    reselect,
    replaceElement,
    mutable,
    path,
    isBackgroundHit,
    get primary() {
      return session.primary;
    },
    get all() {
      return session.selected;
    },
  };
}
