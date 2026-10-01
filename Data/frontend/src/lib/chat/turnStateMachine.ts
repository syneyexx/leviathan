/**
 * Frontend Chat turn lifecycle — mirrors backend FrontendTurnState.
 * Validates transitions; illegal moves throw InvalidTurnTransition.
 */

export const CHAT_TURN_STATES = [
  "IDLE",
  "PREPARING",
  "RUNNING",
  "STREAMING",
  "CANCELLING",
  "CANCELLED",
  "DEGRADED",
  "COMPLETED",
  "FAILED",
] as const;

export type ChatTurnUiState = (typeof CHAT_TURN_STATES)[number];

export const TERMINAL_CHAT_TURN_STATES: ReadonlySet<ChatTurnUiState> = new Set([
  "CANCELLED",
  "COMPLETED",
  "FAILED",
]);

export const ALLOWED_CHAT_TURN_TRANSITIONS: Readonly<
  Record<ChatTurnUiState, ReadonlySet<ChatTurnUiState>>
> = {
  IDLE: new Set(["PREPARING", "RUNNING"]),
  PREPARING: new Set(["RUNNING", "STREAMING", "FAILED", "CANCELLED", "IDLE"]),
  RUNNING: new Set([
    "STREAMING",
    "CANCELLING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "DEGRADED",
  ]),
  STREAMING: new Set([
    "CANCELLING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "DEGRADED",
  ]),
  CANCELLING: new Set(["CANCELLED", "FAILED", "COMPLETED"]),
  DEGRADED: new Set(["COMPLETED", "FAILED", "CANCELLED", "CANCELLING"]),
  COMPLETED: new Set(["IDLE"]),
  FAILED: new Set(["IDLE"]),
  CANCELLED: new Set(["IDLE"]),
};

export class InvalidTurnTransition extends Error {
  readonly current: ChatTurnUiState;
  readonly target: ChatTurnUiState;

  constructor(current: ChatTurnUiState, target: ChatTurnUiState) {
    super(`Illegal ChatTurn transition: ${current} → ${target}`);
    this.name = "InvalidTurnTransition";
    this.current = current;
    this.target = target;
  }
}

export function isChatTurnUiState(value: unknown): value is ChatTurnUiState {
  return (
    typeof value === "string" &&
    (CHAT_TURN_STATES as readonly string[]).includes(value)
  );
}

export function canTransitionChatTurn(
  current: ChatTurnUiState,
  target: ChatTurnUiState,
): boolean {
  if (current === target) return true;
  return ALLOWED_CHAT_TURN_TRANSITIONS[current]?.has(target) ?? false;
}

export function validateChatTurnTransition(
  current: ChatTurnUiState,
  target: ChatTurnUiState,
): void {
  if (!canTransitionChatTurn(current, target)) {
    throw new InvalidTurnTransition(current, target);
  }
}

/** Apply a transition; returns target. No-op when current === target. */
export function transitionChatTurn(
  current: ChatTurnUiState,
  target: ChatTurnUiState,
): ChatTurnUiState {
  validateChatTurnTransition(current, target);
  return target;
}

/**
 * Soft transition: returns next state when legal, otherwise keeps current
 * (useful for late SSE events after a terminal state).
 */
export function tryTransitionChatTurn(
  current: ChatTurnUiState,
  target: ChatTurnUiState,
): ChatTurnUiState {
  return canTransitionChatTurn(current, target) ? target : current;
}

/** Aliases used by older/sibling tests. */
export const canTransitionTurn = canTransitionChatTurn;
export const transitionTurn = transitionChatTurn;
export const tryTransitionTurn = tryTransitionChatTurn;

export function isTerminalChatTurn(state: ChatTurnUiState): boolean {
  return TERMINAL_CHAT_TURN_STATES.has(state);
}

export function isBusyChatTurn(state: ChatTurnUiState): boolean {
  return (
    state === "PREPARING" ||
    state === "RUNNING" ||
    state === "STREAMING" ||
    state === "CANCELLING" ||
    state === "DEGRADED"
  );
}

export type ChatStreamingBadge =
  | "idle"
  | "streaming"
  | "degraded"
  | "complete"
  | "failed"
  | "cancelled";

/** Map UI state → MessageList streaming badge. CANCELLED ≠ FAILED. */
export function chatTurnToStreamingBadge(state: ChatTurnUiState): ChatStreamingBadge {
  switch (state) {
    case "STREAMING":
    case "RUNNING":
    case "PREPARING":
    case "CANCELLING":
      return "streaming";
    case "DEGRADED":
      return "degraded";
    case "COMPLETED":
      return "complete";
    case "CANCELLED":
      return "cancelled";
    case "FAILED":
      return "failed";
    default:
      return "idle";
  }
}
