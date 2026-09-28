import {
  catalogStatusTone,
  controlRoomStatusLabel,
  controlRoomStatusTone,
  type ControlRoomTone,
} from "../controlRoomStatus";

export const UNMEASURED = "UNMEASURED";
export const DASH = "—";

export const ADD_NOTE_REASON =
  "The control-room snapshot has no operator-note write contract.";
export const VIEW_PIPELINE_REASON =
  "No qualification-pipeline route is registered. Gate state is shown in this column.";

/** Canonical qualification sequence from market_sim.qualification.GATE_ORDER. */
export const QUALIFICATION_GATES: readonly { code: string; id: string }[] = [
  { code: "Q01", id: "Q01_DATA_CERTIFICATION" },
  { code: "Q02", id: "Q02_REPRODUCIBILITY" },
  { code: "Q03", id: "Q03_BASELINE_ACCEPTANCE" },
  { code: "Q04", id: "Q04_WALK_FORWARD" },
  { code: "Q05", id: "Q05_STATISTICAL_MULTIPLICITY" },
  { code: "Q06", id: "Q06_REGIME_MATRIX" },
  { code: "Q07", id: "Q07_ADVERSARIAL_ROBUSTNESS" },
  { code: "Q08", id: "Q08_EXECUTION_VALIDITY" },
  { code: "Q09", id: "Q09_CAPACITY" },
  { code: "Q10", id: "Q10_SEALED_HOLDOUT" },
  { code: "Q11", id: "Q11_PORTFOLIO_COMPATIBILITY" },
];

const ROLLUP_PRIORITY = [
  "FAIL",
  "BLOCKED",
  "BREACH",
  "ERROR",
  "BROKEN",
  "INFEASIBLE",
  "NOT_IMPLEMENTED",
  "UNAVAILABLE",
  "INSUFFICIENT_HISTORY",
  "DEGRADED",
  "FEATURE_GATED",
  "EMPTY",
  "UNMEASURED",
  "ASSUMED",
  "ESTIMATED",
  "PARTIAL",
  "IN_PROGRESS",
  "PENDING",
  "NOT_CHECKED",
  "OBSERVED",
  "MEASURED",
  "CERTIFIED",
  "READY",
  "HEALTHY",
  "VALID",
  "PASS",
];

const ACTIVE_RUN = new Set(["CREATED", "QUEUED", "RUNNING", "PAUSED", "IN_PROGRESS"]);
const FAILED_RUN = new Set(["BLOCKED", "REJECTED", "FAILED", "CANCELLED"]);
const RUN_PRIORITY = ["RUNNING", "QUEUED", "PAUSED", "IN_PROGRESS", "CREATED", "BLOCKED", "REJECTED", "FAILED", "QUALIFIED", "CANCELLED"];

export type Chip = { label: string; tone: ControlRoomTone };
export type GateVisual = "complete" | "current" | "failed" | "pending";

