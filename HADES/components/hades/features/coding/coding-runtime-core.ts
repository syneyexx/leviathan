/**
 * Shared Coding runtime pure helpers (skin-agnostic).
 * Source of truth for status labels, parsing, event merge, OmniRoute labels.
 */

export type CodingStatusTone = "success" | "warning" | "danger" | "neutral";

export type CodingTestSuite =
  | "auto"
  | "unittest"
  | "pytest"
  | "npm_test"
  | "go_test"
  | "cargo_test"
  | "ctest";

export type CodingStrategy = "fast" | "investigate" | "auto";

export type CodingAutonomyProfile =
  | "analyze_only"
  | "managed_workspace_modify"
  | "reviewable_result";

export const CODING_JOB_STORAGE_KEY = "hades-coding-active-job-id";
export const CODING_JOB_EVENT_CURSOR_KEY = "hades-coding-job-event-cursor";

export const JOB_TERMINAL = new Set([
  "verified",
  "failed",
  "cancelled",
  "interrupted",
  "tests_failed",
  "completed",
  "no_change",
  "implementation_missing",
  "model_output_invalid",
  "model_unavailable",
]);

export const JOB_SUCCESS = new Set(["verified", "completed"]);

export const TEST_SUITES: Array<{ id: CodingTestSuite; label: string }> = [
  { id: "auto", label: "Auto (aanbevolen)" },
  { id: "unittest", label: "Python unittest" },
  { id: "pytest", label: "Python pytest" },
  { id: "npm_test", label: "npm test (Windows/Node)" },
  { id: "go_test", label: "go test" },
  { id: "cargo_test", label: "cargo test" },
  { id: "ctest", label: "CTest" },
];

export function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export function buildStatusLabel(status: string): string {
  const copy: Record<string, string> = {
    verified: "Geverifieerd",
    tests_failed: "Tests mislukt",
    running: "Bezig",
    queued: "In wachtrij",
    pause_requested: "Pauze aangevraagd",
    paused: "Gepauzeerd",
    cancel_requested: "Annulering bezig",
    cancelled: "Geannuleerd",
    interrupted: "Onderbroken",
    completed: "Voltooid",
    error: "Fout",
    failed: "Mislukt",
    still_running: "Nog bezig",
    no_change: "Geen wijziging",
    implementation_missing: "Implementatie ontbreekt",
    model_output_invalid: "Ongeldige model-output",
    model_unavailable: "Model niet beschikbaar",
    COMPLETED_VERIFIED: "Volledig geverifieerd",
    COMPLETED_PARTIALLY_VERIFIED: "Gedeeltelijk geverifieerd",
    FAILED_VERIFICATION: "Verificatie mislukt",
    BLOCKED: "Geblokkeerd",
    AWAITING_APPROVAL: "Wacht op goedkeuring",
    CANCELLED: "Geannuleerd",
    INTERRUPTED: "Onderbroken",
    CONFLICT: "Conflict",
    RUNNING: "Bezig",
    INCOMPLETE: "Onvolledig",
  };
  return copy[status] ?? status;
}

export function buildStatusTone(status: string): CodingStatusTone {
  if (
    status === "verified" ||
    status === "completed" ||
    status === "COMPLETED_VERIFIED"
  ) {
    return "success";
  }
  if (
    [
      "running",
      "queued",
      "pause_requested",
      "cancel_requested",
      "still_running",
      "RUNNING",
      "AWAITING_APPROVAL",
      "COMPLETED_PARTIALLY_VERIFIED",
      "INCOMPLETE",
    ].includes(status)
  ) {
    return "warning";
  }
  if (
    [
      "tests_failed",
      "failed",
      "error",
      "cancelled",
      "interrupted",
      "no_change",
      "implementation_missing",
      "model_output_invalid",
      "model_unavailable",
      "FAILED_VERIFICATION",
      "BLOCKED",
      "CANCELLED",
      "INTERRUPTED",
      "CONFLICT",
    ].includes(status)
  ) {
    return "danger";
  }
  if (status === "paused") return "warning";
  return "neutral";
}

