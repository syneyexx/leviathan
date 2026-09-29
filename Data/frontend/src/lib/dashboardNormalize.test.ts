import { describe, expect, it } from "vitest";
import {
  clampPct,
  domainBadgeTone,
  formatBytes,
  formatDuration,
  formatDutchDateTime,
  formatPct,
  normalizeLmStudioStatus,
  normalizeSystemStatus,
  researchStatusTone,
  toMeasuredValue,
} from "./dashboardNormalize";

describe("formatPct", () => {
  it("returns N/A for unknown / unavailable telemetry (never 0%)", () => {
    expect(formatPct(null)).toBe("N/A");
    expect(formatPct(undefined)).toBe("N/A");
    expect(formatPct(NaN)).toBe("N/A");
    expect(formatPct(0, false)).toBe("N/A");
    expect(formatPct(42, false)).toBe("N/A");
  });

  it("keeps measured zero as 0%", () => {
    expect(formatPct(0)).toBe("0%");
    expect(formatPct(0, true)).toBe("0%");
  });

  it("rounds measured percentages", () => {
    expect(formatPct(42.4)).toBe("42%");
    expect(formatPct(99.6)).toBe("100%");
  });
});

describe("clampPct", () => {
  it("clamps and nulls unknowns", () => {
    expect(clampPct(null)).toBeNull();
    expect(clampPct(-5)).toBe(0);
    expect(clampPct(150)).toBe(100);
    expect(clampPct(33.3)).toBe(33.3);
  });
});

describe("formatBytes", () => {
  it("returns em dash for missing values", () => {
    expect(formatBytes(null)).toBe("—");
    expect(formatBytes(undefined)).toBe("—");
    expect(formatBytes(Number.NaN)).toBe("—");
  });

  it("formats measured byte sizes", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1024)).toBe("1 KB");
    expect(formatBytes(6 * 1024 ** 3 + 0.2 * 1024 ** 3)).toMatch(/^6\.2 GB$/);
    expect(formatBytes(1536)).toBe("1.5 KB");
  });
});

describe("formatDuration", () => {
  it("returns UNMEASURED when missing", () => {
    expect(formatDuration(null)).toBe("UNMEASURED");
    expect(formatDuration(undefined)).toBe("UNMEASURED");
  });

  it("formats minutes and seconds", () => {
    expect(formatDuration(134)).toBe("2m 14s");
    expect(formatDuration(0)).toBe("0s");
  });
});

describe("formatDutchDateTime", () => {
  it("formats Dutch short weekday and month", () => {
    // Sunday 25 May 2025 14:37:26 local
    const d = new Date(2025, 4, 25, 14, 37, 26);
    const { dateLine, timeLine } = formatDutchDateTime(d);
    expect(dateLine).toBe("Zo 25 Mei 2025");
    expect(timeLine).toBe("14:37:26");
  });
});

describe("normalizeSystemStatus", () => {
  it("is Operationeel only when health.ok and not errored", () => {
    expect(normalizeSystemStatus({ ok: true }, null)).toEqual({
      label: "Operationeel",
      tone: "success",
      operational: true,
    });
    expect(normalizeSystemStatus({ ok: true }, "boom").operational).toBe(false);
    expect(normalizeSystemStatus({ ok: false }, null).label).toBe("Degraded");
    expect(normalizeSystemStatus(null, true).label).toBe("Offline");
    expect(normalizeSystemStatus(null, null).label).toBe("Onbekend");
  });
});

describe("normalizeLmStudioStatus", () => {
  it("prefers health.llm.available without inventing hardware names", () => {
    expect(normalizeLmStudioStatus({ ok: true, llm: { available: true, model: "qwen" } })).toEqual({
      label: "LM Studio",
      value: "Running · qwen",
      tone: "success",
    });
    expect(normalizeLmStudioStatus({ ok: true, llm: { available: false, model: null } }).value).toBe(
      "Offline",
    );
    expect(normalizeLmStudioStatus(null).value).toBe("UNKNOWN");
  });
});

describe("domainBadgeTone / researchStatusTone", () => {
  it("maps domains and research statuses to badge tones", () => {
    expect(domainBadgeTone("research")).toBe("research");
    expect(domainBadgeTone("trading")).toBe("trading");
    expect(domainBadgeTone(null)).toBe("muted");
    expect(researchStatusTone("RUNNING")).toBe("info");
    expect(researchStatusTone("COMPLETED")).toBe("success");
    expect(researchStatusTone("FAILED")).toBe("danger");
  });
});

describe("toMeasuredValue", () => {
  it("distinguishes measured zero from unmeasured", () => {
    expect(toMeasuredValue(0)).toEqual({ kind: "measured", value: 0 });
    expect(toMeasuredValue(null)).toEqual({ kind: "unmeasured" });
    expect(toMeasuredValue(0, false)).toEqual({ kind: "unavailable" });
  });
});
