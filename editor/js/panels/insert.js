/**
 * Leviathan Visual Builder — insert panel.
 */

import { escapeHtml } from "../util.js";

export function createInsert(ctx) {
  return {
    id: "insert",
    title: "Insert",
    zone: "left",
    place: "dock",
    host: null,
    _sig: null,
    signature() {
      const content = ctx.store.getState().content;
      return `${content?.components?.length || 0}|${ctx.store.getState().uiEpoch || 0}`;
    },
    bind(host) {
      this.host = host;
      host.addEventListener("click", (event) => {
        const type = event.target.closest("[data-insert]")?.dataset.insert;
        if (type) ctx.widgets.insertPreset(type);
        const id = event.target.closest("[data-component]")?.dataset.component;
        if (id) ctx.widgets.insertComponent(id);
        if (event.target.closest("[data-act='add-image']")) ctx.chrome.openMedia("insert");
      });
    },
    render() {
      if (!this.host) return;
      const components = ctx.content.ensure().components || [];
      this.host.innerHTML = `<div class="lvb-section">Elementen</div>
        <div class="lvb-insert-grid">
          ${[
            ["text", "Tekst"],
            ["heading", "Titel"],
            ["box", "Box"],
            ["button", "Knop"],
            ["divider", "Lijn"],
          ]
            .map(([id, label]) => `<button type="button" class="lvb-insert" data-insert="${id}"><b>${label}</b><span>Widget</span></button>`)
            .join("")}
          <button type="button" class="lvb-insert" data-act="add-image"><b>Image</b><span>Upload of bibliotheek</span></button>
        </div>
        <div class="lvb-section">Componenten</div>
        ${
          components.length
            ? components
                .map(
                  (c) => `<button type="button" class="lvb-insert" data-component="${escapeHtml(c.id)}"><b>${escapeHtml(c.name || c.id)}</b><span>${escapeHtml(c.variant || "master")}</span></button>`,
                )
                .join("")
            : `<p class="lvb-muted">Nog geen componenten. Maak er een vanuit de selectie.</p>`
        }`;
    },
  };
}
