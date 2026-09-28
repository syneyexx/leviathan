import { describe, expect, it } from "vitest";
import { mapIngestion } from "../domain/ingestion";

describe("source ingestion progress projection", () => {
  it("preserves measured backend progress as exact", () => {
    const model = mapIngestion({
      counts: { queued: 0, processing: 1, completed: 0, failed: 0 },
      overallProgressPct: 41.5,
      jobs: [{ id: "a", phase: "parsing", state: "RUNNING", progressPct: 40 }],
    });
    expect(model.overallProgressPct).toBe(41.5);
    expect(model.overallProgressEstimated).toBe(false);
    expect(model.jobs[0].progressPct).toBe(40);
    expect(model.jobs[0].progressEstimated).toBe(false);
    expect(model.jobs[0].progressSource).toBe("measured");
  });

  it("shows an explicitly estimated percent for active phase-only jobs", () => {
    const model = mapIngestion({
      counts: { queued: 0, processing: 1, completed: 0, failed: 0 },
      overallProgressPct: null,
      jobs: [{ id: "a", phase: "parsing", state: "RUNNING", progressPct: null }],
    });
    expect(model.jobs[0].progressPct).toBe(58);
    expect(model.jobs[0].progressEstimated).toBe(true);
    expect(model.jobs[0].progressSource).toBe("phase_estimate");
    expect(model.overallProgressPct).toBe(58);
    expect(model.overallProgressEstimated).toBe(true);
  });

  it("does not fabricate progress for failed or unknown states", () => {
    const model = mapIngestion({
      counts: { queued: 0, processing: 0, completed: 0, failed: 1 },
      overallProgressPct: null,
      jobs: [{ id: "a", phase: "partial", state: "FAILED", progressPct: null }],
    });
    expect(model.jobs[0].progressPct).toBeNull();
    expect(model.jobs[0].progressSource).toBe("unmeasured");
    expect(model.overallProgressPct).toBeNull();
  });

  it("reports 100 percent when the bounded read model contains only completed work", () => {
    const model = mapIngestion({
      counts: { queued: 0, processing: 0, completed: 2, failed: 0 },
      overallProgressPct: null,
      jobs: [
        { id: "a", phase: "completed", state: "COMPLETED", progressPct: null },
        { id: "b", phase: "completed", state: "COMPLETED", progressPct: null },
      ],
    });
    expect(model.overallProgressPct).toBe(100);
    expect(model.overallProgressEstimated).toBe(false);
  });
});
