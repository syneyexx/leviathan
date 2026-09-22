/**
 * AI interaction state machine — avoids impossible boolean combinations.
 */

export const AiPhase = {
  IDLE: "idle",
  CAPTURING_CONTEXT: "capturing-context",
  CAPTURING_SNAPSHOT: "capturing-snapshot",
  SUBMITTING: "submitting",
  GENERATING: "generating",
  PREVIEW_READY: "preview-ready",
  APPLYING: "applying",
  ERROR: "error",
  CANCELLED: "cancelled",
};

export function createAiState() {
  return {
    phase: AiPhase.IDLE,
    requestId: null,
    task: "generate_image",
    instruction: "",
    styleSource: "page_and_selection",
    customStyle: "",
    placement: "cover",
    variants: 1,
    useSelectionDimensions: true,
    width: null,
    height: null,
    aspectLocked: true,
    contextOpts: {
      pageVisual: true,
      selectionVisual: true,
      themeTokens: true,
      nearby: true,
      existingImage: true,
    },
    target: null, // { key, pageId, bounds, tag, role, assetUrl, generation }
    contextSummary: null,
    preview: null, // { requestId, variants, selectedIndex, provider, diagnostics, kind, text, actions }
    error: null,
    capabilities: null,
    lastDurationMs: null,
  };
}

export function isBusy(phase) {
  return [
    AiPhase.CAPTURING_CONTEXT,
    AiPhase.CAPTURING_SNAPSHOT,
    AiPhase.SUBMITTING,
    AiPhase.GENERATING,
    AiPhase.APPLYING,
  ].includes(phase);
}
