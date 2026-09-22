/**
 * Preview lifecycle — non-destructive AI candidates.
 * Selecting a variant ≠ accepting. Reject cleans without history entries.
 */

import { AiPhase } from "./state.js";

export function createPreviewController(ctx) {
  const objectUrls = new Set();

  function trackUrl(url) {
    if (url && String(url).startsWith("blob:")) objectUrls.add(url);
    return url;
  }

  function revokeAll() {
    for (const url of objectUrls) {
      try {
        URL.revokeObjectURL(url);
      } catch {
        /* ignore */
      }
    }
    objectUrls.clear();
  }

  function fromResult(resultBody, targetFingerprint) {
    const result = resultBody?.result || {};
    const kind = result.kind || "error";
    const variants = (result.variants || []).map((v, i) => ({
      id: v.id || `v${i}`,
      tempId: v.tempId,
      url: v.url ? absoluteUrl(ctx, v.url) : null,
      mime: v.mime,
      width: v.width,
      height: v.height,
      label: v.label || `Variant ${i + 1}`,
      isMock: !!v.isMock,
      bytes: v.bytes,
    }));
    return {
      requestId: resultBody.requestId,
      kind,
      variants,
      selectedIndex: 0,
      text: result.text || null,
      actions: result.actions || null,
      analysis: result.analysis || null,
      provider: resultBody.provider || {},
      diagnostics: resultBody.diagnostics || {},
      targetFingerprint: targetFingerprint || resultBody.diagnostics?.targetFingerprint || {},
      requestedSize: result.requestedSize || resultBody.diagnostics?.requestedSize || null,
      generatedSize: result.generatedSize || resultBody.diagnostics?.generatedSize || null,
      createdAt: Date.now(),
    };
  }

  function absoluteUrl(c, url) {
    if (!url) return null;
    if (url.startsWith("http")) return url;
    const origin = c.api?.origin || c.apiOrigin || "";
    return `${origin}${url}`;
  }

  function selectedVariant(preview) {
    if (!preview?.variants?.length) return null;
    const idx = Math.max(0, Math.min(preview.selectedIndex || 0, preview.variants.length - 1));
    return preview.variants[idx];
  }

function cssEscape(value) {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") return CSS.escape(value);
  return String(value).replace(/[^a-zA-Z0-9_-]/g, (ch) => `\\${ch}`);
}

  /**
   * Revalidate target before accept. Does not guess a replacement.
   */
  function validateTarget(preview) {
    const fp = preview?.targetFingerprint || {};
    const key = fp.nodeKey;
    if (!key) return { ok: false, reason: "missing-target" };
    const nodeId = key.replace(/^node:/, "");
    const el =
      document.querySelector(`[data-lvb-node="${cssEscape(nodeId)}"]`) ||
      document.querySelector(`[data-lvb-id="${cssEscape(nodeId)}"]`) ||
      document.querySelector(`[data-lvb-node="${cssEscape(key)}"]`);
    if (!el || !el.isConnected) return { ok: false, reason: "target-gone", message: "The selected element was removed while generation was running." };
    const page = ctx.store.getState().page;
    if (fp.pageRoute && page && fp.pageRoute !== page) {
      return { ok: false, reason: "wrong-page", message: "Preview belongs to another page." };
    }
    // Still same identity — OK even if unrelated content changed
    return { ok: true, el, key, nodeId };
  }

  async function accept(preview, aiState) {
    const check = validateTarget(preview);
    if (!check.ok) return { ok: false, ...check };
    if (ctx.commands?.isGesturing?.() || ctx.store.getState().gestureActive) {
      return { ok: false, reason: "gesture-active", message: "Finish or cancel the current gesture before accepting AI changes." };
    }

    const kind = preview.kind;
    if (kind === "text_preview") {
      return acceptText(preview, check);
    }
    if (kind === "action_preview") {
      return acceptActions(preview, check);
    }
    if (kind === "analysis") {
      return { ok: false, reason: "analysis-no-apply", message: "Analysis results are informational only." };
    }
    return acceptAsset(preview, check, aiState);
  }

  async function acceptAsset(preview, check, aiState) {
    const variant = selectedVariant(preview);
    if (!variant?.tempId && !variant?.url) {
      return { ok: false, reason: "no-variant", message: "No variant selected." };
    }
    // Promote temp → permanent upload via API
    let permanentUrl = null;
    if (variant.tempId) {
      const uploaded = await ctx.api.acceptAiAsset({
        tempId: variant.tempId,
        meta: {
          origin: "ai-generated",
          requestId: preview.requestId,
          task: aiState?.task || "generate_image",
          provider: preview.provider?.id,
          model: preview.provider?.model,
          requestedWidth: preview.requestedSize?.width,
          requestedHeight: preview.requestedSize?.height,
          actualWidth: variant.width,
          actualHeight: variant.height,
          sourcePage: preview.targetFingerprint?.pageRoute,
          targetNode: check.key,
          isMock: !!variant.isMock || !!preview.provider?.isMock,
        },
      });
      permanentUrl = uploaded.url;
    } else {
      permanentUrl = variant.url;
    }

    const label = preview.provider?.isMock || variant.isMock ? "AI: Replace image (mock)" : "AI: Replace image";
    const el = check.el;
    const placement = aiState?.placement || "cover";

    ctx.commands.capture(label, () => {
      if (el.tagName === "IMG") {
        el.setAttribute("src", permanentUrl);
        ctx.content.patchEntry(ctx.selection.selectorFor(el), { src: permanentUrl });
        if (placement === "cover" || placement === "fill") ctx.widgets.applyImageFit?.(el, "fill");
        else if (placement === "contain") ctx.widgets.applyImageFit?.(el, "fit");
        else if (placement === "original") ctx.widgets.applyImageFit?.(el, "original");
      } else {
        const value = `url("${permanentUrl}")`;
        ctx.content.applyProp(el, "background-image", value);
        if (placement === "cover" || placement === "fill") {
          ctx.content.applyProp(el, "background-size", "cover");
          ctx.content.applyProp(el, "background-position", "center");
        } else if (placement === "contain") {
          ctx.content.applyProp(el, "background-size", "contain");
          ctx.content.applyProp(el, "background-position", "center");
          ctx.content.applyProp(el, "background-repeat", "no-repeat");
        }
      }
    });

    // Cleanup other temp variants for this request
    try {
      await ctx.api.cleanupAiPreview({ requestId: preview.requestId });
    } catch {
      /* non-fatal */
    }
    revokeAll();
    ctx.content.setStatus(label, "ok");
    return { ok: true, url: permanentUrl, el };
  }

  function acceptText(preview, check) {
    const text = preview.text;
    if (typeof text !== "string") return { ok: false, reason: "no-text" };
    const el = check.el;
    const label = preview.provider?.isMock ? "AI: Rewrite text (mock)" : "AI: Rewrite text";
    ctx.commands.capture(label, () => {
      el.textContent = text;
      ctx.content.patchEntry(ctx.selection.selectorFor(el), { text });
    });
    ctx.content.setStatus(label, "ok");
    return { ok: true, el };
  }

  function acceptActions(preview, check) {
    const actions = preview.actions || [];
    if (!actions.length) return { ok: false, reason: "no-actions" };
    const label = "AI: Apply layout proposal";
    ctx.commands.capture(label, () => {
      for (const action of actions) {
        applyAction(ctx, action, check);
      }
    });
    ctx.content.setStatus(label, "ok");
    return { ok: true };
  }

  async function reject(preview) {
    if (preview?.requestId) {
      try {
        await ctx.api.cleanupAiPreview({ requestId: preview.requestId });
      } catch {
        /* ignore */
      }
    }
    revokeAll();
    return { ok: true };
  }

  return {
    fromResult,
    selectedVariant,
    validateTarget,
    accept,
    reject,
    trackUrl,
    revokeAll,
    AiPhase,
  };
}

