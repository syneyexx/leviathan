/**
 * Leviathan Visual Builder — lightweight components.
 */

import { escapeHtml } from "../util.js";

export function createComponents(ctx) {
  return {
    id: "components",
    title: "Componenten",
    zone: "right",
    place: "dock",
    host: null,
    _sig: null,
    signature() {
      return `${ctx.store.getState().uiEpoch || 0}|${ctx.content.ensure().components.length}`;
    },
    bind(host) {
      this.host = host;
      host.addEventListener("click", (event) => {
        if (event.target.closest("[data-act='create-component']")) ctx.widgets.createComponent();
        const id = event.target.closest("[data-insert-component]")?.dataset.insertComponent;
        if (id) ctx.widgets.insertComponent(id);
        const update = event.target.closest("[data-update-master]");
        if (update) {
          const card = update.closest("[data-component-card]");
          const html = card.querySelector("[data-role='master-html']")?.value || "";
          const variant = card.querySelector("[data-role='variant']")?.value || "";
          const name = card.querySelector("[data-role='name']")?.value || "";
          if (name) ctx.widgets.renameComponent(card.dataset.componentCard, name);
          ctx.widgets.updateMaster(card.dataset.componentCard, html, variant);
        }
      });
    },
    render() {
      if (!this.host) return;
      const list = ctx.content.ensure().components;
      this.host.innerHTML = `<p class="lvb-muted">Een component is een benoemd HTML-fragment. Master bijwerken vervangt instances en houdt hun style-overrides.</p>
        <button type="button" class="lvb-btn lvb-btn-primary" data-act="create-component">Maak component van selectie</button>
        ${list
          .map(
            (c) => `<article class="lvb-component" data-component-card="${escapeHtml(c.id)}">
              <label class="lvb-field"><span>Naam</span><input data-role="name" value="${escapeHtml(c.name || "")}" /></label>
              <label class="lvb-field"><span>Variant</span><input data-role="variant" value="${escapeHtml(c.variant || "")}" placeholder="optioneel" /></label>
              <label class="lvb-field"><span>Master HTML</span><textarea data-role="master-html" rows="5">${escapeHtml(c.html || "")}</textarea></label>
              <div class="lvb-chip-row">
                <button type="button" class="lvb-chip" data-insert-component="${escapeHtml(c.id)}">Invoegen</button>
                <button type="button" class="lvb-chip" data-update-master="${escapeHtml(c.id)}">Update instances</button>
              </div>
            </article>`,
          )
          .join("") || `<p class="lvb-muted">Nog leeg.</p>`}`;
    },
  };
}
