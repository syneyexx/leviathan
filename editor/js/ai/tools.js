/**
 * Editor tool layer — shared by AI UI and future MCP adapter.
 * Mutations that change the document go through preview → accept.
 */

import { collectEditorContext, contextSummaryLines } from "./context.js";
import { attachVisualContext, capturePageSnapshot, captureRegionSnapshot, captureSelectionSnapshot } from "./snapshots.js";
import { TASKS, newRequestId } from "./protocol.js";
import { createPreviewController } from "./preview.js";
import { AiPhase, createAiState, isBusy } from "./state.js";

export function createAiTools(ctx) {
  const state = createAiState();
  const previewCtrl = createPreviewController(ctx);
  const listeners = new Set();

  function emit() {
    for (const fn of listeners) {
      try {
        fn(getState());
      } catch {
        /* ignore */
      }
    }
    ctx.store.setState({ uiEpoch: (ctx.store.getState().uiEpoch || 0) + 1 });
  }

  function getState() {
    return { ...state, busy: isBusy(state.phase) };
  }

  function subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  function patch(p) {
    Object.assign(state, p);
    emit();
  }

  async function get_capabilities() {
    try {
      const caps = await ctx.api.getAiCapabilities();
      state.capabilities = caps;
      emit();
      return caps;
    } catch (err) {
      const fallback = {
        available: false,
        reason: String(err.message || err),
        capabilities: {},
      };
      state.capabilities = fallback;
      emit();
      return fallback;
    }
  }

  function get_selection() {
    return {
      keys: ctx.selection?.keys?.() ? [...ctx.selection.keys()] : [],
      primary: ctx.session.primary,
      count: ctx.session.selected?.length || 0,
    };
  }

  function get_selection_bounds() {
    const el = ctx.session.primary;
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.left, y: r.top, width: r.width, height: r.height };
  }

  function get_element(key) {
    const nodeId = String(key || "").replace(/^node:/, "");
    return (
      document.querySelector(`[data-lvb-node="${CSS.escape(nodeId)}"]`) ||
      document.querySelector(`[data-lvb-id="${CSS.escape(nodeId)}"]`)
    );
  }

  function get_page_context() {
    const s = ctx.store.getState();
    return {
      route: s.page,
      mode: s.viewMode,
      breakpoint: s.breakpoint,
      docId: s.content?.docId,
      revision: s.contentRevision,
    };
  }

  function get_design_tokens() {
    return typeof ctx.tokens === "function" ? ctx.tokens() : [];
  }

  function get_asset() {
    const el = ctx.session.primary;
    if (!el) return null;
    if (el.tagName === "IMG") return { kind: "img", url: el.getAttribute("src") };
    try {
      const bg = getComputedStyle(el).backgroundImage;
      const m = String(bg || "").match(/url\(["']?([^"')]+)/);
      if (m) return { kind: "background", url: m[1] };
    } catch {
      /* ignore */
    }
    return null;
  }

  function suggestTaskForSelection() {
    const el = ctx.session.primary;
    if (!el) return "generate_image";
    if (el.tagName === "IMG") return "replace_image";
    const tag = el.tagName;
    if (/^(H[1-6]|P|BUTTON|A|LABEL|SPAN)$/.test(tag) && (el.textContent || "").trim()) return "rewrite_text";
    try {
      const bg = getComputedStyle(el).backgroundImage;
      if (bg && bg !== "none") return "replace_image";
    } catch {
      /* ignore */
    }
    return "generate_image";
  }

  function applicableTasks() {
    const el = ctx.session.primary;
    const keys = ctx.selection?.keys?.() ? [...ctx.selection.keys()] : [];
    if (keys.length > 1) {
      return TASKS.map((t) => ({
        ...t,
        enabled: false,
        reason: "Multi-selection is not supported for AI tasks yet — select a single target.",
      }));
    }
    const caps = state.capabilities?.capabilities || {};
    let kind = "any";
    if (el?.tagName === "IMG") kind = "image";
    else if (el && /^(H[1-6]|P|BUTTON|A|LABEL|SPAN)$/.test(el.tagName)) kind = "text";
    else if (el) {
      try {
        const bg = getComputedStyle(el).backgroundImage;
        if (bg && bg !== "none") kind = "visual";
        else kind = "container";
      } catch {
        kind = "container";
      }
    }
    return TASKS.map((t) => {
      const kindOk = t.kinds.includes(kind) || t.kinds.includes("any");
      const cap = caps[t.capability];
      const capOk = !state.capabilities || cap?.available;
      let reason = null;
      if (!el && t.id !== "analyze_style") reason = "Select an element first";
      else if (!kindOk) reason = `Not applicable to ${kind} selection`;
      else if (state.capabilities && !capOk) reason = cap?.reason || "Capability unavailable";
      return { ...t, enabled: kindOk && (!state.capabilities || capOk) && !!el, reason };
    });
  }

  async function buildContext({ withSnapshots = true } = {}) {
    patch({ phase: AiPhase.CAPTURING_CONTEXT, error: null });
    const width = state.useSelectionDimensions ? state.width : state.width;
    const height = state.useSelectionDimensions ? state.height : state.height;
    const { context, kind, identityKey, bounds, role } = collectEditorContext(ctx, {
      task: state.task,
      instruction: state.instruction,
      styleSource: state.styleSource,
      customStyle: state.customStyle,
      placement: state.placement,
      variants: state.variants,
      width,
      height,
      includeTokens: state.contextOpts.themeTokens,
      includeNearby: state.contextOpts.nearby,
      includeExistingImage: state.contextOpts.existingImage,
      requestId: state.requestId,
    });

    state.target = {
      key: identityKey,
      pageId: context.page.id,
      pageRoute: context.page.route,
      bounds,
      tag: context.selection.tag,
      role,
      kind,
      assetUrl: context.asset?.current?.url || null,
      generation: ctx.session.uiEpoch ?? 0,
    };

    if (withSnapshots) {
      patch({ phase: AiPhase.CAPTURING_SNAPSHOT });
      await attachVisualContext(ctx, context, {
        pageVisual: state.contextOpts.pageVisual && ["current_page", "page_and_selection"].includes(state.styleSource),
        selectionVisual:
          state.contextOpts.selectionVisual &&
          ["selected_element", "page_and_selection", "custom"].includes(state.styleSource),
        regionVisual: false,
        primary: ctx.session.primary,
      });
    }

    state.contextSummary = contextSummaryLines(context);
    state.requestId = context.request.id;
    emit();
    return context;
  }

  async function generate_asset() {
    if (isBusy(state.phase)) {
      return { ok: false, reason: "busy" };
    }
    if (!state.instruction.trim()) {
      patch({ phase: AiPhase.ERROR, error: { message: "Enter an instruction / prompt." } });
      return { ok: false, reason: "no-instruction" };
    }
    if (!ctx.session.primary) {
      patch({ phase: AiPhase.ERROR, error: { message: "Select a target element first." } });
      return { ok: false, reason: "no-selection" };
    }

    // Always new request id for generate/regenerate
    state.requestId = newRequestId();

    try {
      const context = await buildContext({ withSnapshots: true });
      patch({ phase: AiPhase.SUBMITTING, preview: null, error: null });
      patch({ phase: AiPhase.GENERATING });
      const body = await ctx.api.editorAi({
        context,
        requestId: context.request.id,
        task: context.request.task,
        instruction: context.request.instruction,
      });
      if (state.requestId && body.requestId && body.requestId !== state.requestId) {
        // Stale — ignore
        return { ok: false, reason: "stale" };
      }
      if (body.status === "error" || body.error) {
        const err = body.error || {};
        patch({
          phase: AiPhase.ERROR,
          error: {
            code: err.code,
            message: err.message || body.error || "Generation failed",
            details: err.details,
            diagnostics: body.diagnostics,
          },
          lastDurationMs: body.diagnostics?.durationMs,
        });
        return { ok: false, error: state.error };
      }
      const preview = previewCtrl.fromResult(body, context.targetFingerprint);
      patch({
        phase: AiPhase.PREVIEW_READY,
        preview,
        lastDurationMs: body.diagnostics?.durationMs,
        error: null,
      });
      return { ok: true, preview };
    } catch (err) {
      const payload = err.payload || {};
      const message =
        payload?.error?.message ||
        payload?.notes ||
        payload?.reason ||
        err.message ||
        "Generation failed";
      const code = payload?.error?.code || payload?.reason || (err.status === 501 ? "no-provider" : "error");
      patch({
        phase: AiPhase.ERROR,
        error: {
          code,
          message: formatError(code, message, payload),
          diagnostics: payload.diagnostics,
          unavailable: payload.unavailable || err.status === 501,
        },
      });
      return { ok: false, error: state.error };
    }
  }

  function formatError(code, message, payload) {
    if (code === "no-provider" || payload?.unavailable) {
      return (
        message ||
        "Image generation is unavailable because no image provider is configured. Enable LEVIATHAN_EDITOR_AI_MOCK=1 for deterministic previews, or configure LEVIATHAN_EDITOR_AI_IMAGE_ENDPOINT."
      );
    }
    if (code === "provider_timeout") return message || "Provider timed out.";
    if (code === "target-gone") return message;
    return message;
  }

  async function cancel() {
    const id = state.requestId;
    if (id) {
      try {
        await ctx.api.cancelAiRequest(id);
      } catch {
        /* abandon client-side */
      }
    }
    patch({ phase: AiPhase.CANCELLED, error: { message: "Cancelled — in-flight result will be ignored." } });
    return { ok: true };
  }

  async function reject_preview() {
    await previewCtrl.reject(state.preview);
    patch({ phase: AiPhase.IDLE, preview: null, error: null });
    return { ok: true };
  }

  async function accept_preview() {
    if (!state.preview) return { ok: false, reason: "no-preview" };
    patch({ phase: AiPhase.APPLYING });
    try {
      const result = await previewCtrl.accept(state.preview, state);
      if (!result.ok) {
        patch({
          phase: AiPhase.ERROR,
          error: { code: result.reason, message: result.message || result.reason },
        });
        return result;
      }
      patch({ phase: AiPhase.IDLE, preview: null, error: null });
      return result;
    } catch (err) {
      patch({ phase: AiPhase.ERROR, error: { message: String(err.message || err) } });
      return { ok: false, error: state.error };
    }
  }

  function select_variant(index) {
    if (!state.preview) return;
    state.preview = { ...state.preview, selectedIndex: index };
    emit();
  }

  function syncDimensionsFromSelection() {
    const el = ctx.session.primary;
    if (!el) {
      if (state.width != null || state.height != null) {
        state.width = null;
        state.height = null;
        emit();
      }
      return;
    }
    const r = el.getBoundingClientRect();
    const w = Math.round(r.width);
    const h = Math.round(r.height);
    const task = suggestTaskForSelection();
    let changed = false;
    if (state.width !== w || state.height !== h) {
      state.width = w;
      state.height = h;
      changed = true;
    }
    if (!state.preview && !(state.instruction || "").trim() && state.task !== task) {
      state.task = task;
      changed = true;
    }
    if (changed) emit();
  }

  // Public tool surface (MCP-ready names)
  return {
    getState,
    subscribe,
    patch,
    syncDimensionsFromSelection,
    applicableTasks,
    suggestTaskForSelection,
    // READ
    get_selection,
    get_selection_bounds,
    get_element,
    get_page_context,
    get_design_tokens,
    get_asset,
    get_capabilities,
    // VISUAL
    capture_page_snapshot: () => capturePageSnapshot(ctx),
    capture_selection_snapshot: () => captureSelectionSnapshot(ctx.session.primary),
    capture_region_snapshot: (opts) => captureRegionSnapshot(ctx.session.primary, opts),
    // ASSET / CONTENT
    generate_asset,
    preview_asset: () => state.preview,
    discard_asset_preview: reject_preview,
    // TRANSACTIONAL
    accept_preview,
    reject_preview,
    select_variant,
    cancel,
    regenerate: generate_asset,
    undo: () => ctx.commands.undo(),
    redo: () => ctx.commands.redo(),
    buildContext,
    previewCtrl,
    AiPhase,
  };
}
