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
        const renameBtn = event.target.closest("[data-act='rename-token']");
        if (renameBtn) {
          const oldName = renameBtn.dataset.tokenName;
          const next = window.prompt(`Hernoem ${oldName} naar:`, oldName);
          if (!next || next === oldName) return;
          const newName = next.startsWith("--") ? next : `--${next.replace(/^-+/, "")}`;
          const plan = ctx.studio?.planTokenRename?.(oldName, newName);
          if (!plan || plan.empty) {
            ctx.content.setStatus(plan?.error || "Geen impact", "dirty");
            return;
          }
          const s = plan.summary;
          const ok = window.confirm(
            `Impact: ${s.entries} entries, ${s.files.length} CSS-bestanden, pages: ${s.pages.join(", ") || "—"}. Toepassen?`,
          );
          if (!ok) return;
          ctx.studio.applyImpact(plan, s.label);
          ctx.content.setStatus(`Token ${oldName} → ${newName}`, "ok");
          this._sig = null;
          this.render();
          return;
        }
        const btn = event.target.closest("[data-token-name]");
        if (!btn || btn.dataset.act === "rename-token") return;
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
              (token) => `<div class="lvb-token-row">
                <button type="button" class="lvb-token-card" data-token-name="${escapeHtml(token.name)}" data-token-group="${escapeHtml(token.group)}">
                <i style="background:${escapeHtml(token.group === "Kleuren" ? token.value : "#16120c")}"></i>
                <b>${escapeHtml(token.name.replace("--lv-", ""))}</b>
                <span>${escapeHtml(token.value)}</span>
              </button>
              <button type="button" class="lvb-mini" data-act="rename-token" data-token-name="${escapeHtml(token.name)}" title="Hernoem met impact preview">Rename</button>
              </div>`,
            )
            .join("")}</div>`,
        )
        .join("");
      const keep = this.host.querySelector("[data-role='token-filter']");
      const value = keep?.value || query;
      this.host.innerHTML = `<p class="lvb-muted">Klik kopieert <b>var(--lv-…)</b>. Shift-klik past toe. Rename toont Change Impact.</p>
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
