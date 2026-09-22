/**
 * Leviathan Visual Builder — layers tree (frontier).
 * Hierarchy, search with ancestors, rename, eye/lock, before/after/into drop, virtualization.
 */

import { LAYER_ROW_H } from "../constants.js";
import { escapeHtml } from "../util.js";

const ROW = LAYER_ROW_H;

export function createLayers(ctx) {
  let built = false;
  let dropLine = null;
  const panel = {
    id: "layers",
    title: "Layers",
    zone: "left",
    place: "dock",
    host: null,
    _sig: null,
    signature() {
      const s = ctx.store.getState();
      return `${s.sel}|${s.uiEpoch || 0}|${ctx.session.layerQuery || ""}`;
    },
    bind(host) {
      this.host = host;
      host.addEventListener("input", (event) => {
        if (event.target.dataset?.role === "layer-search") {
          ctx.session.layerQuery = event.target.value || "";
          paint(ctx, host);
        }
        if (event.target.dataset?.role === "layer-rename") {
          const el = query(event.target.dataset.layerRename);
          if (!el) return;
          const name = event.target.value.trim();
          el.dataset.lvbLabel = name;
          if (el.dataset.lvbId) {
            const content = ctx.content.ensure();
            const node = content.nodes.find((n) => n.id === el.dataset.lvbId);
            if (node) node.label = name;
            ctx.store.setState({ content });
            ctx.content.markContentDirty();
          }
        }
      });
      host.addEventListener("keydown", (event) => {
        if (event.key === "F2") {
          const row = host.querySelector(".lvb-layer.is-on");
          const nameBtn = row?.querySelector("[data-layer-select]");
          if (nameBtn) startRename(ctx, host, nameBtn.dataset.layerSelect);
        }
        if (event.key === "Enter" && event.target.dataset?.role === "layer-rename") {
          event.target.blur();
          paint(ctx, host);
        }
      });
      host.addEventListener("click", (event) => onClick(ctx, host, event));
      host.addEventListener("contextmenu", (event) => {
        const row = event.target.closest("[data-layer]");
        if (!row) return;
        event.preventDefault();
        const el = query(row.dataset.layer);
        if (el && !ctx.session.selected.includes(el)) ctx.selection.set([el], el);
        ctx.chrome.showMenu(event.clientX, event.clientY, layerMenu(ctx, el));
      });
      host.addEventListener("mouseover", (event) => {
        const row = event.target.closest("[data-layer]");
        if (!row) return;
        const el = query(row.dataset.layer);
        if (el !== ctx.session.hoverEl) {
          ctx.session.hoverEl = el;
          ctx.chrome.schedulePaint();
        }
      });
      host.addEventListener("mouseleave", () => {
        ctx.session.hoverEl = null;
        ctx.chrome.schedulePaint();
      });
      host.addEventListener("dragstart", (event) => {
        const row = event.target.closest("[data-layer]");
        if (!row) return;
        ctx.session.dragLayer = row.dataset.layer;
        event.dataTransfer?.setData("text/plain", row.dataset.layer);
      });
      host.addEventListener("dragover", (event) => {
        if (!ctx.session.dragLayer) return;
        const row = event.target.closest("[data-layer]");
        if (!row) return;
        event.preventDefault();
        const intent = dropIntent(row, event.clientY);
        showDropLine(host, row, intent);
      });
      host.addEventListener("dragleave", () => hideDropLine(host));
      host.addEventListener("drop", (event) => {
        hideDropLine(host);
        onDrop(ctx, event);
      });
      host.addEventListener("scroll", (event) => {
        if (event.target.dataset?.role === "layer-scroll") paint(ctx, host, true);
      }, true);
      host.addEventListener("dblclick", (event) => {
        const name = event.target.closest("[data-layer-select]");
        if (name) startRename(ctx, host, name.dataset.layerSelect);
      });
    },
    render() {
      if (!this.host) return;
      if (!built) {
        this.host.innerHTML = `<div class="lvb-layers-head">Lagen</div>
          <input data-role="layer-search" data-nohistory="1" placeholder="Filter lagen…" value="${escapeHtml(ctx.session.layerQuery || "")}" />
          <div class="lvb-layer-scroll" data-role="layer-scroll"><div data-role="layer-list"></div><div class="lvb-layer-drop" data-role="layer-drop" hidden></div></div>`;
        built = true;
      }
      paint(ctx, this.host);
      scrollSelectedIntoView(this.host, ctx);
    },
  };
  return panel;
}

