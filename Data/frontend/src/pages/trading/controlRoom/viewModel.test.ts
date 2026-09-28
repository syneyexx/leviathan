import { createElement } from "react";
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ControlRoomView } from "./ControlRoomView";
import {
  ADD_NOTE_REASON,
  buildControlRoomModel,
  modelHasFakeGreen,
  UNMEASURED,
  VIEW_PIPELINE_REASON,
} from "./viewModel";

const measured = {
  generatedAt: "2026-03-01T14:05:00+00:00",
  overallStatus: "FAIL",
  liveTrading: {
    ok: true,
    status: "PASS",
    LIVE_TRADING_AVAILABLE: "BLOCKED",
    publicStatus: {
      LIVE_TRADING_AVAILABLE: "BLOCKED",
      unlock_env_set: false,
      adapter_configured: false,
      human_authorization_required: true,
      agent_cannot_enable: true,
      detail: "Live broker orders are intentionally blocked.",
    },
  },
  gaps: {
    openGapCount: 4,
    count: 10,
    byStatus: { OBSERVED: 3, BLOCKED: 1, NOT_IMPLEMENTED: 4, ASSUMED: 2 },
    byImplementation: { PRESENT: 3, PARTIAL: 2, NOT_IMPLEMENTED: 5 },
  },
  multiAsset: {
    featureEnabled: true,
    families: [
      { family: "equity", HISTORICAL_SIM_AVAILABLE: "AVAILABLE", LIVE_TRADING_AVAILABLE: "BLOCKED", notes: "" },
      { family: "crypto_spot", HISTORICAL_SIM_AVAILABLE: "AVAILABLE", LIVE_TRADING_AVAILABLE: "BLOCKED" },
    ],
  },
  health: { overall: "FAIL", notes: ["audit chain failed"] },
  reconciliation: {
    status: "FAIL",
    openCount: 1,
    breaks: [
      {
        breakId: "brk-1",
        domain: "demo",
        field: "value",
        status: "OPEN",
        explanation: "left 1 vs right 2",
        createdAt: "2026-03-01T13:00:00+00:00",
        updatedAt: "2026-03-01T13:10:00+00:00",
        leftSystem: "a",
        rightSystem: "b",
      },
    ],
    recentRuns: [{ runId: "recon-1", status: "FAIL", openCount: 1, domain: "demo", createdAt: "2026-03-01T13:00:00+00:00" }],
  },
  exceptions: {
    status: "FAIL",
    openCount: 1,
    items: [
      {
        exceptionId: "ex-1",
        kind: "reconciliation.break",
        severity: "MEDIUM",
        status: "OPEN",
        owner: "operations",
        lastSeen: "2026-03-01T13:11:00+00:00",
      },
    ],
  },
  audit: {
    status: "FAIL",
    ok: false,
    count: 2,
    brokenAt: "evt-2",
    lastTs: "2026-03-01T13:12:00+00:00",
    recentEvents: [{ eventId: "evt-2", kind: "reconciliation.completed", actor: "runtime", detail: "demo status=FAIL", ts: "2026-03-01T13:12:00+00:00" }],
  },
  api: {
    contracts: [
      { path: "/api/market-sim/institutional/control-room", method: "GET", owner: "control_room", status: "OBSERVED" },
      { path: "/api/market-sim/live/order", method: "POST", owner: "guard", status: "BLOCKED" },
    ],
    truth: { catalog_is_not_runtime_proof: true },
  },
  events: {
    contracts: [{ eventType: "audit_chained", owner: "audit", status: "OBSERVED" }],
  },
  notes: ["operator saw the break"],
  research: {
    status: "OBSERVED",
    activeCampaigns: 1,
    hypothesesCount: 2,
    trialCount: 5,
    qualificationRunsCount: 1,
    rejectionReasons: ["LOW_SAMPLE"],
    campaignSample: [{ campaignId: "camp-1", status: "RUNNING", hypothesisId: "hyp-1" }],
    qualificationRuns: [
      {
        qualificationId: "q-1",
        status: "RUNNING",
        decision: null,
        currentGate: "Q04_WALK_FORWARD",
        strategyId: "s-1",
        blockers: ["LOW_SAMPLE"],
        updatedAt: "2026-03-01T12:00:00+00:00",
      },
    ],
    sealedAttempts: [],
  },
  dataPlane: {
    status: "OBSERVED",
    certificationCount: 1,
    pitStates: ["PASS"],
    survivorshipStates: ["PASS"],
    certificationStates: ["CERTIFIED"],
    certifications: [
      {
        certificationId: "cert-1",
        certificationState: "CERTIFIED",
        pitState: "PASS",
        survivorshipState: "PASS",
        certifiedAt: "2026-02-28T09:00:00+00:00",
      },
    ],
  },
};

