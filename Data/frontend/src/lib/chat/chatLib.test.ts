import { describe, expect, it } from "vitest";
import { formatParameterCount } from "./formatModelParams";
import {
  canTransitionChatTurn,
  transitionChatTurn,
  tryTransitionChatTurn,
} from "./turnStateMachine";
import { isSafeHref } from "./safeMarkdown";
import { classifyChatError } from "./errorTaxonomy";
import {
  isReasoningModeId,
  parseReasoningMode,
  reasoningModeForApi,
  DEFAULT_REASONING_MODE,
} from "./reasoningModes";

describe("formatParameterCount", () => {
  it("formats B/M/K thresholds", () => {
    expect(formatParameterCount(1_500_000_000)).toBe("1.5B");
    expect(formatParameterCount(2_000_000)).toBe("2M");
    expect(formatParameterCount(4_200)).toBe("4.2K");
    expect(formatParameterCount(42)).toBe("42");
    expect(formatParameterCount(null)).toBe("UNMEASURED");
  });
});

describe("turnStateMachine", () => {
  it("allows legal transitions and rejects illegal", () => {
    expect(canTransitionChatTurn("IDLE", "PREPARING")).toBe(true);
    expect(canTransitionChatTurn("COMPLETED", "STREAMING")).toBe(false);
    expect(transitionChatTurn("RUNNING", "STREAMING")).toBe("STREAMING");
    expect(() => transitionChatTurn("CANCELLED", "COMPLETED")).toThrow();
    expect(tryTransitionChatTurn("COMPLETED", "STREAMING")).toBe("COMPLETED");
  });
});

describe("isSafeHref", () => {
  it("blocks dangerous schemes", () => {
    expect(isSafeHref("javascript:alert(1)")).toBe(false);
    expect(isSafeHref("data:text/html,x")).toBe(false);
    expect(isSafeHref("https://example.com")).toBe(true);
    expect(isSafeHref("/local")).toBe(true);
  });
});

describe("classifyChatError", () => {
  it("does not call validation a LLM reachability error", () => {
    const err = classifyChatError({ message: "Message cannot be empty", status: 422 });
    expect(err.code).toBe("VALIDATION_ERROR");
    expect(err.message).not.toMatch(/Could not reach LLM/i);
  });

  it("marks abort as cancelled", () => {
    expect(classifyChatError({ name: "AbortError" }).code).toBe("CANCELLED");
  });
});

describe("reasoningModes", () => {
  it("keeps auto as null request override", () => {
    expect(isReasoningModeId("standard")).toBe(true);
    expect(parseReasoningMode("deep")).toBe("deep");
    expect(parseReasoningMode("nope")).toBe(DEFAULT_REASONING_MODE);
    expect(reasoningModeForApi("auto")).toBeNull();
    expect(reasoningModeForApi("deep")).toBe("deep");
  });
});
