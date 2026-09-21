/**
 * Leviathan Visual Builder — design tokens.
 */

import { escapeHtml, fuzzyScore } from "../util.js";

export function createTokensPanel(ctx) {
  let query = "";
  return {
    id: "tokens",
    title: "Tokens",
    zone: "right",
    place: "dock",
    host: null,
    _sig: null,
    signature() {
      return `${(ctx.store.getState().files["tokens.css"] || "").length}|${query}|${ctx.store.getState().uiEpoch || 0}`;
    },
    bind(host) {
      this.host = host;
      host.addEventListener("input", (event) => {
        if (event.target.dataset?.role === "token-filter") {
          query = event.target.value || "";
          this._sig = null;
          this.render();
        }
      });
      host.addEventListener("click", (event) => {
        const btn = event.target.closest("[data-token-name]");
        if (!btn) return;
        const name = btn.dataset.tokenName;
        const prop = propForToken(name, btn.dataset.tokenGroup);
        const el = ctx.session.primary;
        if (el && prop && event.shiftKey) {
          ctx.commands.capture("token", () => ctx.content.applyProp(el, prop, `var(${name})`));
          ctx.content.setStatus(`${name} → ${prop}`, "ok");
          return;
        }
        try {
          navigator.clipboard?.writeText(`var(${name})`);
        } catch {
          /* ignore */
        }
        ctx.content.setStatus(`var(${name}) gekopieerd`, "ok");
      });
    },
    render() {
      if (!this.host) return;
      const groups = new Map();
      for (const token of ctx.tokens()) {
        if (query && fuzzyScore(query, `${token.name} ${token.value}`) <= 0) continue;
        if (!groups.has(token.group)) groups.set(token.group, []);
        groups.get(token.group).push(token);
      }
      const body = [...groups.entries()]
        .map(
          ([group, list]) => `<div class="lvb-section">${escapeHtml(group)}</div><div class="lvb-token-grid">${list
            .map(
              (token) => `<button type="button" class="lvb-token-card" data-token-name="${escapeHtml(token.name)}" data-token-group="${escapeHtml(token.group)}">
                <i style="background:${escapeHtml(token.group === "Kleuren" ? token.value : "#16120c")}"></i>
                <b>${escapeHtml(token.name.replace("--lv-", ""))}</b>
                <span>${escapeHtml(token.value)}</span>
              </button>`,
            )
            .join("")}</div>`,
        )
        .join("");
      const keep = this.host.querySelector("[data-role='token-filter']");
      const value = keep?.value || query;
      this.host.innerHTML = `<p class="lvb-muted">Klik kopieert <b>var(--lv-…)</b>. Shift-klik past toe op de selectie.</p>
        <input data-role="token-filter" data-nohistory="1" placeholder="Zoek token…" value="${escapeHtml(value)}" />
        ${body || `<p class="lvb-muted">Geen tokens in tokens.css</p>`}`;
      const input = this.host.querySelector("[data-role='token-filter']");
      if (input && document.activeElement !== input && query) input.focus();
    },
  };
}

function propForToken(name, group) {
  if (group === "Kleuren") return "color";
  if (/radius/.test(name)) return "border-radius";
  if (/font-display|font-ui|font-mono/.test(name)) return "font-family";
  if (/text-|heading-|hero-|brand-title/.test(name)) return "font-size";
  if (/tracking/.test(name)) return "letter-spacing";
  if (/shadow|glow/.test(name)) return "box-shadow";
  if (/gap|pad/.test(name)) return "padding";
  return "color";
}