describe("control room view model", () => {
  it("derives the status strip from the snapshot", () => {
    const model = buildControlRoomModel(measured);
    const byId = Object.fromEntries(model.kpis.map((kpi) => [kpi.id, kpi]));
    expect(byId.overall?.value).toBe("FAIL");
    expect(byId.overall?.tone).toBe("bad");
    expect(byId.guard?.value).toBe("BLOCKED");
    expect(byId.guard?.tone).toBe("bad");
    expect(byId.audit?.value).toBe("FAIL");
    expect(byId.breaks?.value).toBe("1");
    expect(byId.exceptions?.value).toBe("1");
    expect(byId.qualification?.value).toBe("Q04");
    expect(byId.qualification?.tone).not.toBe("good");
    expect(byId.certifications?.value).toBe("1");
    expect(byId.certifications?.foot).toBe("1 in sample");
    expect(JSON.stringify(model.kpis)).not.toContain("18 of 24");
    expect(JSON.stringify(model.kpis)).not.toContain("Q04 / Q11");
  });

  it("does not paint unmeasured, blocked, or catalog-only states green", () => {
    const model = buildControlRoomModel(measured);
    expect(modelHasFakeGreen(model)).toEqual([]);
    expect(model.apiRows[0]?.status.label).toBe("OBSERVED");
    expect(model.apiRows[0]?.status.tone).toBe("neutral");
    expect(model.apiRows[0]?.latency).toBe(UNMEASURED);
    expect(model.apiRows[1]?.status.tone).toBe("bad");
    expect(model.eventRows[0]?.throughput).toBe(UNMEASURED);
    expect(model.eventRows[0]?.status.tone).not.toBe("good");
    expect(model.families[0]?.historical.tone).toBe("info");
    expect(model.families[0]?.live.tone).toBe("bad");
    expect(model.dataPlane.pit.tone).toBe("good");
    expect(model.auditRows.find((row) => row.label === "Evidence store")?.value).toBe(UNMEASURED);
    expect(model.auditRows.find((row) => row.label === "Tamper detection")?.tone).toBe("bad");
  });

  it("keeps an empty snapshot unmeasured instead of inventing screenshot values", () => {
    const model = buildControlRoomModel({});
    expect(model.kpis.find((kpi) => kpi.id === "overall")?.value).toBe(UNMEASURED);
    expect(model.kpis.find((kpi) => kpi.id === "breaks")?.value).toBe("—");
    expect(model.kpis.find((kpi) => kpi.id === "qualification")?.value).toBe(UNMEASURED);
    expect(model.families).toEqual([]);
    expect(model.breaks).toEqual([]);
    expect(model.exceptions).toEqual([]);
    expect(model.experiments).toEqual([]);
    expect(model.notes).toEqual([]);
    expect(model.gates.every((gate) => gate.visual === "pending")).toBe(true);
    expect(modelHasFakeGreen(model)).toEqual([]);
    expect(model.researchKpis.every((kpi) => kpi.value === UNMEASURED)).toBe(true);
  });

  it("maps gaps, readiness, qualification, and evidence from real fields", () => {
    const model = buildControlRoomModel(measured);
    expect(model.gaps.total).toBe("10");
    expect(model.gaps.buckets.find((bucket) => bucket.id === "completed")?.value).toBe("3");
    expect(model.gaps.buckets.find((bucket) => bucket.id === "progress")?.value).toBe("2");
    expect(model.gaps.buckets.find((bucket) => bucket.id === "planned")?.value).toBe("5");
    expect(model.families.map((family) => family.family)).toEqual(["equity", "crypto_spot"]);
    expect(model.gates.find((gate) => gate.code === "Q04")?.visual).toBe("current");
    expect(model.gates.filter((gate) => gate.visual === "complete")).toEqual([]);
    expect(model.researchKpis.find((kpi) => kpi.id === "trials")?.value).toBe("5");
    expect(model.qualification.blockers).toContain("LOW_SAMPLE");
    expect(model.breaks[0]?.description).toBe("left 1 vs right 2");
    expect(model.exceptions[0]?.severity.label).toBe("MEDIUM");
    expect(model.exceptions[0]?.severity.tone).toBe("warn");
    expect(model.timeline.some((row) => row.entity === "evt-2")).toBe(true);
    expect(model.notes).toContain("operator saw the break");
    expect(model.health.label).toBe("FAIL");
  });

  it("marks a qualified run complete and leaves unsupported actions disabled", () => {
    const model = buildControlRoomModel({
      ...measured,
      overallStatus: "PASS",
      research: {
        ...measured.research,
        qualificationRuns: [
          {
            qualificationId: "q-ok",
            status: "QUALIFIED",
            decision: "QUALIFIED",
            currentGate: "Q11_PORTFOLIO_COMPATIBILITY",
          },
        ],
      },
    });
    expect(model.kpis.find((kpi) => kpi.id === "qualification")?.value).toBe("QUALIFIED");
    expect(model.kpis.find((kpi) => kpi.id === "qualification")?.tone).toBe("good");
    expect(model.gates.every((gate) => gate.visual === "complete")).toBe(true);
    expect(model.actions.addNote.enabled).toBe(false);
    expect(model.actions.addNote.reason).toBe(ADD_NOTE_REASON);
    expect(model.actions.viewPipeline.enabled).toBe(false);
    expect(model.actions.viewPipeline.reason).toBe(VIEW_PIPELINE_REASON);
    expect(model.actions.researchLab.href).toBe("/trading/lab");
    expect(model.actions.refresh.enabled).toBe(true);
  });
});