function query(selector) {
  try {
    return document.querySelector(selector);
  } catch {
    return null;
  }
}

function typeIcon(el) {
  if (el.classList.contains("lvb-group")) return "▦";
  if (el.dataset.lvbComponentId) return "◆";
  if (el.tagName === "IMG") return "▣";
  if (/^H[1-6]$/.test(el.tagName) || el.tagName === "P" || el.tagName === "SPAN") return "T";
  if (el.tagName === "BUTTON") return "▭";
  if (el.dataset.lvbId) return "□";
  return "·";
}

function walk(ctx, el, depth, acc) {
  if (!(el instanceof Element) || ctx.selection.isBuilderNode(el)) return;
  if (el.id === "lvb-live-overrides") return;
  const selector = ctx.selection.selectorFor(el);
  const label = ctx.selection.labelFor(el);
  const kids = [...el.children].filter((child) => !ctx.selection.isBuilderNode(child));
  if (!ctx.session.layerState) ctx.session.layerState = new Map();
  const stored = ctx.session.layerState.get(selector);
  const open = ctx.session.layerQuery ? true : stored == null ? depth < 2 : stored;
  acc.push({
    el,
    depth,
    selector,
    label,
    kids: kids.length,
    open,
    shell: ctx.selection.isShell(el),
    icon: typeIcon(el),
  });
  if (open) {
    for (const child of kids) walk(ctx, child, depth + 1, acc);
  }
}

function rows(ctx) {
  const root = document.getElementById("root");
  const acc = [];
  if (root) {
    for (const child of [...root.children]) walk(ctx, child, 0, acc);
  }
  const q = (ctx.session.layerQuery || "").trim().toLowerCase();
  if (!q) return acc;
  // Keep matching rows + their ancestors
  const match = new Set();
  for (const row of acc) {
    if (row.label.toLowerCase().includes(q) || row.selector.toLowerCase().includes(q)) {
      match.add(row.selector);
      let parent = row.el.parentElement;
      while (parent && parent.id !== "root") {
        match.add(ctx.selection.selectorFor(parent));
        parent = parent.parentElement;
      }
    }
  }
  return acc.filter((row) => match.has(row.selector));
}

function paint(ctx, host, fromScroll = false) {
  const list = host.querySelector("[data-role='layer-list']");
  const scroller = host.querySelector("[data-role='layer-scroll']");
  if (!list || !scroller) return;
  const all = rows(ctx);
  const head = host.querySelector(".lvb-layers-head");
  if (head) head.textContent = `Lagen (${all.length})`;
  if (!fromScroll && document.activeElement?.dataset?.role !== "layer-search" && document.activeElement?.dataset?.role !== "layer-rename") {
    const input = host.querySelector("[data-role='layer-search']");
    if (input && input.value !== (ctx.session.layerQuery || "")) input.value = ctx.session.layerQuery || "";
  }
  const useWindow = all.length > 200;
  const scrollTop = scroller.scrollTop || 0;
  const viewH = scroller.clientHeight || 480;
  const start = useWindow ? Math.max(0, Math.floor(scrollTop / ROW) - 4) : 0;
  const end = useWindow ? Math.min(all.length, start + Math.ceil(viewH / ROW) + 8) : all.length;
  const slice = all.slice(start, end);
  list.style.height = useWindow ? `${all.length * ROW}px` : "auto";
  list.style.position = "relative";
  list.innerHTML = slice
    .map((row, i) => {
      const active = ctx.session.selected.includes(row.el) ? " is-on" : "";
      const hidden = row.el.style.display === "none" || ctx.content.getEntry(row.selector)?.hide;
      const locked = ctx.selection.isLocked(row.el);
      const top = useWindow ? (start + i) * ROW : null;
      const shell = row.shell ? " is-shell" : "";
      return `<div class="lvb-layer${active}${hidden ? " is-hidden" : ""}${shell}" draggable="${row.shell ? "false" : "true"}" data-layer="${escapeHtml(row.selector)}" style="${top == null ? `padding-left:${8 + row.depth * 12}px` : `position:absolute;top:${top}px;left:0;right:0;height:${ROW}px;padding-left:${8 + row.depth * 12}px`}">
        <button type="button" class="lvb-icon" data-layer-eye="${escapeHtml(row.selector)}" title="Zichtbaarheid">${hidden ? "○" : "●"}</button>
        <button type="button" class="lvb-icon" data-layer-lock="${escapeHtml(row.selector)}" title="Lock">${locked ? "■" : "□"}</button>
        <button type="button" class="lvb-icon" data-layer-twist="${escapeHtml(row.selector)}" data-open="${row.open ? "1" : "0"}">${row.kids ? (row.open ? "▾" : "▸") : ""}</button>
        <span class="lvb-layer-type" title="${escapeHtml(row.el.tagName)}">${row.icon}</span>
        <button type="button" class="lvb-layer-name" data-layer-select="${escapeHtml(row.selector)}">${escapeHtml(row.label)}</button>
        ${row.el.dataset?.lvbNode ? `<span class="lvb-layer-badge" title="node id">node:${escapeHtml(row.el.dataset.lvbNode.slice(0, 8))}</span>` : ""}
        ${row.shell ? `<span class="lvb-layer-badge is-shell">shell</span>` : ""}
      </div>`;
    })
    .join("");
}

