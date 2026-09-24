import { useCallback, useEffect, useMemo, useState } from "react";
import { media } from "../assets/media";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import {
  codingEmptySessionsCopy,
  MISSION_CHIPS,
  statusPillClass,
  statusPillLabel,
  type CodingMission,
  type CodingPatch,
  type CodingSession,
  type CodingSessionDetail,
  type CodingStatusResponse,
  type CodingStep,
  type CodingWorkspaceEntry,
} from "./coding/types";

const ACTIVE = new Set(["RUNNING", "WAITING_APPROVAL"]);

const OBJECTIVE_OPTIONS: Array<{ mission: CodingMission; label: string }> = [
  { mission: "GENERIC", label: "Implement New Feature" },
  { mission: "SCAFFOLD", label: "Scaffold Project" },
  { mission: "REVIEW", label: "Review Diff" },
  { mission: "TEST", label: "Write Tests" },
  { mission: "FIX", label: "Fix Bug" },
];

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function formatTime(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  } catch {
    return "—";
  }
}

function countDiffLines(diff: string): { plus: number; minus: number } {
  let plus = 0;
  let minus = 0;
  for (const line of diff.split("\n")) {
    if (line.startsWith("+") && !line.startsWith("+++")) plus += 1;
    if (line.startsWith("-") && !line.startsWith("---")) minus += 1;
  }
  return { plus, minus };
}

function renderDiff(diff: string): Array<{ cls: string; text: string }> {
  return diff.split("\n").map((line) => {
    if (line.startsWith("@@")) return { cls: "lv-ca-hunk", text: line };
    if (line.startsWith("+") && !line.startsWith("+++")) return { cls: "lv-ca-add", text: line };
    if (line.startsWith("-") && !line.startsWith("---")) return { cls: "lv-ca-del", text: line };
    return { cls: "", text: line };
  });
}

function workspaceBasename(root?: string | null): string {
  if (!root) return "—";
  const cleaned = root.replace(/[/\\]+$/, "");
  const parts = cleaned.split(/[/\\]/).filter(Boolean);
  return parts[parts.length - 1] || cleaned;
}

function stepOutput(step: CodingStep | undefined): Record<string, unknown> {
  if (!step) return {};
  const raw = step.output ?? step.output_json;
  return raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
}

function resolvePending(detail: CodingSessionDetail): { approvalId: string; capabilityId?: string } | null {
  const fromSession = detail.session.pending_capability;
  if (fromSession?.approval_id) {
    return {
      approvalId: String(fromSession.approval_id),
      capabilityId: fromSession.capability_id ? String(fromSession.capability_id) : undefined,
    };
  }
  const pending = detail.steps.find(
    (s) => s.approval_id && (s.status === "PENDING" || s.kind === "WAIT_APPROVAL"),
  );
  if (!pending?.approval_id) return null;
  return {
    approvalId: pending.approval_id,
    capabilityId: pending.capability_id ?? undefined,
  };
}

const TERMINAL_STATUSES = new Set([
  "COMPLETED",
  "FAILED",
  "UNVERIFIED",
  "PARTIAL",
  "RESOURCE_EXHAUSTED",
  "CANCELLED",
  "DISABLED",
]);

