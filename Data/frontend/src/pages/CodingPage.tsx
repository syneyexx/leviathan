import { useCallback, useEffect, useMemo, useState } from "react";
import { media } from "../assets/media";
import { api, ApiError } from "../api/client";
import { SubMenu } from "../components/SubMenu";
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

export function CodingPage() {
  const toast = useAppToast();
  const [status, setStatus] = useState<CodingStatusResponse | null>(null);
  const [sessions, setSessions] = useState<CodingSession[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CodingSessionDetail | null>(null);
  const [tree, setTree] = useState<CodingWorkspaceEntry[]>([]);
  const [wsTab, setWsTab] = useState<"files" | "changes" | "notes">("files");
  const [termTab, setTermTab] = useState<"terminal" | "logs" | "tests" | "lsp">("terminal");
  const [diffTab, setDiffTab] = useState<"staged" | "modified" | "all">("modified");
  const [reviewTab, setReviewTab] = useState<"summary" | "tests" | "review">("summary");
  const [memTab, setMemTab] = useState<"memory" | "rules" | "instructions" | "constraints">("memory");
  const [selectedPatchId, setSelectedPatchId] = useState<string | null>(null);
  const [goal, setGoal] = useState(
    "Implement a risk analysis and position sizing engine for our trading system.\n\nRequirements:\n- Support multiple risk models\n- Position sizing constraints\n- Unit tests\n- Update documentation",
  );
  const [mission, setMission] = useState<CodingMission>("GENERIC");
  const [commitMsg, setCommitMsg] = useState("");
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

  const loadTree = useCallback(async () => {
    try {
      const res = await api.codingWorkspaceTree({ recursive: false });
      setTree(res.entries);
    } catch {
      setTree([]);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
    void loadSessions();
    void loadTree();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    void loadDetail(selectedId);
  }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedId || !selected || !ACTIVE.has(selected.status)) return;
    const id = window.setInterval(() => {
      void loadDetail(selectedId);
      void loadSessions();
    }, 1000);
    return () => window.clearInterval(id);
  }, [selectedId, selected?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const launch = async () => {
    const text = goal.trim();
    if (!text) {
      toast("Describe a coding task first");
      return;
    }
    setBusy(true);
    try {
      const created = await api.createCodingSession({ goal: text, mission });
      setSelectedId(created.session.session_id);
      await api.codingTurn(created.session.session_id, { message: text });
      await loadSessions();
      await loadDetail(created.session.session_id);
      toast("Coding agent launched");
    } catch (err) {
      toast(errMsg(err, "Failed to launch coding agent"));
    } finally {
      setBusy(false);
    }
  };

  const approvePending = async () => {
    if (!selectedId || !detail) return;
    const pending = detail.steps.find((s) => s.status === "PENDING" || s.kind === "WAIT_APPROVAL");
    const approvalId = pending?.approval_id;
    if (!approvalId) {
      toast("No pending approval");
      return;
    }
    setBusy(true);
    try {
      await api.approveApproval(approvalId);
      await api.codingTurn(selectedId, { approval_id: approvalId, capability_id: pending?.capability_id ?? undefined });
      await loadDetail(selectedId);
      toast("Approved");
    } catch (err) {
      toast(errMsg(err, "Approve failed"));
    } finally {
      setBusy(false);
    }
  };

  const denyPending = async () => {
    if (!selectedId || !detail) return;
    const pending = detail.steps.find((s) => s.approval_id && (s.status === "PENDING" || s.kind === "WAIT_APPROVAL"));
    if (!pending?.approval_id) {
      toast("No pending approval");
      return;
    }
    setBusy(true);
    try {
      await api.denyApproval(pending.approval_id);
      await loadDetail(selectedId);
      toast("Denied");
    } catch (err) {
      toast(errMsg(err, "Deny failed"));
    } finally {
      setBusy(false);
    }
  };

  const terminalText = useMemo(() => {
    const testSteps = steps.filter((s) => s.capability_id === "coding.run_tests");
    const last = testSteps[testSteps.length - 1];
    if (termTab === "tests" || (termTab === "terminal" && last)) {
      const out = (last?.output_json ?? {}) as Record<string, unknown>;
      const stdout = String(out.stdout ?? out.output ?? "");
      const stderr = String(out.stderr ?? "");
      const exit = out.exit_code;
      const cmd = String(out.command ?? "python -m pytest -q");
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

        <SubMenu />

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
                  <input id="ca-repo" value="codingworkspace" readOnly aria-label="Repository" />
                </div>
                <div className="lv-ca-field">
                  <label htmlFor="ca-branch">Branch</label>
                  <input id="ca-branch" value="workspace" readOnly aria-label="Branch" />
                </div>
              </div>
              <div className="lv-ca-intake-actions">
                <button type="button" className="lv-ca-btn-ghost" onClick={() => toast("Attach files — coming via approvals")}>
                  Attach Files
                </button>
                <button type="button" className="lv-ca-btn-ghost" onClick={() => toast("Add context — use knowledge.search via agent")}>
                  Add Context
                </button>
                <button
                  type="button"
                  className="lv-ca-btn-launch"
                  disabled={busy || (status != null && !status.enabled)}
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
                <dd>{selected?.model_id ?? "—"}</dd>
                <dt>Approval Mode</dt>
                <dd>Plan &amp; Execute (Ask on Write)</dd>
                <dt>Workspace</dt>
                <dd title={selected?.workspace_root ?? ""}>{selected?.workspace_root ?? "—"}</dd>
                <dt>Sandbox</dt>
                <dd className="is-live">Isolated · gateway-only</dd>
                <dt>Sessions</dt>
                <dd>
                  {sessions.length} total
                  {codingEmptySessionsCopy(sessions.length) ? " · empty" : ""}
                </dd>
                <dt>Current Phase</dt>
                <dd>
                  {steps.length
                    ? `${steps[steps.length - 1]?.kind ?? "—"}${steps[steps.length - 1]?.capability_id ? ` · ${steps[steps.length - 1]?.capability_id}` : ""}`
                    : "—"}
                </dd>
                <dt>Health</dt>
                <dd>
                  <div className="lv-ca-health">
                    <span />
                    <span />
                    <span />
                    <small>{status?.enabled ? "Ready" : "Disabled"}</small>
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
                    ["lsp", "LSP"],
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
                {termTab === "lsp" ? (
                  <span className="lv-ca-dim">LSP output is not wired — honest UNMEASURED.</span>
                ) : terminalText ? (
                  <>
                    <div className="lv-ca-cmd">$ {terminalText.cmd}</div>
                    {terminalText.stdout ? <div>{terminalText.stdout}</div> : null}
                    {terminalText.stderr ? <div className="lv-ca-fail">{terminalText.stderr}</div> : null}
                    {terminalText.exit != null ? (
                      <div className={Number(terminalText.exit) === 0 ? "lv-ca-ok" : "lv-ca-fail"}>
                        exit {String(terminalText.exit)} · {terminalText.status}
                      </div>
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
                    ["staged", `Staged (${patches.filter((p) => p.applied).length})`],
                    ["modified", `Modified (${patches.length})`],
                    ["all", "All Changes"],
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
                {patches.length === 0 ? (
                  <div className="lv-ca-empty" style={{ padding: 8 }}>
                    No diffs
                  </div>
                ) : (
                  patches
                    .filter((p) => (diffTab === "staged" ? p.applied : true))
                    .map((p) => {
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
                {selectedPatch ? (
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
                  value={commitMsg}
                  onChange={(e) => setCommitMsg(e.target.value)}
                  placeholder="Commit message…"
                  aria-label="Commit message"
                />
                <button
                  type="button"
                  className="lv-ca-btn-gold"
                  disabled={!commitMsg.trim() || !selected}
                  onClick={() => toast("git.commit requires explicit operator request + approval")}
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
                    {verification
                      ? `Verification ${verification.outcome}`
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
                      <span className={verification?.outcome === "PASSED" ? "ok" : "warn"}>
                        {verification?.outcome === "PASSED" ? "✓" : "!"}
                      </span>
                      {verification
                        ? `Evidence ${verification.outcome}`
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
              <div className="lv-ca-tabs">
                {(
                  [
                    ["memory", "Agent Memory"],
                    ["rules", "Project Rules"],
                    ["instructions", "Reusable Instructions"],
                    ["constraints", "Constraints"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    className={`lv-ca-tab${memTab === id ? " is-active" : ""}`}
                    onClick={() => setMemTab(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </header>
            <div className="lv-ca-panel-body">
              <div className="lv-ca-memory-grid">
                <div className="lv-ca-memory-card">
                  <h4>Flight Rules</h4>
                  <p>Model output ≠ evidence. WRITE requires approval. Unmeasured ≠ passed.</p>
                  <small>Always on</small>
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
                  <h4>Residual</h4>
                  <p>
                    {status?.residual_supported || neuro?.residual_supported
                      ? "Residual port supported"
                      : "Residual unsupported — honest provenance, no fake inject"}
                  </p>
                  <small>Degrades cleanly</small>
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
                <button type="button" className="lv-ca-btn-ghost" onClick={() => toast("Memory writes go through MemoryStore (trust≠model_output)")}>
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