describe("control room rendering", () => {
  it("renders snapshot-backed sections, empty copy, and disabled actions", () => {
    const model = buildControlRoomModel(measured);
    const html = renderToStaticMarkup(
      createElement(ControlRoomView, {
        phase: "ready",
        model,
        image: "/hero.jpg",
        selectedId: "brk-1",
        onSelect: () => undefined,
        onRefresh: () => undefined,
      }),
    );
    expect(html).toContain("CONTROL ROOM");
    expect(html).toContain("INSTITUTIONAL OVERSIGHT");
    expect(html).toContain("Overall Status");
    expect(html).toContain("Live Trading Guard");
    expect(html).toContain("left 1 vs right 2");
    expect(html).toContain("reconciliation.break");
    expect(html).toContain("Evidence store");
    expect(html).toContain("evt-2");
    expect(html).toContain("operator saw the break");
    expect(html).toContain("UNMEASURED");
    expect(html).toContain("disabled");
    expect(html).toContain(ADD_NOTE_REASON);
    expect(html).toContain("data-section=\"health\"");
    expect(html).toContain("is-selected");
    expect(html).toContain("left 1 vs right 2");
    expect(html).not.toMatch(/data-tone="good"[^<]*UNMEASURED/);
    expect(html).not.toContain("18 of 24");
  });

  it("renders loading and error without fake green data", () => {
    const loading = renderToStaticMarkup(
      createElement(ControlRoomView, {
        phase: "loading",
        model: null,
        image: "/hero.jpg",
        selectedId: null,
        onSelect: () => undefined,
        onRefresh: () => undefined,
      }),
    );
    expect(loading).toContain("data-phase=\"loading\"");
    expect(loading).toContain("Loading snapshot…");
    expect(loading).toContain("Live Trading Guard");
    expect(loading).not.toContain("data-tone=\"good\"");
    expect(loading).not.toContain("DEGRADED");

    const error = renderToStaticMarkup(
      createElement(ControlRoomView, {
        phase: "error",
        error: "Control Room snapshot failed",
        model: null,
        image: "/hero.jpg",
        selectedId: null,
        onSelect: () => undefined,
        onRefresh: () => undefined,
      }),
    );
    expect(error).toContain("Control Room snapshot failed");
    expect(error).toContain("Snapshot unavailable.");
    expect(error).not.toContain("data-tone=\"good\"");
  });
});
