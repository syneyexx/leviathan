/**
 * Leviathan Visual Builder — Diagnostics / Performance panel.
 */

import { escapeHtml } from "../util.js";

export function createDiagnosticsPanel(ctx) {
  let timer = 0;
  const panel = {
    id: "diagnostics",
    title: "Diagnostics",
    zone: "right",
    place: "dock",
    host: null,
    _sig: null,
    signature() {
      const s = ctx.store.getState();
      return `diag|${s.uiEpoch || 0}|${Math.floor((ctx.renderer?.getStats?.()?.paintCount || 0) / 15)}`;
    },
    bind(host) {
      this.host = host;
      host.addEventListener("click", (event) => {
        if (event.target.closest("[data-act='diag-refresh']")) {
          this._sig = null;
          this.render();
        }
        if (event.target.closest("[data-act='diag-copy']")) {
          const snap = ctx.diagnostics.snapshot();
          navigator.clipboard?.writeText(JSON.stringify(snap, null, 2));
          ctx.content.setStatus("Diagnostics schema gekopieerd", "ok");
        }
      });
    },
    render() {
      if (!this.host) return;
      const snap = ctx.diagnostics.snapshot();
      const r = snap.renderer;
      const e = snap.editor;
      const gpu = snap.gpu;
      this.host.innerHTML = `
        <p class="lvb-muted">Live paint / GPU / geheugen. Backend: <b>${escapeHtml(r.backend)}</b></p>
        <div class="lvb-diag-grid">
          <div class="lvb-diag-card">
            <div class="lvb-diag-label">FPS</div>
            <div class="lvb-diag-value">${r.fps.toFixed(0)}</div>
            ${ctx.diagnostics.sparkline("fps", 140, 32)}
          </div>
          <div class="lvb-diag-card">
            <div class="lvb-diag-label">Frame</div>
            <div class="lvb-diag-value">${r.frameMs.toFixed(2)} ms</div>
            ${ctx.diagnostics.sparkline("frameMs", 140, 32)}
          </div>
          <div class="lvb-diag-card">
            <div class="lvb-diag-label">Scene nodes</div>
            <div class="lvb-diag-value">${r.sceneNodes}</div>
            ${ctx.diagnostics.sparkline("sceneNodes", 140, 32)}
          </div>
          <div class="lvb-diag-card">
            <div class="lvb-diag-label">JS heap</div>
            <div class="lvb-diag-value">${snap.memory.jsHeapMb ? `${snap.memory.jsHeapMb} MB` : "n/a"}</div>
            ${ctx.diagnostics.sparkline("heapMb", 140, 32)}
          </div>
        </div>
        <div class="lvb-section">Editor</div>
        <div class="lvb-diag-kv">
          <span>Pagina</span><b>${escapeHtml(e.page)}</b>
          <span>Selectie</span><b>${e.selected}</b>
          <span>Guides</span><b>${e.guides}</b>
          <span>Content nodes</span><b>${e.contentNodes}</b>
          <span>Entries</span><b>${e.contentEntries}</b>
          <span>Components</span><b>${e.components}</b>
          <span>History</span><b>${e.historyDepth}</b>
          <span>Dirty</span><b>${e.dirty ? "ja" : "nee"}</b>
          <span>Auto-save</span><b>${e.autoSave ? "aan" : "uit"}</b>
          <span>Tool</span><b>${escapeHtml(e.tool || "")}</b>
          <span>Zoom</span><b>${Math.round((e.zoom || 1) * 100)}%</b>
          <span>Phase</span><b>${escapeHtml(e.phase || "")}</b>
        </div>
        <div class="lvb-section">GPU</div>
        ${
          gpu?.active !== false && r.backend === "webgpu"
            ? `<div class="lvb-diag-kv">
                <span>Draws</span><b>${gpu.drawCount ?? "—"}</b>
                <span>GPU frame</span><b>${gpu.lastFrameMs != null ? `${Number(gpu.lastFrameMs).toFixed(2)} ms` : "—"}</b>
                <span>VRAM est.</span><b>${gpu.vramEstimateMb != null ? `${gpu.vramEstimateMb} MB` : "—"}</b>
                <span>Canvas</span><b>${gpu.canvas ? `${gpu.canvas.width}×${gpu.canvas.height}` : "—"}</b>
              </div>
              <details class="lvb-fold"><summary>Adapter / limits</summary>
                <pre class="lvb-ai-preview">${escapeHtml(JSON.stringify({ adapter: gpu.adapter, limits: gpu.limits, features: gpu.features }, null, 2))}</pre>
              </details>`
            : `<p class="lvb-muted">${navigator.gpu ? "WebGPU beschikbaar maar fallback actief." : "Geen navigator.gpu — DOM paint fallback."}</p>`
        }
        <div class="lvb-section">Schema</div>
        <div class="lvb-chip-row">
          <button type="button" class="lvb-chip" data-act="diag-refresh">Vernieuwen</button>
          <button type="button" class="lvb-chip" data-act="diag-copy">Kopieer JSON</button>
        </div>
        <pre class="lvb-ai-preview" data-role="diag-schema">${escapeHtml(JSON.stringify(snap, null, 2))}</pre>`;

      clearInterval(timer);
      timer = setInterval(() => {
        if (!this.host || this.host.hidden) return;
        if (document.activeElement?.closest?.("[data-host='diagnostics']") && document.activeElement.tagName === "PRE") return;
        this._sig = null;
        this.render();
      }, 1500);
    },
  };
  return panel;
}
