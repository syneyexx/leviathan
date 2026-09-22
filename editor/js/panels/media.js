/**
 * Leviathan Visual Builder — image library modal.
 */

import { escapeHtml } from "../util.js";

export function createMedia(ctx) {
  return {
    id: "media",
    title: "Media",
    zone: "modal",
    place: "dock",
    host: null,
    mode: "insert",
    _sig: null,
    signature() {
      return this.mode;
    },
    bind(host) {
      this.host = host;
      host.addEventListener("click", async (event) => {
        if (event.target.closest("[data-act='close-media']")) {
          host.hidden = true;
          return;
        }
        if (event.target.closest("[data-act='upload-image']")) {
          ctx.chrome.pickUpload(this.mode);
          return;
        }
        if (event.target.closest("[data-act='refresh-media']")) {
          await this.open(this.mode);
          return;
        }
        const item = event.target.closest("[data-asset-url]");
        if (!item) return;
        const url = item.dataset.assetUrl;
        try {
          if (this.mode === "replace" && ctx.session.primary?.tagName === "IMG") {
            const el = ctx.session.primary;
            const oldSrc = el.getAttribute("src") || "";
            ctx.commands.capture("image", () => {
              el.setAttribute("src", url);
              ctx.content.patchEntry(ctx.selection.selectorFor(el), { src: url });
            });
            if (oldSrc && oldSrc !== url && !el.dataset.lvbId) await ctx.api.replaceText(oldSrc, url);
            ctx.content.setStatus("Image vervangen", "ok");
          } else {
            ctx.widgets.insertImageAtUrl(url, item.title || "Image");
          }
          host.hidden = true;
        } catch (err) {
          ctx.content.setStatus(String(err.message || err), "dirty");
        }
      });
    },
    async open(mode = "insert") {
      this.mode = mode;
      if (!this.host) return;
      this.host.hidden = false;
      const title = this.host.querySelector("[data-role='media-title']");
      const grid = this.host.querySelector("[data-role='media-grid']");
      if (title) title.textContent = mode === "replace" ? "Image vervangen" : "Image toevoegen";
      if (grid) grid.innerHTML = `<p class="lvb-muted">Assets laden…</p>`;
      try {
        const data = await ctx.api.assets();
        const assets = data.assets || [];
        if (!grid) return;
        grid.innerHTML = assets.length
          ? assets
              .map(
                (a) => `<button type="button" class="lvb-media-item" data-asset-url="${escapeHtml(a.url)}" title="${escapeHtml(a.name)}">
                  <img src="${escapeHtml(a.url)}" alt="" />
                  <span>${escapeHtml(a.name)}</span>
                </button>`,
              )
              .join("")
          : `<p class="lvb-muted">Nog geen images. Upload er een.</p>`;
      } catch (err) {
        if (grid) grid.innerHTML = `<p class="lvb-muted">${escapeHtml(String(err.message || err))}</p>`;
      }
    },
    render() {
      if (!this.host || this.host.dataset.ready === "1") return;
      this.host.dataset.ready = "1";
      this.host.innerHTML = `<div class="lvb-media-head">
          <strong data-role="media-title">Image toevoegen</strong>
          <button type="button" class="lvb-btn" data-act="close-media">Sluiten</button>
        </div>
        <div class="lvb-media-actions">
          <button type="button" class="lvb-btn lvb-btn-primary" data-act="upload-image">Upload vanaf PC</button>
          <button type="button" class="lvb-btn" data-act="refresh-media">Ververs</button>
        </div>
        <p class="lvb-muted">Blijft opgeslagen in Leviathan, ook zonder editor.</p>
        <div class="lvb-media-grid" data-role="media-grid"></div>`;
    },
  };
}