export function parseArgv(raw: string): string[] {
  const trimmed = raw.trim();
  if (!trimmed) return [];
  if (trimmed.startsWith("[")) {
    const parsed = JSON.parse(trimmed) as unknown;
    if (!Array.isArray(parsed) || !parsed.every((item) => typeof item === "string")) {
      throw new Error("JSON argv moet een array van strings zijn.");
    }
    return parsed;
  }
  return trimmed.split(/\s+/).filter(Boolean);
}

export function parseEdits(raw: string): Array<Record<string, unknown>> {
  const trimmed = raw.trim();
  if (!trimmed) return [];
  const parsed = JSON.parse(trimmed) as unknown;
  if (!Array.isArray(parsed)) throw new Error("Edits moeten een JSON-array zijn.");
  return parsed as Array<Record<string, unknown>>;
}

export function collectBuildLogs(result: Record<string, unknown> | null): string {
  if (!result) return "";
  const chunks: string[] = [];
  const report = result.report as Record<string, unknown> | undefined;
  if (report?.attempts != null) chunks.push(`Pogingen: ${String(report.attempts)}`);
  if (typeof result.error === "string" && result.error) chunks.push(`Fout: ${result.error}`);
  const tests = Array.isArray(result.test_results) ? result.test_results : [];
  for (const [index, item] of tests.entries()) {
    const test = item as Record<string, unknown>;
    chunks.push(`--- test ${index + 1}: ${dash(test.suite as string)} (${dash(test.status as string)}) ---`);
    if (Array.isArray(test.command)) chunks.push(`$ ${(test.command as string[]).join(" ")}`);
    if (typeof test.stdout === "string" && test.stdout.trim()) chunks.push(test.stdout.trim());
    if (typeof test.stderr === "string" && test.stderr.trim()) chunks.push(test.stderr.trim());
  }
  return chunks.join("\n\n");
}

export function collectReviewDiffText(result: Record<string, unknown> | null): string {
  if (!result) return "";
  const chunks: string[] = [];
  const diffText = typeof result.diff_text === "string" ? result.diff_text.trim() : "";
  const patchText = typeof result.patch_text === "string" ? result.patch_text.trim() : "";
  if (diffText) chunks.push(diffText);
  else if (patchText) chunks.push(patchText);

  const conflicts = Array.isArray(result.conflicts) ? result.conflicts : [];
  if (conflicts.length) {
    chunks.push("--- apply-conflicten (run) ---");
    for (const item of conflicts) {
      const row = item as Record<string, unknown>;
      const path = String(row.path || row.file || "onbekend");
      const reason = String(row.reason || row.message || JSON.stringify(row));
      chunks.push(`${path}\n  ${reason}`);
    }
  }

  const planned = Array.isArray(result.planned_edits) ? result.planned_edits : [];
  const applied = Array.isArray(result.applied_edits) ? result.applied_edits : [];
  const editRows = [...applied, ...planned].filter((item) => item && typeof item === "object") as Array<
    Record<string, unknown>
  >;
  if (!chunks.length && editRows.length) {
    chunks.push("--- geplande/gewijzigde bestanden ---");
    for (const edit of editRows) {
      const path = String(edit.path || edit.file || "onbekend");
      const action = String(edit.action || edit.status || "edit");
      const preview =
        typeof edit.diff === "string"
          ? edit.diff.trim()
          : typeof edit.patch === "string"
            ? edit.patch.trim()
            : typeof edit.content === "string"
              ? edit.content.trim()
              : "";
      chunks.push(`${action} ${path}${preview ? `\n${preview}` : ""}`);
    }
  }

  return chunks.join("\n\n").trim();
}

