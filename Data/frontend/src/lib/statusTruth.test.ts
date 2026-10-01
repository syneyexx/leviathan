import { describe, expect, it } from "vitest";
import {
  classifyRawStatus,
  classifyStatusToken,
  mapMeasuredComponentStatus,
  normalizeStatusToken,
} from "./statusTruth";

describe("statusTruth exact-token classification", () => {
  it("normalizes casing, spaces, and hyphens to exact tokens", () => {
    expect(normalizeStatusToken("NOT READY")).toBe("not_ready");
    expect(normalizeStatusToken("Not-Ok")).toBe("not_ok");
    expect(normalizeStatusToken("  Running ")).toBe("running");
  });

  it("treats ready/running/ok/healthy as success only as exact tokens", () => {
    expect(classifyStatusToken("ready").kind).toBe("success");
    expect(classifyStatusToken("running").value).toBe("Running");
    expect(classifyStatusToken("ok").kind).toBe("success");
    expect(classifyStatusToken("healthy").kind).toBe("success");
  });

  it("does not treat adversarial NOT_/UN* tokens as success", () => {
    for (const raw of ["NOT_READY", "UNHEALTHY", "NOT_OK", "NOT_RUNNING", "UNREADY"]) {
      const classified = classifyRawStatus(raw);
      expect(classified.kind).not.toBe("success");
      expect(classified.tone).not.toBe("success");
      expect(classified.value).not.toMatch(/Ready|Running|Goed|HEALTHY/i);
    }
  });

  it("maps unknown tokens to UNKNOWN", () => {
    expect(classifyRawStatus("weird-state")).toEqual({
      token: "weird_state",
      value: "UNKNOWN",
      tone: "muted",
      kind: "unknown",
    });
    expect(classifyRawStatus("")).toEqual({
      token: "unknown",
      value: "UNKNOWN",
      tone: "muted",
      kind: "unknown",
    });
    expect(classifyRawStatus(null).value).toBe("UNKNOWN");
  });

  it("honors measured=false as UNMEASURED before status text", () => {
    expect(mapMeasuredComponentStatus("ready", false)).toEqual({
      value: "UNMEASURED",
      tone: "muted",
    });
    expect(mapMeasuredComponentStatus("NOT_READY", true)).toEqual({
      value: "Offline",
      tone: "danger",
    });
    expect(mapMeasuredComponentStatus("ready", true)).toEqual({
      value: "Ready",
      tone: "success",
    });
  });
});
