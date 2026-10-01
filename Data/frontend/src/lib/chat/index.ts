export { REASONING_MODE_IDS, REASONING_MODE_OPTIONS, DEFAULT_REASONING_MODE } from "./reasoningModes";
export type { ReasoningModeId, ReasoningModeOption } from "./reasoningModes";
export {
  isReasoningModeId,
  parseReasoningMode,
  reasoningModeOption,
  reasoningModeForApi,
} from "./reasoningModes";

export { CHAT_PROMPT_PRESETS } from "./promptPresets";
export type { ChatPromptPreset } from "./promptPresets";

export {
  CHAT_TURN_STATES,
  TERMINAL_CHAT_TURN_STATES,
  ALLOWED_CHAT_TURN_TRANSITIONS,
  InvalidTurnTransition,
  isChatTurnUiState,
  canTransitionChatTurn,
  validateChatTurnTransition,
  transitionChatTurn,
  tryTransitionChatTurn,
  isTerminalChatTurn,
  isBusyChatTurn,
  chatTurnToStreamingBadge,
} from "./turnStateMachine";
export type { ChatTurnUiState, ChatStreamingBadge } from "./turnStateMachine";

export { formatModelParams, formatParamCount, formatParameterCount } from "./formatModelParams";

export {
  CHAT_ERROR_CODES,
  classifyChatError,
  chatErrorUserMessage,
} from "./errorTaxonomy";
export type { ChatErrorCode, ChatErrorClassification } from "./errorTaxonomy";

export {
  createGenerationGate,
  beginGeneration,
  isCurrentGeneration,
  mayCommit,
  abortGeneration,
  debounceMs,
} from "./raceSafety";
export type { GenerationGate } from "./raceSafety";

export {
  SafeMarkdown,
  parseSafeMarkdown,
  renderInlineMarkdown,
  isSafeHref,
  sanitizeHref,
} from "./safeMarkdown";
export type { MdBlock, SafeMarkdownProps } from "./safeMarkdown";

export {
  canAttachFiles,
  validateLocalFile,
  uploadChatAttachment,
  readyArtifactIds,
  visionClaimAllowed,
} from "./attachments";
export type { ChatAttachment, ChatAttachmentState } from "./attachments";

export {
  resolveTurnForMessage,
  resolveHistoricToolCalls,
  resolveHistoricActivity,
} from "./historicTurn";
