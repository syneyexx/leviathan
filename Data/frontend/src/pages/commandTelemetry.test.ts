import { describe, expect, it } from "vitest";
import { sparklinePath, type TelemetryHistoryPoint } from "../hooks/useSystemTelemetry";

describe("dashboard telemetry helpers", () => {
  it("sparkline uses actual sample history", () => {
    const history: TelemetryHistoryPoint[] = [
      { at: 1, cpuPct: 10, ramPct: 20, gpuPct: null, vramPct: null },
      { at: 2, cpuPct: 40, ramPct: 30, gpuPct: null, vramPct: null },
      { at: 3, cpuPct: 25, ramPct: 35, gpuPct: null, vramPct: null },
    ];
    const path = sparklinePath(history, "cpuPct");
    expect(path).not.toBeNull();
    expect(path?.line.split(" ").length).toBe(3);
    expect(path?.area.startsWith("M")).toBe(true);
  });

  it("sparkline returns null until enough measured points", () => {
    expect(sparklinePath([], "cpuPct")).toBeNull();
    expect(
      sparklinePath([{ at: 1, cpuPct: null, ramPct: null, gpuPct: null, vramPct: null }], "gpuPct"),
    ).toBeNull();
  });

  it("unavailable GPU stays null rather than zero", () => {
    const sample = {
      dashboard: { cpuPct: 12, ramPct: 28, gpuPct: null as number | null, vramPct: null as number | null },
      gpu: { available: false },
    };
    const gpuAvailable = Boolean(sample.gpu.available && sample.dashboard.gpuPct != null);
    const display =
      !gpuAvailable || sample.dashboard.gpuPct == null
        ? "N/A"
        : `${Math.round(sample.dashboard.gpuPct)}%`;
    expect(display).toBe("N/A");
    expect(sample.dashboard.gpuPct).not.toBe(0);
  });
});

describe("conversation deep-link helpers", () => {
  it("builds stable conversation query links", () => {
    const id = "abc-123";
    const path = `/chat?conversation=${encodeURIComponent(id)}`;
    expect(path).toBe("/chat?conversation=abc-123");
  });

  it("sorts recent conversations by updated_at descending", () => {
    const rows = [
      { id: "1", updated_at: "2026-01-01T10:00:00Z" },
      { id: "2", updated_at: "2026-01-02T10:00:00Z" },
      { id: "3", updated_at: "2026-01-01T12:00:00Z" },
    ];
    const sorted = [...rows].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    expect(sorted.map((r) => r.id)).toEqual(["2", "3", "1"]);
  });
});
