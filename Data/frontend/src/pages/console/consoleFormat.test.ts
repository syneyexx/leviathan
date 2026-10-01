import { describe, expect, it } from "vitest";
import {
  compileSafeRegex,
  eventMatchesQuickFilter,
  formatCompactCount,
  normalizeSeverity,
  serviceStatusTone,
} from "./consoleFormat";
import type { RuntimeEvent } from "../../types/api";

function evt(partial: Partial<RuntimeEvent>): RuntimeEvent {
  return {
    sequence: 1,
    event_id: "e1",
    created_at_ms: Date.now(),
    level: "INFO",
    category: "http",
    subsystem: "api",
    name: "req",
    message: "ok",
    payload: {},
    source: "test",
    ...partial,
  };
}

describe("consoleFormat", () => {
  it("normalizes severity aliases", () => {
    expect(normalizeSeverity("warn")).toBe("warning");
    expect(normalizeSeverity("ok")).toBe("other");
    expect(normalizeSeverity("SUCCESS")).toBe("success");
    expect(normalizeSeverity("CRITICAL")).toBe("error");
  });

  it("rejects pathological regex safely", () => {
    expect(compileSafeRegex("(a+)+").error).toBeTruthy();
    expect(compileSafeRegex("ERROR|WARNING").re).toBeInstanceOf(RegExp);
    expect(compileSafeRegex("(").error).toBeTruthy();
  });

  it("maps quick filters without inventing matches", () => {
    expect(eventMatchesQuickFilter(evt({ level: "ERROR" }), "errors")).toBe(true);
    expect(eventMatchesQuickFilter(evt({ category: "mcp" }), "mcp")).toBe(true);
    expect(eventMatchesQuickFilter(evt({ category: "http" }), "workflows")).toBe(false);
  });

  it("never treats unmeasured as success tone", () => {
    expect(serviceStatusTone("operational", false)).toBe("muted");
    expect(serviceStatusTone("operational", true)).toBe("success");
    expect(serviceStatusTone("unmeasured", true)).toBe("muted");
  });

  it("formats compact counts without fabricating", () => {
    expect(formatCompactCount(null)).toBe("—");
    expect(formatCompactCount(1482339)).toMatch(/M/);
  });
});