export type ControlRoomModel = {
  generatedAt: string;
  kpis: {
    id: string;
    label: string;
    value: string;
    foot: string;
    tone: ControlRoomTone;
  }[];
  guard: {
    state: Chip;
    assurance: Chip | null;
    detail: string;
    flags: { label: string; value: string; tone: ControlRoomTone }[];
  };
  health: Chip;
  gaps: {
    total: string;
    open: string;
    buckets: { id: string; label: string; value: string; hint: string }[];
    statuses: { label: string; count: string; tone: ControlRoomTone }[];
    measured: boolean;
  };
  families: { family: string; historical: Chip; live: Chip; note: string }[];
  multiAssetStatus: Chip;
  dataPlane: {
    status: Chip;
    certifiedInSample: string;
    sampleCount: string;
    pit: Chip;
    survivorship: Chip;
    recency: string;
    measured: boolean;
  };
  gates: { code: string; id: string; visual: GateVisual }[];
  gateCaption: string;
  researchKpis: { id: string; label: string; value: string; foot: string; tone: ControlRoomTone }[];
  qualification: {
    gate: string;
    status: Chip;
    decision: string;
    blockers: string[];
    sealed: { id: string; status: Chip; strategyId: string }[];
  };
  experiments: { id: string; status: Chip; detail: string }[];
  breaks: {
    id: string;
    time: string;
    source: string;
    type: string;
    description: string;
    severity: Chip;
  }[];
  breakStatus: Chip;
  exceptions: {
    id: string;
    time: string;
    kind: string;
    severity: Chip;
    status: Chip;
    owner: string;
  }[];
  exceptionStatus: Chip;
  auditRows: { label: string; value: string; tone: ControlRoomTone; detail: string }[];
  attention: { id: string; severity: Chip; text: string }[];
  notes: string[];
  timeline: {
    id: string;
    time: string;
    type: string;
    description: string;
    entity: string;
    severity: Chip;
    sortKey: string;
  }[];
  apiRows: { id: string; service: string; status: Chip; latency: string; detail: string }[];
  eventRows: { id: string; service: string; status: Chip; throughput: string; detail: string }[];
  fabricNote: string;
  actions: {
    refresh: { enabled: true };
    addNote: { enabled: false; reason: string };
    viewPipeline: { enabled: false; reason: string };
    researchLab: { enabled: true; href: string; label: string };
  };
};

function rec(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function arr(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item) => item && typeof item === "object") as Record<string, unknown>[];
}

function str(value: unknown): string {
  if (value == null) return "";
  return String(value).trim();
}

function num(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return null;
}

function chip(status: unknown, fallback = UNMEASURED): Chip {
  const label = controlRoomStatusLabel(str(status) || fallback);
  return { label, tone: controlRoomStatusTone(label) };
}

function formatWhen(value: unknown): string {
  const raw = str(value);
  if (!raw) return DASH;
  const match = raw.match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  if (match) return `${match[2]}-${match[3]} ${match[4]}:${match[5]}`;
  return raw.slice(0, 16);
}

function sortKey(value: unknown): string {
  return str(value);
}

export function rollupStatuses(states: string[]): string {
  const values = states.map((state) => state.trim().toUpperCase()).filter(Boolean);
  if (!values.length) return "EMPTY";
  for (const candidate of ROLLUP_PRIORITY) {
    if (values.includes(candidate)) return candidate;
  }
  return UNMEASURED;
}

function gateCode(value: unknown): string | null {
  const raw = str(value).toUpperCase();
  const match = raw.match(/^Q(\d{2})/);
  return match ? `Q${match[1]}` : null;
}

function runTone(status: unknown): Chip {
  const label = controlRoomStatusLabel(str(status) || UNMEASURED);
  if (label === "QUALIFIED") return { label, tone: "good" };
  if (FAILED_RUN.has(label)) return { label, tone: "bad" };
  if (ACTIVE_RUN.has(label)) return { label, tone: "warn" };
  return chip(label);
}

function pickRun(runs: Record<string, unknown>[]): Record<string, unknown> | null {
  if (!runs.length) return null;
  const ranked = [...runs].sort((a, b) => {
    const as = RUN_PRIORITY.indexOf(str(a.status).toUpperCase());
    const bs = RUN_PRIORITY.indexOf(str(b.status).toUpperCase());
    return (as === -1 ? 99 : as) - (bs === -1 ? 99 : bs);
  });
  return ranked[0] ?? null;
}

function countText(status: string, value: unknown): { value: string; tone: ControlRoomTone } {
  if (!["OBSERVED", "MEASURED", "PASS", "EMPTY"].includes(status)) {
    return { value: UNMEASURED, tone: "neutral" };
  }
  const count = num(value);
  if (count == null) return { value: DASH, tone: "neutral" };
  return { value: String(count), tone: "neutral" };
}

