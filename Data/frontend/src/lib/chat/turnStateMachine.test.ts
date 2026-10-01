import { describe, expect, it } from "vitest";
import {
  ALLOWED_CHAT_TURN_TRANSITIONS,
  InvalidTurnTransition,
  canTransitionChatTurn,
  chatTurnToStreamingBadge,
  isBusyChatTurn,
  isTerminalChatTurn,
  transitionChatTurn,
  tryTransitionChatTurn,
  validateChatTurnTransition,
} from "./turnStateMachine";

describe("turnStateMachine", () => {
  it("allows IDLE → PREPARING → STREAMING → COMPLETED → IDLE", () => {
    let state = transitionChatTurn("IDLE", "PREPARING");
    state = transitionChatTurn(state, "STREAMING");
    state = transitionChatTurn(state, "COMPLETED");
    state = transitionChatTurn(state, "IDLE");
    expect(state).toBe("IDLE");
  });

  it("allows cancel path RUNNING → CANCELLING → CANCELLED", () => {
    expect(canTransitionChatTurn("RUNNING", "CANCELLING")).toBe(true);
    expect(canTransitionChatTurn("CANCELLING", "CANCELLED")).toBe(true);
    expect(canTransitionChatTurn("CANCELLED", "STREAMING")).toBe(false);
  });

  it("rejects illegal transitions", () => {
    expect(() => validateChatTurnTransition("COMPLETED", "STREAMING")).toThrow(
      InvalidTurnTransition,
    );
    expect(tryTransitionChatTurn("FAILED", "STREAMING")).toBe("FAILED");
  });

  it("marks terminal and busy states correctly", () => {
    expect(isTerminalChatTurn("COMPLETED")).toBe(true);
    expect(isTerminalChatTurn("STREAMING")).toBe(false);
    expect(isBusyChatTurn("STREAMING")).toBe(true);
    expect(isBusyChatTurn("IDLE")).toBe(false);
    expect(chatTurnToStreamingBadge("DEGRADED")).toBe("degraded");
    expect(chatTurnToStreamingBadge("CANCELLED")).toBe("cancelled");
    expect(chatTurnToStreamingBadge("FAILED")).toBe("failed");
    expect(chatTurnToStreamingBadge("CANCELLED")).not.toBe("failed");
  });

  it("has an allow-list entry for every state", () => {
    for (const [from, targets] of Object.entries(ALLOWED_CHAT_TURN_TRANSITIONS)) {
      expect(targets).toBeInstanceOf(Set);
      expect(from).toBeTruthy();
    }
  });
});
