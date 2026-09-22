/**
 * Leviathan Visual Builder — image library modal.
 */

import { escapeHtml } from "../util.js";

function formatBytes(n) {
  if (!Number.isFinite(n)) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function formatWhen(ts) {
  if (!ts) return "";
  try {
    return new Date(ts * 1000).toLocaleString();
  } catch {
    return "";
  }
}

export function createMedia(ctx) {
  let uploadAbort = null;
  let usageCache = null;

  function usedOnPage() {
    if (usageCache) return usageCache;
    const urls = ctx.widgets?.referencedAssetUrls?.() || new Set();
    usageCache = urls;
    return urls;
  }

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
        if (event.target.closest("[data-act='cancel-upload']")) {
          uploadAbort?.abort();
          uploadAbort = null;
          const progress = host.querySelector("[data-role='upload-progress']");
          if (progress) progress.hidden = true;
          return;
        }
        if (event.target.closest("[data-act='refresh-media']")) {
          usageCache = null;
          await this.open(this.mode);
          return;
        }
        if (event.target.closest("[data-act='orphan-cleanup']")) {
          ctx.registry.run("orphan-cleanup");
          return;
        }
        const item = event.target.closest("[data-asset-url]");
        if (!item) return;
        const url = item.dataset.assetUrl;
        try {
          if (this.mode === "replace") {
            await ctx.widgets.replaceImageWithUrl(url);
            ctx.widgets.offerImageFit?.(ctx.session.primary);
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
      usageCache = null;
      if (!this.host) return;
      this.host.hidden = false;
      const title = this.host.querySelector("[data-role='media-title']");
      const grid = this.host.querySelector("[data-role='media-grid']");
      if (title) title.textContent = mode === "replace" ? "Image vervangen" : "Image toevoegen";
      if (grid) grid.innerHTML = `<p class="lvb-muted">Assets laden…</p>`;
      try {
        const data = await ctx.api.assets();
        const assets = data.assets || [];
        const used = usedOnPage();
        if (!grid) return;
        grid.innerHTML = assets.length
          ? assets
              .map((a) => {
                const onPage = used.has(a.url);
                const meta = [
                  a.ext?.toUpperCase() || "",
                  formatBytes(a.bytes),
                  formatWhen(a.mtime),
                ]
                  .filter(Boolean)
                  .join(" · ");
                return `<button type="button" class="lvb-media-item${onPage ? " is-used" : ""}" data-asset-url="${escapeHtml(a.url)}" title="${escapeHtml(a.name)}">
                  <img src="${escapeHtml(a.url)}" alt="" loading="lazy" data-probe="1" />
                  <span class="lvb-media-name">${escapeHtml(a.name)}</span>
                  <span class="lvb-media-meta" data-meta="${escapeHtml(a.url)}">${escapeHtml(meta)}</span>
                  ${onPage ? `<span class="lvb-media-badge">Used on this page</span>` : ""}
                </button>`;
              })
              .join("")
          : `<p class="lvb-muted">Nog geen images. Upload er een (PNG, JPG, SVG, WebP).</p>`;
        // Probe natural dimensions after load
        grid.querySelectorAll("img[data-probe]").forEach((img) => {
          const done = () => {
            if (!img.naturalWidth) return;
            const meta = img.parentElement?.querySelector("[data-meta]");
            if (meta && !meta.dataset.dims) {
              meta.dataset.dims = "1";
              meta.textContent = `${img.naturalWidth}×${img.naturalHeight} · ${meta.textContent}`;
            }
          };
          if (img.complete) done();
          else img.addEventListener("load", done, { once: true });
        });
      } catch (err) {
        if (grid) grid.innerHTML = `<p class="lvb-muted">${escapeHtml(String(err.message || err))}</p>`;
      }
    },
    beginUploadProgress() {
      uploadAbort = typeof AbortController !== "undefined" ? new AbortController() : null;
      const progress = this.host?.querySelector("[data-role='upload-progress']");
      if (progress) {
        progress.hidden = false;
        progress.querySelector("[data-role='upload-label']").textContent = "Uploaden…";
      }
      return uploadAbort?.signal;
    },
    endUploadProgress() {
      uploadAbort = null;
      const progress = this.host?.querySelector("[data-role='upload-progress']");
      if (progress) progress.hidden = true;
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
          <button type="button" class="lvb-btn" data-act="orphan-cleanup" title="Alleen orphans — nooit auto bij replace">Orphan cleanup…</button>
        </div>
        <div class="lvb-upload-progress" data-role="upload-progress" hidden>
          <span data-role="upload-label">Uploaden…</span>
          <button type="button" class="lvb-mini" data-act="cancel-upload">Annuleren</button>
        </div>
        <p class="lvb-muted">PNG · JPG · SVG · WebP. Replace verwijdert nooit automatisch assets die elders nog in gebruik zijn.</p>
        <div class="lvb-media-grid" data-role="media-grid"></div>`;
    },
  };
}
