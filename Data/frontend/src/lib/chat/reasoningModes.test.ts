import { describe, expect, it } from "vitest";
import {
  DEFAULT_REASONING_MODE,
  REASONING_MODE_IDS,
  REASONING_MODE_OPTIONS,
  isReasoningModeId,
  parseReasoningMode,
  reasoningModeForApi,
  reasoningModeOption,
} from "./reasoningModes";

describe("reasoningModes", () => {
  it("includes auto, fast, standard, deep", () => {
    expect([...REASONING_MODE_IDS]).toEqual(["auto", "fast", "standard", "deep"]);
    expect(REASONING_MODE_OPTIONS.map((o) => o.id)).toEqual([
      "auto",
      "fast",
      "standard",
      "deep",
    ]);
  });

  it("parses and guards mode ids", () => {
    expect(isReasoningModeId("standard")).toBe(true);
    expect(isReasoningModeId("ultra")).toBe(false);
    expect(parseReasoningMode("deep")).toBe("deep");
    expect(parseReasoningMode("nope")).toBe(DEFAULT_REASONING_MODE);
  });

  it("omits auto on the wire", () => {
    expect(reasoningModeForApi("auto")).toBeNull();
    expect(reasoningModeForApi("standard")).toBe("standard");
    expect(reasoningModeOption("standard").label).toBe("Standaard");
  });
});