export function formatConflictRows(items: Array<Record<string, unknown>>): string {
  if (!items.length) return "";
  return items
    .map((row) => {
      const path = String(row.path || row.file || "onbekend");
      const reason = String(row.reason || row.message || "");
      const expected = typeof row.expected === "string" ? row.expected : "";
      const actual = typeof row.actual === "string" ? row.actual : "";
      const lines = [`${path}`, reason ? `  reden: ${reason}` : ""];
      if (expected) lines.push(`  verwacht: ${expected.slice(0, 16)}…`);
      if (actual) lines.push(`  actueel: ${actual.slice(0, 16)}…`);
      return lines.filter(Boolean).join("\n");
    })
    .join("\n\n");
}

export function loopPhaseLabel(phase: unknown): string {
  const key = String(phase || "step");
  const labels: Record<string, string> = {
    plan: "Plan",
    apply_edits: "Apply edits",
    test: "Test",
    diagnose: "Diagnose (fail)",
    repair: "Repair / fix",
    error: "Error",
    investigate: "Investigate",
    review: "Review",
    verify: "Verify",
    delivery: "Delivery",
  };
  return labels[key] ?? key;
}

export function parseContextFiles(raw: string): Array<{ path: string; content?: string }> {
  const trimmed = raw.trim();
  if (!trimmed) return [];
  const parsed = JSON.parse(trimmed) as unknown;
  if (!Array.isArray(parsed)) throw new Error("context_files moet een JSON-array zijn.");
  return parsed.map((item) => {
    if (!item || typeof item !== "object") throw new Error("Elke context_file vereist path.");
    const row = item as Record<string, unknown>;
    const path = String(row.path || "").trim();
    if (!path) throw new Error("Elke context_file vereist path.");
    return {
      path,
      content: typeof row.content === "string" ? row.content : undefined,
    };
  });
}