function scrollSelectedIntoView(host, ctx) {
  const primary = ctx.session.primary;
  if (!primary) return;
  const sel = ctx.selection.selectorFor(primary);
  const row = host.querySelector(`[data-layer="${CSS.escape(sel)}"]`);
  row?.scrollIntoView?.({ block: "nearest" });
}

function startRename(ctx, host, selector) {
  const el = query(selector);
  if (!el || ctx.selection.isShell(el)) return;
  const btn = host.querySelector(`[data-layer-select="${CSS.escape(selector)}"]`);
  if (!btn) return;
  const input = document.createElement("input");
  input.dataset.role = "layer-rename";
  input.dataset.layerRename = selector;
  input.dataset.nohistory = "1";
  input.value = ctx.selection.labelFor(el);
  input.className = "lvb-layer-rename";
  btn.replaceWith(input);
  input.focus();
  input.select();
  input.addEventListener("blur", () => {
    ctx.commands.capture("hernoemen", () => {
      const name = input.value.trim() || ctx.selection.labelFor(el);
      el.dataset.lvbLabel = name;
      if (el.dataset.lvbId) {
        const content = ctx.content.ensure();
        const node = content.nodes.find((n) => n.id === el.dataset.lvbId);
        if (node) node.label = name;
        ctx.store.setState({ content });
        ctx.content.markContentDirty();
      }
    });
    paint(ctx, host);
  }, { once: true });
}

function dropIntent(row, clientY) {
  const r = row.getBoundingClientRect();
  const t = (clientY - r.top) / Math.max(r.height, 1);
  if (t < 0.28) return "before";
  if (t > 0.72) return "after";
  return "into";
}

function showDropLine(host, row, intent) {
  const line = host.querySelector("[data-role='layer-drop']");
  if (!line || !row) return;
  const r = row.getBoundingClientRect();
  const scroller = host.querySelector("[data-role='layer-scroll']");
  const sr = scroller.getBoundingClientRect();
  line.hidden = false;
  line.dataset.intent = intent;
  if (intent === "into") {
    line.style.top = `${r.top - sr.top + scroller.scrollTop}px`;
    line.style.height = `${r.height}px`;
    line.classList.add("is-into");
  } else {
    line.classList.remove("is-into");
    line.style.height = "2px";
    line.style.top = `${(intent === "before" ? r.top : r.bottom) - sr.top + scroller.scrollTop - 1}px`;
  }
  line.style.left = "0";
  line.style.right = "0";
}

function hideDropLine(host) {
  const line = host.querySelector("[data-role='layer-drop']");
  if (line) line.hidden = true;
}

