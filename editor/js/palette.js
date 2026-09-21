/**
 * Leviathan Visual Builder — command palette.
 */

import { escapeHtml, fuzzyScore } from "./util.js";

export function createPalette(ctx) {
  let open = false;
  let index = 0;
  let items = [];

  function node() {
    return ctx.chrome.ui().palette;
  }

  function isOpen() {
    return open;
  }

  function layerHits(query) {
    const root = document.getElementById("root");
    if (!root || !query.trim()) return [];
    const hits = [];
    root.querySelectorAll("[class*='lv-'], [data-lvb-id], img, h1, h2, h3, button").forEach((el) => {
      if (ctx.selection.isBuilderNode(el)) return;
      const label = ctx.selection.labelFor(el);
      const score = fuzzyScore(query, `${label} ${ctx.selection.selectorFor(el)}`);
      if (score > 0) hits.push({ el, label, score });
    });
    return hits.sort((a, b) => b.score - a.score).slice(0, 8);
  }

  function render(query = "") {
    const host = node();
    if (!host) return;
    const commands = query.trim() ? ctx.registry.search(query).slice(0, 12) : ctx.registry.recent().concat(ctx.registry.list().slice(0, 8));
    const unique = [];
    const seen = new Set();
    for (const cmd of commands) {
      if (!cmd || seen.has(cmd.id)) continue;
      seen.add(cmd.id);
      unique.push(cmd);
    }
    const layers = layerHits(query);
    items = [
      ...unique.map((cmd) => ({ type: "command", cmd })),
      ...layers.map((hit) => ({ type: "layer", ...hit })),
    ];
    if (index >= items.length) index = 0;
    host.hidden = false;
    host.innerHTML = `<div class="lvb-palette-card">
        <input data-role="palette-input" placeholder="Zoek commando of laag…" value="${escapeHtml(query)}" />
        <div class="lvb-palette-list">
          ${items
            .map((item, i) => {
              if (item.type === "command") {
                return `<button type="button" class="lvb-palette-item${i === index ? " is-on" : ""}" data-index="${i}">
                  <span>${escapeHtml(item.cmd.title)}</span><kbd>${escapeHtml(item.cmd.keys[0] || item.cmd.group)}</kbd>
                </button>`;
              }
              return `<button type="button" class="lvb-palette-item${i === index ? " is-on" : ""}" data-index="${i}">
                  <span>Laag · ${escapeHtml(item.label)}</span><kbd>select</kbd>
                </button>`;
            })
            .join("") || `<p class="lvb-muted">Geen resultaten</p>`}
        </div>
        <footer>↑↓ navigeren · Enter uitvoeren · Esc sluiten · shortcuts staan in Help</footer>
      </div>`;
    const input = host.querySelector("[data-role='palette-input']");
    input?.focus();
    if (query) {
      input.value = query;
      input.setSelectionRange(query.length, query.length);
    }
    input?.addEventListener("input", () => render(input.value));
    input?.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        index = Math.min(items.length - 1, index + 1);
        paintActive();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        index = Math.max(0, index - 1);
        paintActive();
      } else if (event.key === "Enter") {
        event.preventDefault();
        choose(index);
      } else if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    });
    host.querySelectorAll("[data-index]").forEach((btn) => {
      btn.addEventListener("click", () => choose(Number(btn.dataset.index)));
    });
    open = true;
  }

  function paintActive() {
    node()?.querySelectorAll(".lvb-palette-item").forEach((el, i) => el.classList.toggle("is-on", i === index));
  }

  function choose(i) {
    const item = items[i];
    close();
    if (!item) return;
    if (item.type === "command") ctx.registry.run(item.cmd.id);
    else if (item.el) {
      ctx.selection.set([item.el], item.el);
      item.el.scrollIntoView?.({ block: "nearest" });
    }
  }

  function toggle(force) {
    if (force === false || open) close();
    else render("");
  }

  function close() {
    open = false;
    const host = node();
    if (host) {
      host.hidden = true;
      host.innerHTML = "";
    }
  }

  return { toggle, close, isOpen, render };
}