export function persistActiveJobId(jobId: string | null): void {
  try {
    if (jobId) sessionStorage.setItem(CODING_JOB_STORAGE_KEY, jobId);
    else sessionStorage.removeItem(CODING_JOB_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

export function readPersistedActiveJobId(): string | null {
  try {
    return sessionStorage.getItem(CODING_JOB_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function readJobEventCursor(jobId: string): number {
  try {
    const raw = sessionStorage.getItem(`${CODING_JOB_EVENT_CURSOR_KEY}:${jobId}`);
    const after = raw ? Number(raw) : 0;
    return Number.isFinite(after) ? after : 0;
  } catch {
    return 0;
  }
}

export function writeJobEventCursor(jobId: string, cursor: number): void {
  try {
    sessionStorage.setItem(`${CODING_JOB_EVENT_CURSOR_KEY}:${jobId}`, String(cursor));
  } catch {
    /* ignore */
  }
}

export function mergeJobEvents(
  previous: Array<Record<string, unknown>>,
  incoming: Array<Record<string, unknown>>,
  limit = 200,
): Array<Record<string, unknown>> {
  const seen = new Set(previous.map((e) => String(e.id || e.seq)));
  const merged = [...previous];
  for (const row of incoming) {
    const key = String(row.id || row.seq);
    if (!seen.has(key)) {
      seen.add(key);
      merged.push(row);
    }
  }
  return merged.slice(-limit);
}

export function formatOmnirouteRouting(snapshot: unknown): string {
  const row = snapshot && typeof snapshot === "object" ? (snapshot as Record<string, unknown>) : null;
  if (!row) return "Standard provider";
  if (row.fallback_used) {
    return `Standard provider · OmniRoute fallback: ${String(row.fallback_reason || row.status_label || "unavailable")}`;
  }
  if (row.omniroute_used) {
    const mode = String(row.routing_mode || "auto");
    const model = row.selected_model ? String(row.selected_model) : "";
    const provider = row.selected_provider ? String(row.selected_provider) : "";
    if (!model && (mode === "auto" || !row.reported_by_omniroute)) {
      return "OmniRoute · Auto";
    }
    return ["OmniRoute", model, provider].filter(Boolean).join(" · ");
  }
  if (row.omniroute_requested) {
    return `OmniRoute · ${String(row.status_label || row.reason || "pending")}`;
  }
  return "Standard provider";
}

export function extractFrontierStatus(result: Record<string, unknown> | null | undefined): string | null {
  if (!result) return null;
  const coding = result.coding as Record<string, unknown> | undefined;
  if (coding && typeof coding.frontier_status === "string") return coding.frontier_status;
  if (typeof result.frontier_status === "string") return result.frontier_status;
  return null;
}

/** Prominent NL reason when a Coding run produced zero useful edits / failed honestly. */
export function extractCodingFailureReason(
  result: Record<string, unknown> | null | undefined,
): string | null {
  if (!result || typeof result !== "object") return null;
  const coding = (result.coding as Record<string, unknown> | undefined) || {};
  const evidence =
    (coding.failure_evidence as Record<string, unknown> | undefined) ||
    (result.failure_evidence as Record<string, unknown> | undefined) ||
    {};
  if (typeof evidence.human_reason_nl === "string" && evidence.human_reason_nl.trim()) {
    return evidence.human_reason_nl;
  }
  if (
    typeof coding.summary === "string" &&
    /model|ongeldig|unavailable|analyze|geen |blokkeer|afgekapt|implementatie/i.test(coding.summary)
  ) {
    return coding.summary;
  }
  const propose = (coding.propose as Record<string, unknown> | undefined) || {};
  const blocker =
    (typeof evidence.terminal_blocker === "string" && evidence.terminal_blocker) ||
    (typeof propose.blocker === "string" && propose.blocker) ||
    (typeof result.status === "string" &&
    ["no_change", "implementation_missing", "model_output_invalid", "model_unavailable"].includes(result.status)
      ? result.status
      : null);
  const copy: Record<string, string> = {
    model_output_invalid: "Model antwoordde, maar edit-JSON was ongeldig.",
    truncated_output: "Modelresponse werd afgekapt.",
    model_unavailable: "Geen bruikbaar Coding-model beschikbaar.",
    model_timeout: "Model-aanroep time-out.",
    autonomy_blocked: "Autonomy analyze_only blokkeerde wijzigingen.",
    analyze_only: "Analyze-only: deze taak mag geen bestanden wijzigen.",
    scope_not_found: "Geen relevante bestanden gevonden.",
    no_change: "Geen bestanden gewijzigd; groene baseline telt niet als implementatie.",
    implementation_missing: "Implementatie ontbreekt: geen geldige edits toegepast.",
    empty_edits: "Model leverde een lege edits-lijst.",
  };
  if (blocker && copy[blocker]) return copy[blocker];
  return null;
}

export type CodingPreflightState = {
  ready: boolean;
  blockers: Array<{ code: string; message: string }>;
  warnings: Array<{ code: string; message: string }>;
  humanSummaryNl: string;
  analyzeOnlyBlocksMutation: boolean;
};

export function evaluateCodingPreflightClient(input: {
  sourceRepo: string;
  goal: string;
  hasManualEdits: boolean;
  backendReachable: boolean;
  lmConnected: boolean;
  activeModel: string | null;
  useOmniroute: boolean;
  omnirouteUsable: boolean;
  autonomyProfile: string;
}): CodingPreflightState {
  const blockers: Array<{ code: string; message: string }> = [];
  const warnings: Array<{ code: string; message: string }> = [];
  if (!input.sourceRepo.trim()) {
    blockers.push({ code: "source_repo_missing", message: "Vul een source_repo pad in." });
  }
  if (!input.backendReachable) {
    blockers.push({ code: "backend_unreachable", message: "Backend is niet bereikbaar." });
  }
  const mutationHint =
    /\b(fix|repair|repareer|implement|maak|bouw|create|add|voeg|refactor|wijzig|change|patch)\b/i.test(
      input.goal,
    ) || Boolean(input.goal.trim());
  if (input.autonomyProfile === "analyze_only" && mutationHint && !input.hasManualEdits) {
    blockers.push({
      code: "analyze_only",
      message: "Analyze-only: deze taak mag geen bestanden wijzigen.",
    });
  }
  const needsModel =
    !input.hasManualEdits && Boolean(input.goal.trim()) && input.autonomyProfile !== "analyze_only";
  if (needsModel) {
    if (input.useOmniroute && !input.omnirouteUsable) {
      blockers.push({
        code: "omniroute_unavailable",
        message: "OmniRoute is aangevraagd maar niet bruikbaar.",
      });
    } else if (!input.useOmniroute && (!input.lmConnected || !input.activeModel)) {
      blockers.push({
        code: "model_unavailable",
        message: "Geen bruikbaar Coding-model beschikbaar.",
      });
    }
  }
  if (!input.hasManualEdits && !input.goal.trim()) {
    warnings.push({ code: "goal_empty", message: "Geef een goal of edits-JSON op." });
  }
  return {
    ready: blockers.length === 0,
    blockers,
    warnings,
    humanSummaryNl:
      blockers[0]?.message || (blockers.length ? "Preflight niet gereed." : "Klaar om te starten."),
    analyzeOnlyBlocksMutation: input.autonomyProfile === "analyze_only" && mutationHint,
  };
}

export function extractChangedFiles(result: Record<string, unknown> | null | undefined): Array<{
  path: string;
  action: string;
  diff?: string;
}> {
  if (!result) return [];
  const rows: Array<{ path: string; action: string; diff?: string }> = [];
  const pools = [
    Array.isArray(result.files) ? result.files : [],
    Array.isArray(result.applied_edits) ? result.applied_edits : [],
    Array.isArray(result.planned_edits) ? result.planned_edits : [],
  ];
  const seen = new Set<string>();
  for (const pool of pools) {
    for (const item of pool) {
      if (!item || typeof item !== "object") continue;
      const row = item as Record<string, unknown>;
      const path = String(row.path || row.file || "").trim();
      if (!path || seen.has(path)) continue;
      seen.add(path);
      const diff =
        typeof row.diff === "string"
          ? row.diff
          : typeof row.patch === "string"
            ? row.patch
            : typeof row.unified_diff === "string"
              ? row.unified_diff
              : undefined;
      rows.push({
        path,
        action: String(row.action || row.status || row.kind || "modify"),
        diff,
      });
    }
  }
  return rows;
}

export function readCodingJobFromLocation(hash = typeof window !== "undefined" ? window.location.hash : ""): string | null {
  try {
    const hashQuery = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
    const fromHash = new URLSearchParams(hashQuery).get("codingJob");
    if (fromHash?.trim()) return fromHash.trim();
    if (typeof window !== "undefined") {
      const fromSearch = new URLSearchParams(window.location.search).get("codingJob");
      if (fromSearch?.trim()) return fromSearch.trim();
    }
  } catch {
    /* ignore */
  }
  return null;
}

export function writeCodingJobToLocation(jobId: string | null): void {
  try {
    const hash = window.location.hash || "";
    const path = hash.replace(/^#/, "").split("?")[0] || "";
    const params = new URLSearchParams(hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "");
    if (jobId) params.set("codingJob", jobId);
    else params.delete("codingJob");
    const query = params.toString();
    const next = `#${path}${query ? `?${query}` : ""}`;
    if (window.location.hash !== next) {
      window.history.replaceState({}, "", `${window.location.pathname}${window.location.search}${next}`);
    }
  } catch {
    /* ignore */
  }
}

/** Canonical Advanced Coding entry under FINALBETA. */
export function finalBetaCodingHash(jobId?: string | null): string {
  const q = jobId ? `?codingJob=${encodeURIComponent(jobId)}` : "";
  return `#/fb/coding${q}`;
}