function flagBool(
  label: string,
  value: unknown,
  yes = "YES",
  no = "NO",
): { label: string; value: string; tone: ControlRoomTone } {
  if (typeof value !== "boolean") return { label, value: UNMEASURED, tone: "neutral" };
  return { label, value: value ? yes : no, tone: "neutral" };
}

function severityChip(value: unknown): Chip {
  const label = controlRoomStatusLabel(str(value) || UNMEASURED);
  if (label === "HIGH" || label === "CRITICAL" || label === "SEVERE") return { label, tone: "bad" };
  if (label === "MEDIUM" || label === "MODERATE") return { label, tone: "warn" };
  if (label === "LOW" || label === "INFO") return { label, tone: "neutral" };
  return chip(label);
}

export function buildControlRoomModel(snapshot: unknown): ControlRoomModel {
  const snap = rec(snapshot);
  const live = rec(snap.liveTrading);
  const publicStatus = rec(live.publicStatus);
  const gaps = rec(snap.gaps);
  const multi = rec(snap.multiAsset);
  const health = rec(snap.health);
  const recon = rec(snap.reconciliation);
  const exceptions = rec(snap.exceptions);
  const audit = rec(snap.audit);
  const research = rec(snap.research);
  const dataPlane = rec(snap.dataPlane);
  const api = rec(snap.api);
  const events = rec(snap.events);

  const liveAvailable = str(live.LIVE_TRADING_AVAILABLE) || str(publicStatus.LIVE_TRADING_AVAILABLE) || UNMEASURED;
  const guardChip = chip(liveAvailable);
  const assuranceRaw = str(live.status);
  const assurance = assuranceRaw ? chip(assuranceRaw) : null;
  const healthChip = chip(health.overall ?? health.status ?? UNMEASURED);
  const auditChip = chip(audit.status ?? UNMEASURED);
  const researchStatus = str(research.status) || UNMEASURED;
  const dataStatus = str(dataPlane.status) || UNMEASURED;

  const openBreaks = num(recon.openCount);
  const breakStatus = chip(recon.status ?? (openBreaks == null ? UNMEASURED : openBreaks > 0 ? "FAIL" : "EMPTY"));
  const breakTone: ControlRoomTone =
    openBreaks != null && openBreaks > 0 ? "bad" : breakStatus.tone === "good" && openBreaks === 0 ? "good" : breakStatus.tone;

  const openExceptions = num(exceptions.openCount);
  const exceptionStatus = chip(exceptions.status ?? (openExceptions == null ? UNMEASURED : "EMPTY"));
  const exceptionTone: ControlRoomTone =
    openExceptions != null && openExceptions > 0 ? "bad" : exceptionStatus.tone;

  const runs = arr(research.qualificationRuns);
  const focal = pickRun(runs);
  const focalStatus = str(focal?.status || focal?.decision);
  const focalGate = gateCode(focal?.currentGate);
  const qualified = str(focal?.decision).toUpperCase() === "QUALIFIED" || str(focal?.status).toUpperCase() === "QUALIFIED";
  const gateValue = qualified ? "QUALIFIED" : focalGate ?? UNMEASURED;
  const gateTone: ControlRoomTone = qualified ? "good" : focalGate ? runTone(focalStatus || "IN_PROGRESS").tone : "neutral";

  const certs = arr(dataPlane.certifications);
  const certifiedCount = certs.filter((row) => {
    const state = str(row.certificationState).toUpperCase();
    return state === "CERTIFIED" || state === "PASS";
  }).length;
  const dataMeasured = ["OBSERVED", "MEASURED", "PASS", "EMPTY"].includes(dataStatus);
  const certRollup = certs.length
    ? rollupStatuses(certs.map((row) => str(row.certificationState) || UNMEASURED))
    : dataStatus || UNMEASURED;
  const certTone = controlRoomStatusTone(certRollup);
  const latestCert = certs
    .map((row) => str(row.certifiedAt))
    .filter(Boolean)
    .sort()
    .at(-1);

  const pitStates = arrishStrings(dataPlane.pitStates);
  const survStates = arrishStrings(dataPlane.survivorshipStates);
  const pit = chip(pitStates.length ? rollupStatuses(pitStates) : dataMeasured ? "EMPTY" : UNMEASURED);
  const survivorship = chip(survStates.length ? rollupStatuses(survStates) : dataMeasured ? "EMPTY" : UNMEASURED);

  const implKnown = Boolean(gaps.byImplementation && typeof gaps.byImplementation === "object");
  const statusKnown = Boolean(gaps.byStatus && typeof gaps.byStatus === "object");
  const byImpl = rec(gaps.byImplementation);
  const gapCount = num(gaps.count);
  const gapMeasured = gapCount != null;
  const byStatus = rec(gaps.byStatus);
  const operational = ["OBSERVED", "PASS", "MEASURED"].reduce((sum, key) => sum + (num(byStatus[key]) ?? 0), 0);

  const families = arr(multi.families).map((family) => ({
    family: str(family.family) || "unknown",
    historical: chip(family.HISTORICAL_SIM_AVAILABLE ?? family.status ?? UNMEASURED),
    live: chip(family.LIVE_TRADING_AVAILABLE ?? UNMEASURED),
    note: str(family.notes),
  }));

  const gates = QUALIFICATION_GATES.map((gate) => {
    let visual: GateVisual = "pending";
    if (qualified) visual = "complete";
    else if (focalGate === gate.code) {
      visual = FAILED_RUN.has(str(focalStatus).toUpperCase()) ? "failed" : "current";
    }
    return { ...gate, visual };
  });

  const researchMeasured = ["OBSERVED", "MEASURED", "PASS", "EMPTY"].includes(researchStatus);
  const active = countText(researchStatus, research.activeCampaigns);
  const hypotheses = countText(researchStatus, research.hypothesesCount);
  const trials = countText(researchStatus, research.trialCount);
  const qualRuns = countText(researchStatus, research.qualificationRunsCount);

  const blockers = uniqueStrings([
    ...arrishStrings(focal?.blockers),
    ...arrishStrings(research.rejectionReasons),
  ]).slice(0, 12);

  const sealed = arr(research.sealedAttempts).slice(0, 4).map((row) => ({
    id: str(row.sealedAttemptId) || DASH,
    status: chip(row.status ?? UNMEASURED),
    strategyId: str(row.strategyId) || DASH,
  }));

  const experiments = [
    ...arr(research.campaignSample).map((row) => ({
      id: str(row.campaignId) || DASH,
      status: runTone(row.status ?? UNMEASURED),
      detail: str(row.hypothesisId) ? `hypothesis ${str(row.hypothesisId)}` : "campaign",
    })),
    ...runs.slice(0, 8).map((row) => ({
      id: str(row.qualificationId) || DASH,
      status: runTone(row.decision || row.status || UNMEASURED),
      detail: [str(row.currentGate), str(row.strategyId)].filter(Boolean).join(" · ") || "qualification run",
    })),
  ].slice(0, 8);

  const breakRows = arr(recon.breaks).map((row, index) => {
    const source = [str(row.leftSystem), str(row.rightSystem)].filter(Boolean).join(" → ") || str(row.domain) || DASH;
    return {
      id: str(row.breakId) || `break-${index}`,
      time: formatWhen(row.updatedAt || row.createdAt),
      source,
      type: str(row.field) || str(row.domain) || DASH,
      description: str(row.explanation) || str(row.fingerprint) || "Open reconciliation break",
      severity: chip(row.status ?? "OPEN"),
    };
  });

  const exceptionRows = arr(exceptions.items).map((row, index) => ({
    id: str(row.exceptionId) || `exception-${index}`,
    time: formatWhen(row.lastSeen || row.firstSeen),
    kind: str(row.kind) || DASH,
    severity: severityChip(row.severity),
    status: chip(row.status ?? UNMEASURED),
    owner: str(row.owner) || DASH,
  }));

  const auditOk = typeof audit.ok === "boolean" ? audit.ok : null;
  const auditCount = num(audit.count);
  const auditRows: ControlRoomModel["auditRows"] = [
    {
      label: "Chain integrity",
      value: auditChip.label,
      tone: auditChip.tone,
      detail: str(audit.brokenAt) ? `broken at ${str(audit.brokenAt)}` : "verify_audit_chain",
    },
    {
      label: "Tamper detection",
      value: auditOk == null ? UNMEASURED : auditOk ? "PASS" : "FAIL",
      tone: auditOk == null ? "neutral" : auditOk ? "good" : "bad",
      detail: auditOk == null ? "audit verify not supplied" : auditOk ? "chain recomputed" : "hash mismatch",
    },
    {
      label: "Event chain",
      value: auditCount == null ? UNMEASURED : String(auditCount),
      tone: auditChip.tone === "bad" ? "bad" : "neutral",
      detail: "stored audit events",
    },
    {
      label: "Evidence store",
      value: UNMEASURED,
      tone: "neutral",
      detail: "not exposed by the control-room snapshot",
    },
    {
      label: "Latest audit",
      value: str(audit.lastTs) ? formatWhen(audit.lastTs) : UNMEASURED,
      tone: "neutral",
      detail: str(audit.lastTs) ? "timestamp from audit chain" : "no audit timestamp",
    },
    {
      label: "System health",
      value: healthChip.label,
      tone: healthChip.tone,
      detail: "health.overall",
    },
  ];

  const attention: ControlRoomModel["attention"] = [];
  for (const row of breakRows.slice(0, 5)) {
    attention.push({
      id: `att-${row.id}`,
      severity: row.severity.tone === "good" ? chip("OPEN") : row.severity,
      text: `${row.type}: ${row.description}`,
    });
  }
  for (const row of exceptionRows.slice(0, 5)) {
    attention.push({
      id: `att-${row.id}`,
      severity: row.severity.tone === "neutral" && row.severity.label === UNMEASURED ? row.status : row.severity,
      text: `${row.kind} · ${row.status.label}`,
    });
  }
  if (auditOk === false) {
    attention.push({
      id: "att-audit",
      severity: chip("FAIL"),
      text: str(audit.brokenAt) ? `Audit chain failed at ${str(audit.brokenAt)}` : "Audit chain verification failed",
    });
  }
  if (healthChip.tone === "bad") {
    attention.push({
      id: "att-health",
      severity: healthChip,
      text: `System health ${healthChip.label}`,
    });
  }
  if (guardChip.label !== "BLOCKED" && guardChip.label !== UNMEASURED) {
    attention.push({
      id: "att-guard",
      severity: guardChip.tone === "good" ? chip("FAIL") : guardChip,
      text: `Live execution guard reports ${guardChip.label}`,
    });
  }
  for (const reason of blockers.slice(0, 4)) {
    attention.push({
      id: `att-block-${reason}`,
      severity: chip("BLOCKED"),
      text: `Qualification blocker: ${reason}`,
    });
  }

  const noteItems = uniqueStrings([
    ...arrishStrings(snap.notes),
    ...arrishStrings(health.notes),
    ...arrishStrings(recon.notes),
    ...arrishStrings(audit.notes),
    ...arrishStrings(research.notes),
    ...arrishStrings(dataPlane.notes),
  ]);

  const timeline: ControlRoomModel["timeline"] = [];
  for (const ev of arr(audit.recentEvents)) {
    timeline.push({
      id: `audit-${str(ev.eventId) || timeline.length}`,
      time: formatWhen(ev.ts),
      type: "audit",
      description: str(ev.detail) || str(ev.kind) || "Audit event",
      entity: str(ev.eventId) || str(ev.actor) || DASH,
      severity: { label: "LOGGED", tone: "neutral" },
      sortKey: sortKey(ev.ts),
    });
  }
  for (const row of arr(recon.breaks)) {
    timeline.push({
      id: `brk-${str(row.breakId) || timeline.length}`,
      time: formatWhen(row.updatedAt || row.createdAt),
      type: "break",
      description: str(row.explanation) || `${str(row.domain) || "recon"} ${str(row.field) || ""}`.trim(),
      entity: str(row.breakId) || DASH,
      severity: chip(row.status ?? "OPEN"),
      sortKey: sortKey(row.updatedAt || row.createdAt),
    });
  }
  for (const row of arr(exceptions.items)) {
    timeline.push({
      id: `exc-${str(row.exceptionId) || timeline.length}`,
      time: formatWhen(row.lastSeen || row.firstSeen),
      type: "exception",
      description: str(row.kind) || "Exception",
      entity: str(row.exceptionId) || DASH,
      severity: chip(row.severity ?? row.status ?? UNMEASURED),
      sortKey: sortKey(row.lastSeen || row.firstSeen),
    });
  }
  for (const row of runs) {
    timeline.push({
      id: `qual-${str(row.qualificationId) || timeline.length}`,
      time: formatWhen(row.updatedAt || row.createdAt),
      type: "qualification",
      description: [str(row.status), str(row.currentGate)].filter(Boolean).join(" · ") || "Qualification run",
      entity: str(row.qualificationId) || DASH,
      severity: runTone(row.status ?? UNMEASURED),
      sortKey: sortKey(row.updatedAt || row.createdAt),
    });
  }
  for (const row of arr(recon.recentRuns)) {
    timeline.push({
      id: `run-${str(row.runId) || timeline.length}`,
      time: formatWhen(row.createdAt),
      type: "reconciliation",
      description: `${str(row.domain) || "run"} · open ${num(row.openCount) ?? DASH}`,
      entity: str(row.runId) || DASH,
      severity: chip(row.status ?? UNMEASURED),
      sortKey: sortKey(row.createdAt),
    });
  }
  timeline.sort((a, b) => (a.sortKey < b.sortKey ? 1 : a.sortKey > b.sortKey ? -1 : 0));

  const apiTruth = rec(api.truth);
  const apiNotProof = apiTruth.catalog_is_not_runtime_proof !== false;
  const apiRows = arr(api.contracts).map((row, index) => {
    const status = chip(row.status ?? UNMEASURED);
    const method = str(row.method);
    const path = str(row.path);
    return {
      id: method || path ? `${method || "GET"} ${path || DASH}` : `api-${index}`,
      service: `${method || "GET"} ${path || DASH}`,
      status: { label: status.label, tone: catalogStatusTone(status.label, apiNotProof) },
      latency: UNMEASURED,
      detail: str(row.owner) || str(row.description) || DASH,
    };
  });
  const eventRows = arr(events.contracts).map((row, index) => {
    const status = chip(row.status ?? UNMEASURED);
    return {
      id: str(row.eventType) || `event-${index}`,
      service: str(row.eventType) || DASH,
      status: { label: status.label, tone: catalogStatusTone(status.label, true) },
      throughput: UNMEASURED,
      detail: str(row.owner) || str(row.description) || DASH,
    };
  });

  const detail =
    str(publicStatus.detail) ||
    str(live.detail) ||
    (guardChip.label === "BLOCKED"
      ? "Live broker orders remain blocked by LiveTradingGuard."
      : "Live trading guard did not supply an explanation.");

  const flags = [
    flagBool("Unlock env", publicStatus.unlock_env_set),
    flagBool("Adapter", publicStatus.adapter_configured, "SET", "UNSET"),
    flagBool("Human auth", publicStatus.human_authorization_required),
    flagBool("Agent cannot enable", publicStatus.agent_cannot_enable),
  ];

  const generated = formatWhen(snap.generatedAt);

  return {
    generatedAt: generated,
    kpis: [
      {
        id: "overall",
        label: "Overall Status",
        value: chip(snap.overallStatus ?? UNMEASURED).label,
        foot: `health ${healthChip.label}`,
        tone: chip(snap.overallStatus ?? UNMEASURED).tone,
      },
      {
        id: "guard",
        label: "Live Execution Guard",
        value: guardChip.label,
        foot: assurance ? `assurance ${assurance.label}` : "assurance UNMEASURED",
        tone: guardChip.tone,
      },
      {
        id: "audit",
        label: "Audit Integrity",
        value: auditChip.label,
        foot: auditCount == null ? "count UNMEASURED" : `${auditCount} events`,
        tone: auditChip.tone,
      },
      {
        id: "breaks",
        label: "Open Breaks",
        value: openBreaks == null ? DASH : String(openBreaks),
        foot: breakStatus.label,
        tone: breakTone,
      },
      {
        id: "exceptions",
        label: "Open Exceptions",
        value: openExceptions == null ? DASH : String(openExceptions),
        foot: exceptionStatus.label,
        tone: exceptionTone,
      },
      {
        id: "qualification",
        label: "Qualification Gate",
        value: gateValue,
        foot: focal ? str(focal.currentGate) || str(focal.status) || researchStatus : researchMeasured ? "no active run" : UNMEASURED,
        tone: gateTone,
      },
      {
        id: "certifications",
        label: "Data Certifications",
        value: dataMeasured ? String(certifiedCount) : UNMEASURED,
        foot: dataMeasured ? `${certs.length} in sample` : "sample UNMEASURED",
        tone: dataMeasured && certs.length > 0 ? certTone : "neutral",
      },
    ],
    guard: {
      state: guardChip,
      assurance,
      detail,
      flags,
    },
    health: healthChip,
    gaps: {
      total: gapMeasured ? String(gapCount) : DASH,
      open: num(gaps.openGapCount) == null ? DASH : String(num(gaps.openGapCount)),
      measured: gapMeasured && implKnown,
      buckets: [
        {
          id: "operational",
          label: "Operational",
          value: statusKnown ? String(operational) : UNMEASURED,
          hint: "STATUS OBSERVED / PASS / MEASURED",
        },
        {
          id: "progress",
          label: "In progress",
          value: implKnown ? String(num(byImpl.PARTIAL) ?? 0) : UNMEASURED,
          hint: "IMPLEMENTATION PARTIAL",
        },
        {
          id: "planned",
          label: "Planned",
          value: implKnown ? String(num(byImpl.NOT_IMPLEMENTED) ?? 0) : UNMEASURED,
          hint: "IMPLEMENTATION NOT_IMPLEMENTED",
        },
        {
          id: "completed",
          label: "Completed",
          value: implKnown ? String(num(byImpl.PRESENT) ?? 0) : UNMEASURED,
          hint: "IMPLEMENTATION PRESENT",
        },
      ],
      statuses: Object.entries(byStatus).map(([label, count]) => ({
        label: controlRoomStatusLabel(label),
        count: String(num(count) ?? 0),
        tone: controlRoomStatusTone(label),
      })),
    },
    families,
    multiAssetStatus: families.length
      ? chip(rollupStatuses(families.map((family) => family.historical.label)))
      : chip(multi.featureEnabled === false ? "FEATURE_GATED" : UNMEASURED),
    dataPlane: {
      status: chip(dataStatus),
      certifiedInSample: dataMeasured ? String(certifiedCount) : UNMEASURED,
      sampleCount: dataMeasured ? String(certs.length || num(dataPlane.certificationCount) || 0) : UNMEASURED,
      pit,
      survivorship,
      recency: latestCert ? formatWhen(latestCert) : UNMEASURED,
      measured: dataMeasured,
    },
    gates,
    gateCaption: qualified
      ? "Run decision QUALIFIED — gates marked complete from that decision."
      : focalGate
        ? `Current gate ${focalGate}. Earlier gates stay pending until a gate result is recorded.`
        : researchMeasured
          ? "No current gate on the focal qualification run."
          : "Qualification progression UNMEASURED.",
    researchKpis: [
      { id: "campaigns", label: "Active Campaigns", value: active.value, foot: researchMeasured ? "sample statuses" : UNMEASURED, tone: active.tone },
      { id: "hypotheses", label: "Hypotheses", value: hypotheses.value, foot: researchMeasured ? "bounded sample" : UNMEASURED, tone: hypotheses.tone },
      { id: "trials", label: "Trials Executed", value: trials.value, foot: researchMeasured ? "count_trials" : UNMEASURED, tone: trials.tone },
      { id: "runs", label: "Qualification Runs", value: qualRuns.value, foot: researchMeasured ? "counted" : UNMEASURED, tone: qualRuns.tone },
    ],
    qualification: {
      gate: focal ? str(focal.currentGate) || UNMEASURED : UNMEASURED,
      status: focal ? runTone(focal.status ?? UNMEASURED) : chip(researchMeasured ? "EMPTY" : UNMEASURED),
      decision: str(focal?.decision) || DASH,
      blockers,
      sealed,
    },
    experiments,
    breaks: breakRows,
    breakStatus: { ...breakStatus, tone: breakTone },
    exceptions: exceptionRows,
    exceptionStatus: { ...exceptionStatus, tone: exceptionTone },
    auditRows,
    attention: attention.slice(0, 8),
    notes: noteItems,
    timeline: timeline.slice(0, 24),
    apiRows,
    eventRows,
    fabricNote: apiNotProof
      ? "API catalog status is a contract declaration, not a latency probe. Throughput is UNMEASURED."
      : "Event throughput is UNMEASURED unless a counter is present.",
    actions: {
      refresh: { enabled: true },
      addNote: { enabled: false, reason: ADD_NOTE_REASON },
      viewPipeline: { enabled: false, reason: VIEW_PIPELINE_REASON },
      researchLab: { enabled: true, href: "/trading/lab", label: "Research Lab" },
    },
  };
}