export function CodingPage() {
  const toast = useAppToast();
  const [status, setStatus] = useState<CodingStatusResponse | null>(null);
  const [sessions, setSessions] = useState<CodingSession[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CodingSessionDetail | null>(null);
  const [tree, setTree] = useState<CodingWorkspaceEntry[]>([]);
  const [wsTab, setWsTab] = useState<"files" | "changes" | "notes">("files");
  const [termTab, setTermTab] = useState<"terminal" | "logs" | "tests">("terminal");
  const [diffTab, setDiffTab] = useState<"applied" | "pending" | "all">("pending");
  const [reviewTab, setReviewTab] = useState<"summary" | "tests" | "review">("summary");
  const [selectedPatchId, setSelectedPatchId] = useState<string | null>(null);
  const [goal, setGoal] = useState(
    "Implement a risk analysis and position sizing engine for our trading system.\n\nRequirements:\n- Support multiple risk models\n- Position sizing constraints\n- Unit tests\n- Update documentation",
  );
  const [mission, setMission] = useState<CodingMission>("GENERIC");
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const selected = detail?.session ?? sessions.find((s) => s.session_id === selectedId) ?? null;
  const steps: CodingStep[] = detail?.steps ?? [];
  const patches: CodingPatch[] = detail?.patches ?? [];
  const verification = detail?.verification ?? null;
  const neuro = detail?.neuro ?? null;

  const selectedPatch = useMemo(() => {
    if (!patches.length) return null;
    return patches.find((p) => p.patch_id === selectedPatchId) ?? patches[0];
  }, [patches, selectedPatchId]);

  const patchStats = useMemo(() => {
    let plus = 0;
    let minus = 0;
    for (const p of patches) {
      const c = countDiffLines(p.diff_unified);
      plus += c.plus;
      minus += c.minus;
    }
    return { files: patches.length, plus, minus };
  }, [patches]);

  const loadStatus = useCallback(async () => {
    try {
      const res = await api.codingStatus();
      setStatus(res);
      setLoadError(null);
    } catch (err) {
      setStatus(null);
      setLoadError(errMsg(err, "Coding status unavailable"));
    }
  }, []);

  const loadSessions = useCallback(async () => {
    try {
      const res = await api.listCodingSessions();
      setSessions(res.sessions);
      if (res.sessions.length === 0) {
        setSelectedId(null);
      } else if (!selectedId || !res.sessions.some((s) => s.session_id === selectedId)) {
        setSelectedId(res.sessions[0].session_id);
      }
    } catch (err) {
      setSessions([]);
      if (!(err instanceof ApiError && err.status === 404)) {
        setLoadError(errMsg(err, "Failed to load coding sessions"));
      }
    }
  }, [selectedId]);

  const loadDetail = useCallback(async (sessionId: string) => {
    try {
      const res = await api.getCodingSession(sessionId);
      setDetail(res);
      if (res.patches.length && !selectedPatchId) {
        setSelectedPatchId(res.patches[0].patch_id);
      }
    } catch (err) {
      setDetail(null);
      setLoadError(errMsg(err, "Failed to load session"));
    }
  }, [selectedPatchId]);

  const loadTree = useCallback(async (sessionId?: string | null) => {
    try {
      const res = await api.codingWorkspaceTree({
        recursive: false,
        ...(sessionId ? { sessionId } : {}),
      });
      setTree(res.entries);
    } catch {
      setTree([]);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
    void loadSessions();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      void loadTree(null);
      return;
    }
    void loadDetail(selectedId);
    void loadTree(selectedId);
  }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedId || !selected || !ACTIVE.has(selected.status)) return;
    const id = window.setInterval(() => {
      void loadDetail(selectedId);
      void loadSessions();
      void loadTree(selectedId);
    }, 1000);
    return () => window.clearInterval(id);
  }, [selectedId, selected?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const launch = async () => {
    const text = goal.trim();
    if (!text) {
      toast("Describe a coding task first");
      return;
    }
    if (busy) return;
    if (status != null && !status.enabled) {
      toast(status.error?.trim() || "Coding agent is disabled");
      return;
    }
    setBusy(true);
    try {
      const created = await api.createCodingSession({ goal: text, mission });
      setSelectedId(created.session.session_id);
      await api.codingTurn(created.session.session_id, { message: text });
      await loadSessions();
      await loadDetail(created.session.session_id);
      await loadTree(created.session.session_id);
      toast("Coding agent launched");
    } catch (err) {
      toast(errMsg(err, "Failed to launch coding agent"));
    } finally {
      setBusy(false);
    }
  };

  const approvePending = async () => {
    if (!selectedId || !detail || busy) return;
    const pending = resolvePending(detail);
    if (!pending) {
      toast("No pending approval");
      return;
    }
    setBusy(true);
    try {
      await api.approveApproval(pending.approvalId);
      await api.codingTurn(selectedId, {
        approvalId: pending.approvalId,
        capabilityId: pending.capabilityId,
      });
      await loadDetail(selectedId);
      await loadTree(selectedId);
      toast("Approved");
    } catch (err) {
      toast(errMsg(err, "Approve failed"));
    } finally {
      setBusy(false);
    }
  };

  const denyPending = async () => {
    if (!selectedId || !detail || busy) return;
    const pending = resolvePending(detail);
    if (!pending) {
      toast("No pending approval");
      return;
    }
    setBusy(true);
    try {
      await api.denyApproval(pending.approvalId);
      await api.codingTurn(selectedId, {
        approvalId: pending.approvalId,
        capabilityId: pending.capabilityId,
      });
      await loadDetail(selectedId);
      await loadTree(selectedId);
      toast("Denied");
    } catch (err) {
      toast(errMsg(err, "Deny failed"));
    } finally {
      setBusy(false);
    }
  };

  const cancelSession = async () => {
    if (!selectedId || busy) return;
    if (!selected || !ACTIVE.has(selected.status)) return;
    setBusy(true);
    try {
      await api.cancelCodingSession(selectedId);
      await loadSessions();
      await loadDetail(selectedId);
      await loadTree(selectedId);
      toast("Session cancelled");
    } catch (err) {
      toast(errMsg(err, "Cancel failed"));
    } finally {
      setBusy(false);
    }
  };

  const terminalText = useMemo(() => {
    const testSteps = steps.filter((s) => s.capability_id === "coding.run_tests");
    const last = testSteps[testSteps.length - 1];
    if (termTab === "tests" || (termTab === "terminal" && last)) {
      const out = stepOutput(last);
      const stdout = String(out.stdout ?? out.output ?? "");
      const stderr = String(out.stderr ?? "");
      const exit = out.exit_code;
      const cmd = out.command != null ? String(out.command) : null;
      if (!stdout && !stderr && !last) {
        return null;
      }
      return { cmd, stdout, stderr, exit, status: last?.status ?? "PENDING" };
    }
    if (termTab === "logs") {
      return {
        cmd: "agent logs",
        stdout: steps
          .map((s) => `[${s.kind}] ${s.capability_id ?? ""} ${s.status}${s.error ? ` — ${s.error}` : ""}`)
          .join("\n"),
        stderr: "",
        exit: 0,
        status: "COMPLETED",
      };
    }
    return null;
  }, [steps, termTab]);

  const filteredPatches = useMemo(() => {
    if (diffTab === "applied") return patches.filter((p) => p.applied);
    if (diffTab === "pending") return patches.filter((p) => !p.applied);
    return patches;
  }, [patches, diffTab]);

  const launchDisabled = busy || (status != null && !status.enabled);
  const launchDisabledReason =
    status != null && !status.enabled
      ? status.error?.trim() || "Coding agent disabled (LEVIATHAN_FEATURE_CODING)"
      : busy
        ? "Launch already in progress"
        : undefined;
  const cancelDisabled =
    busy || !selectedId || !selected || TERMINAL_STATUSES.has(selected.status) || !ACTIVE.has(selected.status);
  const repoLabel = workspaceBasename(selected?.workspace_root);
  const healthLabel =
    status == null
      ? "Status unknown"
      : [
          status.enabled ? "Coding enabled" : "Coding disabled",
          status.agents_enabled ? "Agents enabled" : "Agents disabled",
        ].join(" · ");
  const verificationOutcome = verification?.outcome;
  const memoryNotes =
    neuro?.notes?.length
      ? neuro.notes
      : selected
        ? [
            `Session: ${selected.title || selected.session_id}`,
            selected.user_goal ? `Goal: ${selected.user_goal}` : null,
            `Status: ${selected.status}`,
          ].filter((n): n is string => Boolean(n))
        : ["No session memory yet — notes appear from neuro advisory when available."];

  const contextPct = neuro?.progress != null ? Math.round(Number(neuro.progress) * 100) : null;

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Coding Agent"
      searchPlaceholder="Search code, repositories, agents, documentation, or ask Leviathan..."
      layout="wide"
      pageClass="lv-app--coding"
    >
      <main className="lv-main lv-ca-main">
        <section className="lv-ca-hero" aria-label="Coding Agent">
          <img src={media.codingHero} alt="" width={1400} height={220} />
        </section>


        {status && !status.enabled ? (
          <div className="lv-ca-banner is-warn" role="status">
            Coding agent disabled (LEVIATHAN_FEATURE_CODING). Heuristic AgentRuntime still available if AGENTS is on.
          </div>
        ) : null}
        {loadError ? (
          <div className="lv-ca-banner is-error" role="alert">
            {loadError}
          </div>
        ) : null}

        {/* Row 1: Task Intake · Agent Status · Workspace */}
        <section className="lv-ca-row1">
          <article className="lv-ca-panel">
            <header className="lv-ca-panel-head">
              <h2 className="lv-ca-panel-title">
                <span className="lv-ca-num">1</span> Task Intake
              </h2>
            </header>
            <div className="lv-ca-panel-body">
              <p className="lv-ca-intake-hint">Give the coding agent a task. Be specific for the best results.</p>
              <textarea
                className="lv-ca-intake-area"
                aria-label="Coding task"
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    void launch();
                  }
                }}
              />
              <div className="lv-ca-mission-chips">
                {MISSION_CHIPS.map((chip) => (
                  <button
                    key={chip.mission}
                    type="button"
                    className={`lv-ca-chip${mission === chip.mission ? " is-active" : ""}`}
                    onClick={() => {
                      setMission(chip.mission);
                      setGoal(chip.seed);
                    }}
                  >
                    {chip.label}
                  </button>
                ))}
              </div>
              <div className="lv-ca-intake-meta">
                <div className="lv-ca-field">
                  <label htmlFor="ca-objective">Objective</label>
                  <select
                    id="ca-objective"
                    value={mission}
                    onChange={(e) => setMission(e.target.value as CodingMission)}
                  >
                    {OBJECTIVE_OPTIONS.map((o) => (
                      <option key={o.mission} value={o.mission}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="lv-ca-field">
                  <label htmlFor="ca-repo">Repository</label>
                  <input id="ca-repo" value={repoLabel} readOnly aria-label="Repository" />
                </div>
                <div className="lv-ca-field">
                  <label htmlFor="ca-branch">Branch</label>
                  <input id="ca-branch" value="N/A" readOnly aria-label="Branch" title="Branch is not measured for coding sessions" />
                </div>
              </div>
              <div className="lv-ca-intake-actions">
                <button
                  type="button"
                  className="lv-ca-btn-ghost"
                  disabled
                  title="Attach Files is unavailable — file attachment is not wired for coding sessions"
                >
                  Attach Files
                </button>
                <button
                  type="button"
                  className="lv-ca-btn-ghost"
                  disabled
                  title="Add Context is unavailable — context injection is not wired for coding sessions"
                >
                  Add Context
                </button>
                <button
                  type="button"
                  className="lv-ca-btn-ghost"
                  disabled={cancelDisabled}
                  title={
                    cancelDisabled
                      ? "Cancel available only while session is RUNNING or WAITING_APPROVAL"
                      : "Cancel / stop the coding session"
                  }
                  onClick={() => void cancelSession()}
                >
                  Cancel / Stop
                </button>
                <button
                  type="button"
                  className="lv-ca-btn-launch"
                  disabled={launchDisabled}
                  title={launchDisabledReason}
                  onClick={() => void launch()}
                >
                  ▶ Launch Agent <kbd>⌘↵</kbd>
                </button>
              </div>
            </div>
          </article>

          <article className="lv-ca-panel">
            <header className="lv-ca-panel-head">
              <h2 className="lv-ca-panel-title">
                <span className="lv-ca-num">2</span> Agent Status
              </h2>
              <span className={`lv-ca-status-pill ${statusPillClass(selected?.status)}`}>
                <span className="lv-ca-dot" />
                {statusPillLabel(selected?.status)}
              </span>
            </header>
            <div className="lv-ca-panel-body">
              <dl className="lv-ca-kv">
                <dt>Agent State</dt>
                <dd className={selected?.status === "RUNNING" ? "is-live" : undefined}>
                  {selected?.status === "RUNNING"
                    ? "Executing Task"
                    : selected?.status === "WAITING_APPROVAL"
                      ? "Waiting Approval"
                      : selected?.status ?? "Idle"}
                </dd>
                <dt>Active Model</dt>
                <dd>{selected?.model_id?.trim() || "Router default"}</dd>
                <dt>Approval Mode</dt>
                <dd>Plan &amp; Execute (Ask on Write)</dd>
                <dt>Workspace</dt>
                <dd title={selected?.workspace_root ?? ""}>{selected?.workspace_root ?? "—"}</dd>
                <dt>Sandbox</dt>
                <dd className="is-live">Isolated · gateway-only</dd>
                <dt>Sessions</dt>
                <dd>
                  {sessions.length === 0 ? (
                    codingEmptySessionsCopy(0) ?? "0"
                  ) : (
                    <select
                      aria-label="Select coding session"
                      value={selectedId ?? ""}
                      onChange={(e) => setSelectedId(e.target.value || null)}
                      style={{ maxWidth: "100%", font: "inherit", color: "inherit", background: "transparent" }}
                    >
                      {sessions.map((s) => (
                        <option key={s.session_id} value={s.session_id}>
                          {(s.title || s.session_id).slice(0, 40)} · {s.status}
                        </option>
                      ))}
                    </select>
                  )}
                </dd>
                <dt>Current Phase</dt>
                <dd>
                  {selected?.phase
                    ? String(selected.phase).replace(/_/g, " ")
                    : steps.length
                      ? `${steps[steps.length - 1]?.kind ?? "—"}${steps[steps.length - 1]?.capability_id ? ` · ${steps[steps.length - 1]?.capability_id}` : ""}`
                      : "—"}
                </dd>
                <dt>Task Type</dt>
                <dd>{selected?.task_type ? String(selected.task_type).replace(/_/g, " ") : selected?.mission ?? "—"}</dd>
                <dt>Coding Role</dt>
                <dd>{selected?.coding_role ?? "—"}</dd>
                <dt>Brain Context</dt>
                <dd>
                  {selected?.brain_context
                    ? `${String((selected.brain_context as { status?: string }).status ?? "—")} · k=${String((selected.brain_context as { knowledgeHits?: number }).knowledgeHits ?? 0)}`
                    : "—"}
                </dd>
                <dt>Health</dt>
                <dd>
                  <div className="lv-ca-health">
                    <span title={status?.enabled ? "Coding enabled" : "Coding disabled"} />
                    <span title={status?.agents_enabled ? "Agents enabled" : "Agents disabled"} />
                    <span title={status?.workspace_configured ? "Workspace configured" : "Workspace not configured"} />
                    <small>{healthLabel}</small>
                  </div>
                </dd>
              </dl>
              <div className="lv-ca-progress">
                <div className="lv-ca-progress-label">
                  <span>Context / Neuro</span>
                  <span>{contextPct != null ? `${contextPct}%` : neuro?.enabled === false ? "OFF" : "—"}</span>
                </div>
                <div className="lv-ca-progress-track" aria-hidden="true">
                  <span style={{ width: `${contextPct != null ? Math.min(100, contextPct) : 0}%` }} />
                </div>
              </div>
              {selected?.error ? <p className="lv-ca-intake-hint" style={{ color: "#f87171" }}>{selected.error}</p> : null}
            </div>
          </article>

          <article className="lv-ca-panel">
            <header className="lv-ca-panel-head">
              <h2 className="lv-ca-panel-title">
                <span className="lv-ca-num">3</span> Workspace
              </h2>
              <div className="lv-ca-tabs">
                {(
                  [
                    ["files", "Files"],
                    ["changes", "Changes"],
                    ["notes", "Notes"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    className={`lv-ca-tab${wsTab === id ? " is-active" : ""}`}
                    onClick={() => setWsTab(id)}
                  >
                    {label}
                    {id === "changes" && patches.length > 0 ? (
                      <span className="lv-ca-badge">{patches.length}</span>
                    ) : null}
                  </button>
                ))}
              </div>
            </header>
            <div className="lv-ca-panel-body">
              {wsTab === "files" ? (
                <div className="lv-ca-ws-split">
                  <div className="lv-ca-tree" aria-label="Workspace tree">
                    {tree.length === 0 ? (
                      <div className="lv-ca-empty">No workspace entries</div>
                    ) : (
                      tree.map((entry) => (
                        <div key={entry.path} className={`lv-ca-tree-item${entry.type === "dir" ? " is-dir" : ""}`}>
                          <span>{entry.type === "dir" ? "📁" : "📄"}</span>
                          <span>{entry.path}</span>
                          {entry.mark ? (
                            <span className={`lv-ca-mark is-${entry.mark.toLowerCase()}`}>{entry.mark}</span>
                          ) : null}
                        </div>
                      ))
                    )}
                  </div>
                  <div className="lv-ca-recent" aria-label="Recent files">
                    <div style={{ marginBottom: 6, color: "var(--lv-text-muted)", fontSize: 10, letterSpacing: "0.1em" }}>
                      RECENT / PATCHES
                    </div>
                    {patches.length === 0 ? (
                      <div className="lv-ca-empty" style={{ padding: 8 }}>
                        No patches yet
                      </div>
                    ) : (
                      patches.slice(0, 8).map((p) => (
                        <div key={p.patch_id} className="lv-ca-tree-item">
                          <span>📄</span>
                          <span>{p.path}</span>
                          <span className={`lv-ca-mark ${p.applied ? "is-a" : "is-m"}`}>{p.applied ? "A" : "M"}</span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              ) : wsTab === "changes" ? (
                <div className="lv-ca-tree">
                  {patches.length === 0 ? (
                    <div className="lv-ca-empty">No changes</div>
                  ) : (
                    patches.map((p) => {
                      const c = countDiffLines(p.diff_unified);
                      return (
                        <div key={p.patch_id} className="lv-ca-tree-item">
                          <span>{p.path}</span>
                          <span className="lv-ca-mark is-a" style={{ marginLeft: "auto" }}>
                            +{c.plus}
                          </span>
                          <span className="lv-ca-mark is-m">-{c.minus}</span>
                        </div>
                      );
                    })
                  )}
                </div>
              ) : (
                <div className="lv-ca-empty">Session notes appear when the agent records them</div>
              )}
              <div className="lv-ca-ws-info">
                <div>
                  Path <strong>{selected?.workspace_root ?? "—"}</strong>
                </div>
                <div>
                  Files <strong>{tree.length || "—"}</strong>
                </div>
                <div>
                  HADES <strong>excluded</strong>
                </div>
                <div>
                  Gateway <strong>{status?.truth?.gateway_only ? "only" : "—"}</strong>
                </div>
              </div>
            </div>
          </article>
        </section>

        {/* Row 2: Timeline · Terminal · Diff · Review */}
        <section className="lv-ca-row2">
          <article className="lv-ca-panel">
            <header className="lv-ca-panel-head">
              <h2 className="lv-ca-panel-title">
                <span className="lv-ca-num">4</span> Execution Timeline
              </h2>
              {selected && ACTIVE.has(selected.status) ? (
                <span className="lv-ca-status-pill">
                  <span className="lv-ca-dot" /> Live
                </span>
              ) : null}
            </header>
            <div className="lv-ca-panel-body">
              {steps.length === 0 ? (
                <div className="lv-ca-empty">{codingEmptySessionsCopy(sessions.length) ?? "No steps yet"}</div>
              ) : (
                <ol className="lv-ca-timeline">
                  {steps.map((step, idx) => {
                    const done = step.status === "COMPLETED" || step.status === "SKIPPED";
                    const active = step.status === "RUNNING" || (idx === steps.length - 1 && ACTIVE.has(selected?.status ?? ""));
                    const pending = step.status === "PENDING";
                    return (
                      <li
                        key={step.step_id}
                        className={done ? "is-done" : active ? "is-active" : pending ? "is-pending" : ""}
                      >
                        <span className="lv-ca-tl-time">{formatTime(step.created_at)}</span>
                        <span className="lv-ca-tl-text">
                          {step.kind}
                          {step.capability_id ? ` · ${step.capability_id}` : ""} · {step.status}
                        </span>
                        {step.error ? <span className="lv-ca-tl-text" style={{ color: "#f87171" }}>{step.error}</span> : null}
                      </li>
                    );
                  })}
                </ol>
              )}
            </div>
          </article>

          <article className="lv-ca-panel">
            <header className="lv-ca-panel-head">
              <h2 className="lv-ca-panel-title">
                <span className="lv-ca-num">5</span> Terminal / Output
              </h2>
              <div className="lv-ca-tabs">
                {(
                  [
                    ["terminal", "Terminal"],
                    ["logs", "Agent Logs"],
                    ["tests", "Test Output"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    className={`lv-ca-tab${termTab === id ? " is-active" : ""}`}
                    onClick={() => setTermTab(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </header>
            <div className="lv-ca-panel-body">
              <div className="lv-ca-terminal" aria-label="Terminal output">
                {terminalText ? (
                  <>
                    {terminalText.cmd ? <div className="lv-ca-cmd">$ {terminalText.cmd}</div> : null}
                    {terminalText.stdout ? <div>{terminalText.stdout}</div> : null}
                    {terminalText.stderr ? <div className="lv-ca-fail">{terminalText.stderr}</div> : null}
                    {terminalText.exit != null ? (
                      <div className={Number(terminalText.exit) === 0 ? "lv-ca-ok" : "lv-ca-fail"}>
                        exit {String(terminalText.exit)} · {terminalText.status}
                      </div>
                    ) : terminalText.status ? (
                      <div className="lv-ca-dim">{terminalText.status}</div>
                    ) : null}
                  </>
                ) : (
                  <span className="lv-ca-dim">No command output yet. Runs appear when coding.run_tests executes.</span>
                )}
              </div>
            </div>
          </article>

          <article className="lv-ca-panel">
            <header className="lv-ca-panel-head">
              <h2 className="lv-ca-panel-title">
                <span className="lv-ca-num">6</span> Diff / Changes
              </h2>
              <div className="lv-ca-tabs">
                {(
                  [
                    ["applied", `Applied (${patches.filter((p) => p.applied).length})`],
                    ["pending", `Pending (${patches.filter((p) => !p.applied).length})`],
                    ["all", `All Patches (${patches.length})`],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    className={`lv-ca-tab${diffTab === id ? " is-active" : ""}`}
                    onClick={() => setDiffTab(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </header>
            <div className="lv-ca-panel-body">
              <div className="lv-ca-diff-files">
                {filteredPatches.length === 0 ? (
                  <div className="lv-ca-empty" style={{ padding: 8 }}>
                    No diffs
                  </div>
                ) : (
                  filteredPatches.map((p) => {
                      const c = countDiffLines(p.diff_unified);
                      return (
                        <button
                          key={p.patch_id}
                          type="button"
                          className={`lv-ca-diff-file${selectedPatch?.patch_id === p.patch_id ? " is-active" : ""}`}
                          onClick={() => setSelectedPatchId(p.patch_id)}
                        >
                          <span>{p.path}</span>
                          <span className="lv-ca-plus">+{c.plus}</span>
                          <span className="lv-ca-minus">-{c.minus}</span>
                        </button>
                      );
                    })
                )}
              </div>
              <div className="lv-ca-diff-view" aria-label="Unified diff">
                {selectedPatch && filteredPatches.some((p) => p.patch_id === selectedPatch.patch_id) ? (
                  renderDiff(selectedPatch.diff_unified).map((line, i) => (
                    <div key={`${selectedPatch.patch_id}-${i}`} className={line.cls}>
                      {line.text || " "}
                    </div>
                  ))
                ) : (
                  <span className="lv-ca-dim">Select a patch to inspect the unified diff.</span>
                )}
              </div>
              <div className="lv-ca-commit-row">
                <input
                  value=""
                  readOnly
                  disabled
                  placeholder="Commit unavailable"
                  aria-label="Commit message"
                  title="Commit Changes is unavailable — git commit is not wired from this page"
                />
                <button
                  type="button"
                  className="lv-ca-btn-gold"
                  disabled
                  title="Commit Changes is unavailable — git commit is not wired from this page"
                >
                  Commit Changes
                </button>
              </div>
            </div>
          </article>

          <article className="lv-ca-panel">
            <header className="lv-ca-panel-head">
              <h2 className="lv-ca-panel-title">
                <span className="lv-ca-num">7</span> Review / Approval
              </h2>
              <div className="lv-ca-tabs">
                {(
                  [
                    ["summary", "Summary"],
                    ["tests", "Test Results"],
                    ["review", "Code Review"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    className={`lv-ca-tab${reviewTab === id ? " is-active" : ""}`}
                    onClick={() => setReviewTab(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </header>
            <div className="lv-ca-panel-body">
              {reviewTab === "summary" ? (
                <>
                  <p className="lv-ca-intake-hint" style={{ color: "var(--lv-text)" }}>
                    {verificationOutcome
                      ? `Verification ${verificationOutcome}`
                      : verification?.verification_id
                        ? `Verification recorded (${verification.verification_id}) — outcome unmeasured`
                        : selected?.status === "WAITING_APPROVAL"
                          ? "Awaiting operator approval for gated WRITE/EXECUTE."
                          : selected
                            ? `Session ${selected.status}`
                            : "No active review."}
                  </p>
                  <div className="lv-ca-review-stat">
                    <article>
                      <strong>{patchStats.files}</strong>
                      <span>Files Changed</span>
                    </article>
                    <article>
                      <strong style={{ color: "#34d399" }}>+{patchStats.plus}</strong>
                      <span>Lines Added</span>
                    </article>
                    <article>
                      <strong style={{ color: "#f87171" }}>−{patchStats.minus}</strong>
                      <span>Lines Removed</span>
                    </article>
                  </div>
                  <ul className="lv-ca-review-notes">
                    <li>
                      <span className="ok">✓</span> Shared gateway only — no private shell
                    </li>
                    <li>
                      <span className="ok">✓</span> HADES paths excluded
                    </li>
                    <li>
                      <span className={verificationOutcome === "PASSED" ? "ok" : "warn"}>
                        {verificationOutcome === "PASSED" ? "✓" : "!"}
                      </span>
                      {verificationOutcome
                        ? `Evidence ${verificationOutcome}`
                        : verification?.verification_id
                          ? "Verification id present — outcome unmeasured"
                          : "Unmeasured until VerificationEngine reports"}
                    </li>
                  </ul>
                </>
              ) : reviewTab === "tests" ? (
                <div className="lv-ca-empty">
                  {steps.some((s) => s.capability_id === "coding.run_tests")
                    ? "See Terminal → Test Output for captured exit codes"
                    : "No coding.run_tests observation yet"}
                </div>
              ) : (
                <ul className="lv-ca-review-notes">
                  {(neuro?.notes ?? ["Neuro advisory rail — signals never authorize writes"]).map((n) => (
                    <li key={n}>
                      <span className="warn">•</span> {n}
                    </li>
                  ))}
                </ul>
              )}
              <div className="lv-ca-review-actions">
                <button
                  type="button"
                  className="lv-ca-btn-approve"
                  disabled={busy || selected?.status !== "WAITING_APPROVAL"}
                  onClick={() => void approvePending()}
                >
                  Approve Changes
                </button>
                <button
                  type="button"
                  className="lv-ca-btn-secondary"
                  disabled={busy || selected?.status !== "WAITING_APPROVAL"}
                  onClick={() => void denyPending()}
                >
                  Request Revision / Deny
                </button>
                <button
                  type="button"
                  className="lv-ca-btn-ghost"
                  disabled={cancelDisabled}
                  title={
                    cancelDisabled
                      ? "Cancel available only while session is RUNNING or WAITING_APPROVAL"
                      : "Cancel / stop the coding session"
                  }
                  onClick={() => void cancelSession()}
                >
                  Cancel / Stop
                </button>
              </div>
            </div>
          </article>
        </section>

        {/* Row 3: Memory / Context */}
        <section className="lv-ca-row3">
          <article className="lv-ca-panel">
            <header className="lv-ca-panel-head">
              <h2 className="lv-ca-panel-title">
                <span className="lv-ca-num">8</span> Memory / Context
              </h2>
            </header>
            <div className="lv-ca-panel-body">
              <div className="lv-ca-memory-grid">
                <div className="lv-ca-memory-card">
                  <h4>Session Memory</h4>
                  <p>{memoryNotes[0]}</p>
                  <small>Read-only · from session / neuro</small>
                </div>
                <div className="lv-ca-memory-card">
                  <h4>Neuro Advisory</h4>
                  <p>
                    {neuro?.enabled
                      ? `consistency=${neuro.consistency ?? "—"} progress=${neuro.progress ?? "—"} grounding=${neuro.grounding ?? "—"}`
                      : "Neuro feature flag OFF — coding still works."}
                  </p>
                  <small>Advisory only — never authority</small>
                </div>
                <div className="lv-ca-memory-card">
                  <h4>Notes</h4>
                  <p>
                    {memoryNotes.slice(1).join(" · ") ||
                      (neuro?.notes?.length ? neuro.notes.join(" · ") : "No additional notes")}
                  </p>
                  <small>Not an online memory store</small>
                </div>
                <div className="lv-ca-memory-card">
                  <h4>Catalog</h4>
                  <p>
                    {(status?.catalog_ids ?? []).slice(0, 6).join(", ") || "Capabilities load with coding status"}
                    {(status?.catalog_ids?.length ?? 0) > 6 ? "…" : ""}
                  </p>
                  <small>Gateway-backed</small>
                </div>
              </div>
              <div className="lv-ca-memory-foot">
                <button
                  type="button"
                  className="lv-ca-btn-ghost"
                  disabled
                  title="Add to Memory is unavailable — MemoryStore writes are not wired from this page"
                >
                  + Add to Memory
                </button>
              </div>
            </div>
          </article>
        </section>
      </main>
    </AppShell>
  );
}