function applyAction(ctx, action, check) {
  const targetKey = action.target || check.key;
  const nodeId = String(targetKey || "").replace(/^node:/, "");
  const el =
    document.querySelector(`[data-lvb-node="${cssEscape(nodeId)}"]`) ||
    document.querySelector(`[data-lvb-id="${cssEscape(nodeId)}"]`);
  if (!el) return;
  // Shell protection
  if (el.closest?.(".lv-app") && (action.type === "remove_node" || action.type === "reorder_node")) {
    const shell = el.matches?.(".lv-header, .lv-sidebar, .lv-app") || el.classList?.contains("lv-app");
    if (shell) return;
  }
  if (action.type === "update_style_properties") {
    for (const [prop, value] of Object.entries(action.changes || {})) {
      ctx.content.applyProp(el, prop, value);
    }
  } else if (action.type === "set_text") {
    el.textContent = action.value;
    ctx.content.patchEntry(ctx.selection.selectorFor(el), { text: action.value });
  } else if (action.type === "set_image_source" || action.type === "replace_asset") {
    if (el.tagName === "IMG") {
      el.setAttribute("src", action.value);
      ctx.content.patchEntry(ctx.selection.selectorFor(el), { src: action.value });
    } else {
      ctx.content.applyProp(el, "background-image", `url("${action.value}")`);
    }
  } else if (action.type === "set_attributes") {
    for (const [k, v] of Object.entries(action.attributes || {})) {
      if (k.startsWith("on")) continue;
      el.setAttribute(k, v);
    }
  }
  // insert/remove/reorder intentionally limited until structured node schema apply exists
}