function arrishStrings(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => str(item)).filter(Boolean);
  const one = str(value);
  return one ? [one] : [];
}

function uniqueStrings(values: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const value of values) {
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push(value);
  }
  return out;
}

export function modelHasFakeGreen(model: ControlRoomModel): string[] {
  const problems: string[] = [];
  const nonGreen = new Set([
    "UNMEASURED",
    "PARTIAL",
    "IN_PROGRESS",
    "FEATURE_GATED",
    "EMPTY",
    "NOT_CHECKED",
    "PENDING",
    "FAIL",
    "DEGRADED",
    "BLOCKED",
    "BREACH",
    "ERROR",
    "BROKEN",
    "NOT_IMPLEMENTED",
    "ASSUMED",
    "ESTIMATED",
    "UNAVAILABLE",
  ]);
  const visit = (label: string, tone: ControlRoomTone, where: string) => {
    if (tone === "good" && nonGreen.has(label)) problems.push(`${where}:${label}`);
  };
  for (const kpi of model.kpis) visit(kpi.value, kpi.tone, kpi.id);
  visit(model.guard.state.label, model.guard.state.tone, "guard");
  visit(model.health.label, model.health.tone, "health");
  for (const row of model.auditRows) visit(row.value, row.tone, row.label);
  for (const row of model.apiRows) visit(row.status.label, row.status.tone, `api:${row.service}`);
  for (const row of model.eventRows) visit(row.status.label, row.status.tone, `event:${row.service}`);
  for (const row of model.families) {
    visit(row.historical.label, row.historical.tone, row.family);
    visit(row.live.label, row.live.tone, `${row.family}-live`);
  }
  return problems;
}
