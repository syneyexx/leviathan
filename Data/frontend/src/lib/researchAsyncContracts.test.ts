import { describe, expect, it } from "vitest";
import {
  applyProbeAccept,
  beginPollGeneration,
  canStartPollTick,
  classifyResearchAsync,
  createPollController,
  effectivePollMs,
  idleWebProbeState,
  isPollResultCurrent,
  isQueuedFlag,
  isResearchTerminalStatus,
  markPollFinished,
  markPollStarted,
  normalizePlanResponse,
  normalizeProbeResponse,
  normalizeReportResponse,
  normalizeUrlResponse,
  probeToastMessage,
  shouldRefreshMeasuredReachability,
  shouldSkipPollForVisibility,
  abortPoll,
} from "./researchAsyncContracts";

describe("researchAsyncContracts queued vs completed (R-016)", () => {
  it("classifies probe queued accept separately from completed probe", () => {
    const queued = normalizeProbeResponse({
      queued: true,
      job_id: "job-1",
      probe: { status: "QUEUED", query: "sqlite" },
      status: "QUEUED",
    });
    expect(queued.outcome).toBe("queued");
    expect(queued.queued).toBe(true);
    expect(classifyResearchAsync({ queued: true, status: "QUEUED" })).toBe("queued");

    const done = normalizeProbeResponse({
      probe: { status: "OK", query: "sqlite" },
    });
    expect(done.outcome).toBe("completed");
    expect(isQueuedFlag({ probe: { status: "OK" } })).toBe(false);
  });

  it("classifies plan/url/report queued envelopes", () => {
    expect(
      normalizePlanResponse({
        queued: true,
        status: "QUEUED",
        job_id: "j1",
        project: { project_id: "p1", status: "draft" },
        plan: null,
      }).outcome,
    ).toBe("queued");

    expect(
      normalizeUrlResponse({
        queued: true,
        status: "PENDING",
        source: { source_id: "s1" },
        job_id: "j2",
      }).outcome,
    ).toBe("queued");

    expect(
      normalizeReportResponse({
        queued: true,
        status: "QUEUED",
        project_id: "p1",
        job_id: "j3",
      }).outcome,
    ).toBe("queued");

    expect(
      normalizeReportResponse({
        report: { report_id: "r1", project_id: "p1", version: 1, title: "t", body_markdown: "", evidence_ids: [], source_ids: [], created_at: "" },
      }).outcome,
    ).toBe("completed");
  });
});

describe("probeResearchWeb toast + reachability (R-015)", () => {
  it("does not toast finished for queued accepts", () => {
    expect(
      probeToastMessage("queued", { status: "QUEUED" }),
    ).toBe("Web probe queued");
    expect(probeToastMessage("queued", { status: "ok" })).toBe("Web probe queued");
  });

  it("toasts OK only for completed successful probes", () => {
    expect(probeToastMessage("completed", { status: "OK" })).toBe("Web research probe OK");
    expect(probeToastMessage("completed", { status: "ok" })).toBe("Web research probe OK");
    expect(probeToastMessage("completed", { status: "FAILED", error: "boom" })).toBe("boom");
  });

  it("only marks measured reachability after completed/failed probe, not queue accept", () => {
    const queued = applyProbeAccept(
      idleWebProbeState(),
      normalizeProbeResponse({
        queued: true,
        job_id: "job-9",
        probe: { status: "QUEUED" },
      }),
    );
    expect(queued.phase).toBe("queued");
    expect(queued.measuredReachability).toBe(false);
    expect(shouldRefreshMeasuredReachability(queued.phase)).toBe(false);

    const done = applyProbeAccept(
      queued,
      normalizeProbeResponse({ probe: { status: "OK" } }),
    );
    expect(done.phase).toBe("completed");
    expect(done.measuredReachability).toBe(true);
    expect(shouldRefreshMeasuredReachability(done.phase)).toBe(true);
  });
});

describe("poll race safety (R-014)", () => {
  it("blocks overlapping ticks and drops aborted/out-of-order results", () => {
    const ctrl = createPollController();
    const gen = beginPollGeneration(ctrl);
    expect(canStartPollTick(ctrl, gen)).toBe(true);
    markPollStarted(ctrl);
    expect(canStartPollTick(ctrl, gen)).toBe(false);
    markPollFinished(ctrl);
    expect(canStartPollTick(ctrl, gen)).toBe(true);

    const next = beginPollGeneration(ctrl);
    expect(isPollResultCurrent(ctrl, gen)).toBe(false);
    expect(isPollResultCurrent(ctrl, next)).toBe(true);
    abortPoll(ctrl);
    expect(isPollResultCurrent(ctrl, next)).toBe(false);
  });

  it("pauses when hidden and stops on terminal research status", () => {
    expect(shouldSkipPollForVisibility(false)).toBe(true);
    expect(shouldSkipPollForVisibility(true)).toBe(false);
    expect(effectivePollMs(2500, true)).toBe(2500);
    expect(effectivePollMs(2500, false)).toBe(Number.POSITIVE_INFINITY);
    expect(isResearchTerminalStatus("completed")).toBe(true);
    expect(isResearchTerminalStatus("failed")).toBe(true);
    expect(isResearchTerminalStatus("researching")).toBe(false);
  });
});
