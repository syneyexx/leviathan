import { describe, expect, it } from "vitest";
import {
  failedImportDetail,
  mapStatus,
  measuredProgressPct,
  statusLabel,
} from "./datasetsMapping";
import type { DatasetJob, DatasetRecord } from "../../types/api";

describe("datasetsMapping status truth", () => {
  it("does not map unknown backend status to Ready", () => {
    expect(mapStatus("weird-new-state")).toBe("unknown");
    expect(statusLabel(mapStatus("weird-new-state"))).toBe("UNKNOWN");
    expect(mapStatus("ready")).toBe("ready");
    expect(mapStatus("")).toBe("unknown");
  });

  it("measuredProgressPct never invents a percentage", () => {
    const job = { progress: null } as DatasetJob;
    expect(measuredProgressPct(job)).toBeNull();
    expect(measuredProgressPct({ progress: 0.42 } as DatasetJob)).toBe(42);
  });

  it("failedImportDetail prefers validation over Ready · 100%", () => {
    const ds = {
      quality: {
        measured: true,
        score: 0,
        label: "Kritiek",
        segments: [false, false, false, false, false],
        tone: "critical",
        constituents: { errorCount: 1003 },
      },
    } as DatasetRecord;
    const job = {
      phase: "done",
      progress: 1,
      status: "completed",
      result: { materialized: { validation: { valid: false, errorCount: 1003 } } },
    } as DatasetJob;
    expect(failedImportDetail(ds, job)).toContain("Validatie mislukt");
    expect(failedImportDetail(ds, job)).not.toMatch(/^Ready/);
  });
});
