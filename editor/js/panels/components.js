/**
 * Leviathan Visual Builder — component library (frontier).
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
      const primary = ctx.session.primary;
      const inst = primary?.dataset?.lvbComponentId || "";
      return `${ctx.store.getState().uiEpoch || 0}|${ctx.content.ensure().components.length}|${inst}`;
    },
    bind(host) {
      this.host = host;
      host.addEventListener("click", (event) => {
        if (event.target.closest("[data-act='create-component']")) ctx.widgets.createComponent();
        if (event.target.closest("[data-act='detach']")) ctx.widgets.detachComponent();
        const id = event.target.closest("[data-insert-component]")?.dataset.insertComponent;
        if (id) {
          const card = event.target.closest("[data-component-card]");
          const variant = card?.querySelector("[data-role='insert-variant']")?.value || "";
          ctx.widgets.insertComponent(id, variant || undefined);
        }
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
      const primary = ctx.session.primary;
      const instanceId = primary?.dataset?.lvbComponentId || "";
      const instanceVariant = primary?.dataset?.lvbVariant || "";
      this.host.innerHTML = `<p class="lvb-muted">Componenten zijn gekoppelde masters. Instances houden style-, tekst- en src-overrides. Detach maakt een losse kopie.</p>
        <button type="button" class="lvb-btn lvb-btn-primary" data-act="create-component">Maak component van selectie</button>
        ${instanceId ? `<div class="lvb-section">Selectie is instance</div>
          <p class="lvb-muted">${escapeHtml(instanceId)}${instanceVariant ? ` · ${escapeHtml(instanceVariant)}` : ""}</p>
          <button type="button" class="lvb-btn" data-act="detach">Detach instance</button>` : ""}
        ${list
          .map((c) => {
            const variants = Object.keys(c.variants || {});
            return `<article class="lvb-component" data-component-card="${escapeHtml(c.id)}">
              <div class="lvb-component-preview" aria-hidden="true">${previewThumb(c.html)}</div>
              <label class="lvb-field"><span>Naam</span><input data-role="name" value="${escapeHtml(c.name || "")}" /></label>
              <label class="lvb-field"><span>Variant (master)</span><input data-role="variant" value="${escapeHtml(c.variant || "")}" placeholder="default" /></label>
              ${variants.length ? `<label class="lvb-field"><span>Invoegen als</span>
                <select data-role="insert-variant">
                  <option value="">default</option>
                  ${variants.map((v) => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join("")}
                </select>
              </label>` : ""}
              <label class="lvb-field"><span>Master HTML</span><textarea data-role="master-html" rows="4">${escapeHtml(c.html || "")}</textarea></label>
              <div class="lvb-chip-row">
                <button type="button" class="lvb-chip" data-insert-component="${escapeHtml(c.id)}">Invoegen</button>
                <button type="button" class="lvb-chip" data-update-master="${escapeHtml(c.id)}">Update instances</button>
              </div>
            </article>`;
          })
          .join("") || `<p class="lvb-muted">Nog leeg — selecteer een widget en maak een component.</p>`}`;
    },
  };
}

function previewThumb(html) {
  const plain = String(html || "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 48);
  return escapeHtml(plain || "component");
}
