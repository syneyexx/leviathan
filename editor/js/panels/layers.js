/**
 * Leviathan Visual Builder — layers tree, search, visibility, lock, reorder.
 */

import { escapeHtml } from "../util.js";

const ROW = 28;

export function createLayers(ctx) {
  let built = false;
  const panel = {
    id: "layers",
    title: "Lagen",
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
      });
      host.addEventListener("click", (event) => onClick(ctx, event));
      host.addEventListener("mouseover", (event) => {
        const row = event.target.closest("[data-layer]");
        if (!row) return;
        const el = query(row.dataset.layer);
        ctx.session.hoverEl = el;
        ctx.chrome.schedulePaint();
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
      });
      host.addEventListener("drop", (event) => onDrop(ctx, event));
      host.addEventListener("scroll", (event) => {
        if (event.target.dataset?.role === "layer-scroll") paint(ctx, host, true);
      }, true);
    },
    render() {
      if (!this.host) return;
      if (!built) {
        this.host.innerHTML = `<div class="lvb-layers-head">Lagen</div>
          <input data-role="layer-search" data-nohistory="1" placeholder="Filter lagen…" value="${escapeHtml(ctx.session.layerQuery || "")}" />
          <div class="lvb-layer-scroll" data-role="layer-scroll"><div data-role="layer-list"></div></div>`;
        built = true;
      }
      paint(ctx, this.host);
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

function walk(ctx, el, depth, acc) {
  if (!(el instanceof Element) || ctx.selection.isBuilderNode(el)) return;
  if (el.id === "lvb-live-overrides") return;
  const selector = ctx.selection.selectorFor(el);
  const label = ctx.selection.labelFor(el);
  const kids = [...el.children].filter((child) => !ctx.selection.isBuilderNode(child));
  if (!ctx.session.layerState) ctx.session.layerState = new Map();
  const stored = ctx.session.layerState.get(selector);
  const open = ctx.session.layerQuery ? true : stored == null ? depth < 2 : stored;
  acc.push({ el, depth, selector, label, kids: kids.length, open });
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
  return acc.filter((row) => row.label.toLowerCase().includes(q) || row.selector.toLowerCase().includes(q));
}

function paint(ctx, host, fromScroll = false) {
  const list = host.querySelector("[data-role='layer-list']");
  const scroller = host.querySelector("[data-role='layer-scroll']");
  if (!list || !scroller) return;
  const all = rows(ctx);
  const head = host.querySelector(".lvb-layers-head");
  if (head) head.textContent = `Lagen (${all.length})`;
  if (!fromScroll && document.activeElement?.dataset?.role !== "layer-search") {
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
      return `<div class="lvb-layer${active}${hidden ? " is-hidden" : ""}" draggable="true" data-layer="${escapeHtml(row.selector)}" style="${top == null ? `padding-left:${8 + row.depth * 12}px` : `position:absolute;top:${top}px;left:0;right:0;height:${ROW}px;padding-left:${8 + row.depth * 12}px`}">
        <button type="button" class="lvb-icon" data-layer-eye="${escapeHtml(row.selector)}" title="Zichtbaarheid">${hidden ? "○" : "●"}</button>
        <button type="button" class="lvb-icon" data-layer-lock="${escapeHtml(row.selector)}" title="Lock">${locked ? "🔒" : "○"}</button>
        <button type="button" class="lvb-icon" data-layer-twist="${escapeHtml(row.selector)}" data-open="${row.open ? "1" : "0"}">${row.kids ? (row.open ? "▾" : "▸") : ""}</button>
        <button type="button" class="lvb-layer-name" data-layer-select="${escapeHtml(row.selector)}">${escapeHtml(row.label)}</button>
      </div>`;
    })
    .join("");
}

function onClick(ctx, event) {
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
  if (event.shiftKey) ctx.selection.toggle(el);
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
  if (!src || !dst || src === dst) return;
  if (ctx.selection.isShell(src)) {
    ctx.content.setStatus("Shell niet herschikken", "dirty");
    return;
  }
  ctx.commands.capture("lagen", () => {
    if (src.dataset.lvbId && dst.parentElement && !src.contains(dst)) {
      dst.parentElement.insertBefore(src, dst);
      const content = ctx.content.ensure();
      const node = content.nodes.find((n) => n.id === src.dataset.lvbId);
      if (node && dst.parentElement) node.parent = ctx.selection.selectorFor(dst.parentElement);
      ctx.content.syncNodesFromDom();
      ctx.store.setState({ content: ctx.content.ensure() });
      ctx.content.markContentDirty();
    } else if (ctx.selection.canMutate(src)) {
      const z = (parseInt(src.style.zIndex || "1", 10) || 1) + 1;
      src.style.zIndex = String(z);
      ctx.content.applyProp(src, "z-index", String(z));
      ctx.content.setStatus("Z-index verhoogd", "ok");
    }
  });
  ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
  ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
}
