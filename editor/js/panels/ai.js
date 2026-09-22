/**
 * LEVIATHAN STUDIO — AI inspector panel (OmniRoute-backed).
 * Preview-first: Generate → Review → Accept / Reject / Regenerate.
 */

import { PLACEMENTS, STYLE_SOURCES } from "../ai/protocol.js";
import { AiPhase, isBusy } from "../ai/state.js";

export function createAi(ctx) {
  let host;
  let tools = null;

  function ensureTools() {
    if (!tools) tools = ctx.ai || null;
    return tools;
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  return {
    id: "ai",
    title: "AI",
    zone: "right",
    bind(el) {
      host = el;
    },
    signature() {
      const ai = ensureTools()?.getState?.() || {};
      return `${ctx.store.getState().sel}|${ai.phase}|${ai.preview?.requestId || ""}|${ai.error?.message || ""}|${ctx.store.getState().uiEpoch}`;
    },
    render() {
      if (!host) return;
      const ai = ensureTools();
      if (!ai) {
        host.innerHTML = `<h3>AI / Generate</h3><p class="lvb-muted">AI tools not initialized.</p>`;
        return;
      }
      const st = ai.getState();
      const primary = ctx.session.primary;
      const tasks = ai.applicableTasks();
      const caps = st.capabilities;
      const busy = isBusy(st.phase);
      const preview = st.preview;
      const selected = preview ? ai.previewCtrl.selectedVariant(preview) : null;

      const dimLabel =
        st.width && st.height
          ? `${st.width} × ${st.height}${st.width && st.height ? ` · ${(st.width / st.height).toFixed(2)}` : ""}`
          : "—";

      const roleLabel = (() => {
        if (!primary) return "No selection";
        if (primary.tagName === "IMG") return "Image";
        const role = st.target?.role?.value;
        return role || primary.tagName.toLowerCase();
      })();

      const capBanner = !caps
        ? `<p class="lvb-muted">Checking capabilities…</p>`
        : !caps.available
          ? `<div class="lvb-ai-banner lvb-ai-banner-warn" role="status">
              <strong>AI unavailable</strong>
              <span>${escapeHtml(
                caps.disabledReason ||
                  caps.reason ||
                  "No provider configured. Editor remains fully usable. Set LEVIATHAN_EDITOR_AI_MOCK=1 for dev previews or configure an image endpoint.",
              )}</span>
            </div>`
          : caps.mockEnabled
            ? `<div class="lvb-ai-banner lvb-ai-banner-mock" role="status">
                <strong>Dev mock provider</strong>
                <span>Outputs are deterministic placeholders — not real AI generations.</span>
              </div>`
            : "";

      const taskOptions = tasks
        .map((t) => {
          const disabled = t.enabled === false ? "disabled" : "";
          const sel = st.task === t.id ? "selected" : "";
          return `<option value="${t.id}" ${sel} ${disabled}>${escapeHtml(t.label)}${t.enabled === false ? " (unavailable)" : ""}</option>`;
        })
        .join("");

      const styleOptions = STYLE_SOURCES.map(
        (s) => `<option value="${s.id}" ${st.styleSource === s.id ? "selected" : ""}>${escapeHtml(s.label)}</option>`,
      ).join("");

      const placeOptions = PLACEMENTS.map(
        (p) => `<option value="${p.id}" ${st.placement === p.id ? "selected" : ""}>${escapeHtml(p.label)}</option>`,
      ).join("");

      const contextLines = (st.contextSummary || []).map((l) => `<li>${escapeHtml(l)}</li>`).join("") || "<li class=\"lvb-muted\">Collects on Generate</li>";

      const statusLine = (() => {
        if (st.phase === AiPhase.GENERATING || st.phase === AiPhase.SUBMITTING) return "Generating…";
        if (st.phase === AiPhase.CAPTURING_SNAPSHOT) return "Capturing visual context…";
        if (st.phase === AiPhase.CAPTURING_CONTEXT) return "Collecting context…";
        if (st.phase === AiPhase.APPLYING) return "Applying…";
        if (st.phase === AiPhase.ERROR) return st.error?.message || "Error";
        if (st.phase === AiPhase.PREVIEW_READY) return "Preview ready — Accept to persist";
        if (st.phase === AiPhase.CANCELLED) return "Cancelled";
        return "";
      })();

      let previewHtml = "";
      if (preview && preview.kind === "text_preview") {
        previewHtml = `
          <div class="lvb-ai-preview" data-role="preview">
            <div class="lvb-ai-preview-label">Text preview</div>
            <pre class="lvb-ai-text-preview">${escapeHtml(preview.text || "")}</pre>
          </div>`;
      } else if (preview && preview.kind === "analysis") {
        previewHtml = `
          <div class="lvb-ai-preview">
            <div class="lvb-ai-preview-label">Style analysis</div>
            <pre class="lvb-ai-text-preview">${escapeHtml(JSON.stringify(preview.analysis || {}, null, 2))}</pre>
          </div>`;
      } else if (preview && preview.kind === "action_preview") {
        previewHtml = `
          <div class="lvb-ai-preview">
            <div class="lvb-ai-preview-label">Proposed actions (${(preview.actions || []).length})</div>
            <pre class="lvb-ai-text-preview">${escapeHtml(JSON.stringify(preview.actions || [], null, 2))}</pre>
          </div>`;
      } else if (preview?.variants?.length) {
        const thumbs = preview.variants
          .map(
            (v, i) => `
            <button type="button" class="lvb-ai-thumb${i === preview.selectedIndex ? " is-on" : ""}" data-act="pick-variant" data-idx="${i}" aria-label="Variant ${i + 1}">
              <img src="${escapeHtml(v.url || "")}" alt="" />
              ${v.isMock || preview.provider?.isMock ? `<span class="lvb-ai-mock-tag">MOCK</span>` : ""}
            </button>`,
          )
          .join("");
        const compare =
          st.target?.assetUrl && selected?.url
            ? `<div class="lvb-ai-compare">
                <div><span>Original</span><img src="${escapeHtml(st.target.assetUrl)}" alt="Original" /></div>
                <div><span>New</span><img src="${escapeHtml(selected.url)}" alt="Generated" /></div>
              </div>`
            : selected?.url
              ? `<div class="lvb-ai-hero-preview"><img src="${escapeHtml(selected.url)}" alt="Generated preview" /></div>`
              : "";
        previewHtml = `
          <div class="lvb-ai-preview" data-role="preview">
            <div class="lvb-ai-preview-label">
              Preview · target ${escapeHtml(st.target?.key || "—")}
              ${preview.provider?.isMock ? " · MOCK" : ""}
            </div>
            ${compare}
            <div class="lvb-ai-thumbs">${thumbs}</div>
            <div class="lvb-muted lvb-ai-meta">
              Requested ${preview.requestedSize?.width || "?"}×${preview.requestedSize?.height || "?"}
              · Generated ${selected?.width || preview.generatedSize?.width || "?"}×${selected?.height || preview.generatedSize?.height || "?"}
              ${preview.provider?.id ? ` · ${escapeHtml(preview.provider.id)}` : ""}
              ${preview.diagnostics?.degradedContext ? ` · degraded (${escapeHtml(preview.diagnostics.degradeReason || "")})` : ""}
            </div>
          </div>`;
      }

      host.innerHTML = `
        <h3>AI / Generate</h3>
        ${capBanner}
        <div class="lvb-field"><label for="lvb-ai-task">Task</label>
          <select id="lvb-ai-task" data-role="task">${taskOptions}</select>
        </div>
        <div class="lvb-field" style="grid-template-columns:1fr"><label for="lvb-ai-prompt">Prompt</label>
          <textarea id="lvb-ai-prompt" data-role="instruction" rows="4" placeholder="Maak hier een afbeelding … in deze stijl">${escapeHtml(st.instruction)}</textarea>
        </div>
        <div class="lvb-ai-target">
          <div><strong>Target</strong> · ${escapeHtml(roleLabel)}</div>
          <div class="lvb-muted">${escapeHtml(dimLabel)}</div>
          <label class="lvb-ai-check"><input type="checkbox" data-role="use-dims" ${st.useSelectionDimensions ? "checked" : ""}/> Use selection dimensions</label>
        </div>
        <div class="lvb-field"><label for="lvb-ai-style">Style source</label>
          <select id="lvb-ai-style" data-role="style-source">${styleOptions}</select>
        </div>
        <div class="lvb-field" style="grid-template-columns:1fr" data-role="custom-style-wrap" ${st.styleSource === "custom" ? "" : "hidden"}>
          <label for="lvb-ai-custom">Custom style notes</label>
          <textarea id="lvb-ai-custom" data-role="custom-style" rows="2">${escapeHtml(st.customStyle)}</textarea>
        </div>
        <fieldset class="lvb-ai-context">
          <legend>Context</legend>
          <label class="lvb-ai-check"><input type="checkbox" data-ctx="pageVisual" ${st.contextOpts.pageVisual ? "checked" : ""}/> Page visual</label>
          <label class="lvb-ai-check"><input type="checkbox" data-ctx="selectionVisual" ${st.contextOpts.selectionVisual ? "checked" : ""}/> Selected region</label>
          <label class="lvb-ai-check"><input type="checkbox" data-ctx="themeTokens" ${st.contextOpts.themeTokens ? "checked" : ""}/> Theme tokens</label>
          <label class="lvb-ai-check"><input type="checkbox" data-ctx="nearby" ${st.contextOpts.nearby ? "checked" : ""}/> Nearby context</label>
          <label class="lvb-ai-check"><input type="checkbox" data-ctx="existingImage" ${st.contextOpts.existingImage ? "checked" : ""}/> Existing image</label>
        </fieldset>
        <div class="lvb-field"><label for="lvb-ai-place">Placement</label>
          <select id="lvb-ai-place" data-role="placement">${placeOptions}</select>
        </div>
        <div class="lvb-field"><label for="lvb-ai-variants">Variants</label>
          <select id="lvb-ai-variants" data-role="variants">
            ${[1, 2, 4].map((n) => `<option value="${n}" ${st.variants === n ? "selected" : ""}>${n}</option>`).join("")}
          </select>
        </div>
        <details class="lvb-ai-summary">
          <summary>Context summary</summary>
          <ul>${contextLines}</ul>
        </details>
        <div class="lvb-ai-actions">
          <button type="button" class="lvb-btn lvb-btn-primary" data-act="generate" ${busy ? "disabled" : ""}>Generate</button>
          <button type="button" class="lvb-btn" data-act="cancel" ${busy ? "" : "disabled"}>Cancel</button>
        </div>
        <p class="lvb-ai-status" data-role="status" role="status">${escapeHtml(statusLine)}</p>
        ${previewHtml}
        ${
          preview
            ? `<div class="lvb-ai-actions">
                <button type="button" class="lvb-btn lvb-btn-primary" data-act="accept">Accept</button>
                <button type="button" class="lvb-btn" data-act="reject">Reject</button>
                <button type="button" class="lvb-btn" data-act="regenerate" ${busy ? "disabled" : ""}>Regenerate</button>
              </div>
              <details class="lvb-ai-diag">
                <summary>Diagnostics</summary>
                <pre>${escapeHtml(
                  JSON.stringify(
                    {
                      requestId: preview.requestId,
                      provider: preview.provider,
                      durationMs: st.lastDurationMs,
                      routing: preview.diagnostics?.routing,
                      degraded: preview.diagnostics?.degradedContext,
                    },
                    null,
                    2,
                  ),
                )}</pre>
              </details>`
            : ""
        }
        ${
          st.error && st.phase === AiPhase.ERROR
            ? `<details class="lvb-ai-diag"><summary>Error details</summary><pre>${escapeHtml(JSON.stringify(st.error, null, 2))}</pre></details>`
            : ""
        }
      `;

      bind(host, ai);
    },
  };

  function bind(root, ai) {
    root.querySelector("[data-role='task']")?.addEventListener("change", (e) => {
      ai.patch({ task: e.target.value });
    });
    root.querySelector("[data-role='instruction']")?.addEventListener("input", (e) => {
      ai.patch({ instruction: e.target.value });
    });
    root.querySelector("[data-role='style-source']")?.addEventListener("change", (e) => {
      ai.patch({ styleSource: e.target.value });
      const wrap = root.querySelector("[data-role='custom-style-wrap']");
      if (wrap) wrap.hidden = e.target.value !== "custom";
    });
    root.querySelector("[data-role='custom-style']")?.addEventListener("input", (e) => {
      ai.patch({ customStyle: e.target.value });
    });
    root.querySelector("[data-role='placement']")?.addEventListener("change", (e) => {
      ai.patch({ placement: e.target.value });
    });
    root.querySelector("[data-role='variants']")?.addEventListener("change", (e) => {
      ai.patch({ variants: Number(e.target.value) || 1 });
    });
    root.querySelector("[data-role='use-dims']")?.addEventListener("change", (e) => {
      ai.patch({ useSelectionDimensions: e.target.checked });
      if (e.target.checked) ai.syncDimensionsFromSelection();
    });
    root.querySelectorAll("[data-ctx]").forEach((input) => {
      input.addEventListener("change", () => {
        const key = input.getAttribute("data-ctx");
        const opts = { ...ai.getState().contextOpts, [key]: input.checked };
        ai.patch({ contextOpts: opts });
      });
    });
    root.querySelector("[data-act='generate']")?.addEventListener("click", () => {
      ai.generate_asset();
    });
    root.querySelector("[data-act='regenerate']")?.addEventListener("click", () => {
      ai.regenerate();
    });
    root.querySelector("[data-act='cancel']")?.addEventListener("click", () => {
      ai.cancel();
    });
    root.querySelector("[data-act='accept']")?.addEventListener("click", () => {
      ai.accept_preview();
    });
    root.querySelector("[data-act='reject']")?.addEventListener("click", () => {
      ai.reject_preview();
    });
    root.querySelectorAll("[data-act='pick-variant']").forEach((btn) => {
      btn.addEventListener("click", () => {
        ai.select_variant(Number(btn.dataset.idx) || 0);
      });
    });
    root.querySelector("[data-role='instruction']")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        ai.generate_asset();
      }
    });
  }
}
