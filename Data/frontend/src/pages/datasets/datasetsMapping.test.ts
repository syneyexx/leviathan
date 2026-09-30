import { describe, expect, it } from "vitest";
import { mapStatus, measuredProgressPct, statusLabel } from "./datasetsMapping";
import type { DatasetJob } from "../../types/api";

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
});
