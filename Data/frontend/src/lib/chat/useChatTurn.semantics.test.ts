import { describe, expect, it } from "vitest";
import {
  canTransitionChatTurn,
  chatTurnToStreamingBadge,
  isBusyChatTurn,
  tryTransitionChatTurn,
} from "./turnStateMachine";
import { classifyChatError, chatErrorUserMessage } from "./errorTaxonomy";

describe("turn cancel/busy semantics", () => {
  it("allows streaming → cancelling → cancelled", () => {
    expect(canTransitionChatTurn("STREAMING", "CANCELLING")).toBe(true);
    expect(tryTransitionChatTurn("STREAMING", "CANCELLING")).toBe("CANCELLING");
    expect(tryTransitionChatTurn("CANCELLING", "CANCELLED")).toBe("CANCELLED");
    expect(isBusyChatTurn("CANCELLING")).toBe(true);
    expect(chatTurnToStreamingBadge("CANCELLED")).toBe("cancelled");
  });

  it("ignores late streaming events after terminal", () => {
    expect(tryTransitionChatTurn("COMPLETED", "STREAMING")).toBe("COMPLETED");
    expect(tryTransitionChatTurn("FAILED", "STREAMING")).toBe("FAILED");
  });
});

describe("error taxonomy cancel", () => {
  it("classifies abort as user cancel", () => {
    const err = Object.assign(new Error("The operation was aborted"), { name: "AbortError" });
    const classified = classifyChatError(err);
    expect(classified.code).toBe("CANCELLED");
    expect(classified.userCancel).toBe(true);
    expect(chatErrorUserMessage(classified).length).toBeGreaterThan(0);
  });
});