function onClick(ctx, host, event) {
  const eye = event.target.closest("[data-layer-eye]");
  if (eye) {
    const el = query(eye.dataset.layerEye);
    if (el) ctx.widgets.setHidden(el, !(el.style.display === "none" || ctx.content.getEntry(ctx.selection.selectorFor(el))?.hide));
    return;
  }
  const lock = event.target.closest("[data-layer-lock]");
  if (lock) {
    const el = query(lock.dataset.layerLock);
    if (el) ctx.widgets.toggleLock(el);
    return;
  }
  const twist = event.target.closest("[data-layer-twist]");
  if (twist) {
    const key = twist.dataset.layerTwist;
    if (!ctx.session.layerState) ctx.session.layerState = new Map();
    ctx.session.layerState.set(key, twist.dataset.open !== "1");
    ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
    ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
    return;
  }
  const select = event.target.closest("[data-layer-select]") || event.target.closest("[data-layer]");
  if (!select) return;
  const selector = select.dataset.layerSelect || select.dataset.layer;
  const el = query(selector);
  if (!el) return;
  if (event.metaKey || event.ctrlKey) ctx.selection.toggle(el);
  else if (event.shiftKey) ctx.selection.toggle(el);
  else ctx.selection.set([el], el);
  el.scrollIntoView?.({ block: "nearest", inline: "nearest" });
}

function onDrop(ctx, event) {
  const row = event.target.closest("[data-layer]");
  const fromSel = ctx.session.dragLayer || event.dataTransfer?.getData("text/plain");
  ctx.session.dragLayer = "";
  if (!row || !fromSel) return;
  event.preventDefault();
  const src = query(fromSel);
  const dst = query(row.dataset.layer);
  if (!src || !dst || src === dst || src.contains(dst)) return;
  if (ctx.selection.isShell(src)) {
    ctx.content.setStatus("Shell niet herschikken", "dirty");
    return;
  }
  const intent = dropIntent(row, event.clientY);
  ctx.commands.capture("lagen", () => {
    if (!src.dataset.lvbId) {
      if (ctx.selection.canMutate(src)) {
        const z = (parseInt(src.style.zIndex || "1", 10) || 1) + 1;
        src.style.zIndex = String(z);
        ctx.content.applyProp(src, "z-index", String(z));
      }
      return;
    }
    if (!ctx.selection.canMutate(src, "reparent")) return;
    let parent = dst.parentElement;
    if (intent === "into" && (dst.dataset.lvbId || ctx.selection.isShell(dst))) {
      dst.appendChild(src);
      parent = dst;
    } else if (intent === "before") {
      dst.parentElement?.insertBefore(src, dst);
    } else {
      dst.parentElement?.insertBefore(src, dst.nextSibling);
    }
    const content = ctx.content.ensure();
    const node = content.nodes.find((n) => n.id === src.dataset.lvbId);
    if (node && parent) node.parent = ctx.selection.selectorFor(parent);
    ctx.content.syncNodesFromDom();
    ctx.store.setState({ content: ctx.content.ensure() });
    ctx.content.markContentDirty();
    ctx.content.setStatus(intent === "into" ? "Genest" : "Herschikt", "ok");
  });
  ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
  ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
}

function layerMenu(ctx, el) {
  return [
    { id: "rename", label: "Hernoemen", kbd: "F2", run: () => {
      ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
      ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
      if (el) ctx.selection.set([el], el);
    }},
    { id: "select-parent", label: "Select parent", run: () => {
      const parent = el?.parentElement;
      if (parent && !ctx.selection.isBuilderNode(parent) && parent.id !== "root") {
        ctx.selection.set([parent], parent);
      }
    }},
    { id: "select-children", label: "Select children", run: () => {
      const kids = [...(el?.children || [])].filter(
        (c) => c instanceof Element && !ctx.selection.isBuilderNode(c) && !ctx.selection.isShell(c),
      );
      if (kids.length) ctx.selection.set(kids, kids[0]);
    }},
    { id: "duplicate", label: "Dupliceren", kbd: "⌘D", run: () => ctx.registry.run("duplicate") },
    { id: "delete", label: "Verwijderen", kbd: "Del", run: () => ctx.registry.run("delete") },
    { sep: true },
    { id: "lock", label: ctx.selection.isLocked(el) ? "Unlock" : "Lock", run: () => ctx.registry.run("lock") },
    { id: "group", label: "Groeperen", run: () => ctx.registry.run("group") },
    { id: "ungroup", label: "Degroeperen", run: () => ctx.registry.run("ungroup") },
    { id: "detach", label: "Detach component", run: () => ctx.widgets.detachComponent(el), disabled: !el?.dataset?.lvbComponentId },
    { sep: true },
    { id: "front", label: "Naar voren", run: () => ctx.registry.run("forward") },
    { id: "back", label: "Naar achter", run: () => ctx.registry.run("backward") },
  ];
}
