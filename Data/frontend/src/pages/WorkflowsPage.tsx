import { useCallback, useEffect, useMemo, useState } from "react";
import { tradingHeroes } from "../assets/tradingAssets";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type {
  CapabilityListItem,
  ScheduleRecord,
  WorkflowRecord,
  WorkflowState,
  WorkflowStepDef,
  WorkflowStepResult,
} from "../types/api";
import { Panel, TradingHero } from "./trading/shared";

type StateFilter = "All" | WorkflowState;

const STATE_FILTERS: StateFilter[] = ["All", "CREATED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"];

type DraftStep = {
  key: string;
  capability_id: string;
  argumentsText: string;
};

type WorkflowCreateStep = {
  step_id: string;
  capability_id: string;
  arguments: Record<string, unknown>;
};

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function formatTs(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString();
  } catch {
    return value;
  }
}

function statePillClass(state: string): string {
  const s = state.toUpperCase();
  if (s === "COMPLETED") return " is-live";
  if (s === "FAILED" || s === "CANCELLED") return " is-bad";
  if (s === "RUNNING") return " is-warn";
  return "";
}

function canRun(state: string): boolean {
  return state === "CREATED" || state === "RUNNING";
}

function canCancel(state: string): boolean {
  return state === "CREATED" || state === "RUNNING";
}

function newDraftStep(capabilityId = ""): DraftStep {
  return {
    key: `step-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    capability_id: capabilityId,
    argumentsText: "{}",
  };
}

function parseArguments(text: string): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const raw = text.trim() || "{}";
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false, error: "Step arguments must be a JSON object" };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch {
    return { ok: false, error: "Invalid JSON in step arguments" };
  }
}

function capabilityLabel(cap: CapabilityListItem): string {
  return cap.name ? `${cap.id} — ${cap.name}` : cap.id;
}

function intervalLabel(seconds: number): string {
  if (seconds < 60) return `Every ${seconds}s`;
  if (seconds % 3600 === 0) return `Every ${seconds / 3600}h`;
  if (seconds % 60 === 0) return `Every ${seconds / 60}m`;
  return `Every ${seconds}s`;
}

export function WorkflowsPage() {
  const toast = useAppToast();

  const [workflows, setWorkflows] = useState<WorkflowRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [filter, setFilter] = useState<StateFilter>("All");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);

  const [capabilities, setCapabilities] = useState<CapabilityListItem[]>([]);
  const [schedules, setSchedules] = useState<ScheduleRecord[]>([]);
  const [schedulesError, setSchedulesError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [createName, setCreateName] = useState("");
  const [draftSteps, setDraftSteps] = useState<DraftStep[]>(() => [newDraftStep()]);

  const [scheduleName, setScheduleName] = useState("");
  const [scheduleTarget, setScheduleTarget] = useState("");
  const [scheduleInterval, setScheduleInterval] = useState("3600");

  const loadWorkflows = useCallback(async (preferId?: string | null) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listWorkflows(200);
      const list = res.workflows ?? [];
      setWorkflows(list);
      const keep = preferId ?? selectedId;
      if (list.length === 0) {
        setSelectedId(null);
      } else if (!keep || !list.some((w) => w.workflow_id === keep)) {
        setSelectedId(list[0].workflow_id);
      } else {
        setSelectedId(keep);
      }
    } catch (err) {
      setError(errMsg(err, "Failed to load workflows"));
      setWorkflows([]);
      setSelectedId(null);
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  const loadSchedules = useCallback(async () => {
    try {
      const res = await api.listSchedules({ limit: 100 });
      setSchedules(res.schedules ?? []);
      setSchedulesError(null);
    } catch (err) {
      setSchedules([]);
      setSchedulesError(errMsg(err, "Failed to load schedules"));
    }
  }, []);

  useEffect(() => {
    void loadWorkflows();
    void loadSchedules();
    void api.listCapabilities({ limit: 500 }).then(
      (res) => setCapabilities(res.capabilities ?? []),
      () => setCapabilities([]),
    );
    // Initial load only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selected = useMemo(
    () => workflows.find((w) => w.workflow_id === selectedId) ?? null,
    [workflows, selectedId],
  );

  useEffect(() => {
    if (!selected) {
      setSelectedStepId(null);
      return;
    }
    const steps = selected.steps ?? [];
    if (!steps.length) {
      setSelectedStepId(null);
      return;
    }
    if (!selectedStepId || !steps.some((s) => s.step_id === selectedStepId)) {
      setSelectedStepId(steps[0].step_id);
    }
  }, [selected, selectedStepId]);

  const filtered = useMemo(() => {
    return workflows.filter((w) => {
      if (filter !== "All" && String(w.state).toUpperCase() !== filter) return false;
      if (!query.trim()) return true;
      const hay = [w.workflow_id, w.name, w.state, w.error, ...(w.steps ?? []).map((s) => s.capability_id)]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(query.trim().toLowerCase());
    });
  }, [workflows, filter, query]);

  const selectedStep: WorkflowStepDef | null = useMemo(() => {
    if (!selected || !selectedStepId) return null;
    return selected.steps?.find((s) => s.step_id === selectedStepId) ?? null;
  }, [selected, selectedStepId]);

  const selectedStepResult: WorkflowStepResult | null = useMemo(() => {
    if (!selected || !selectedStepId) return null;
    const results = selected.step_results ?? [];
    return results.find((r) => r.step_id === selectedStepId) ?? null;
  }, [selected, selectedStepId]);

  const upsertWorkflow = (record: WorkflowRecord) => {
    setWorkflows((prev) => {
      const idx = prev.findIndex((w) => w.workflow_id === record.workflow_id);
      if (idx < 0) return [record, ...prev];
      const next = [...prev];
      next[idx] = record;
      return next;
    });
  };

  async function refreshSelected() {
    if (!selectedId) return;
    setBusy(true);
    try {
      const res = await api.getWorkflow(selectedId);
      upsertWorkflow(res.workflow);
      toast(`Refreshed · ${res.workflow.state}`);
    } catch (err) {
      toast(errMsg(err, "Refresh failed"));
    } finally {
      setBusy(false);
    }
  }

  async function onRun() {
    if (!selected) return;
    setBusy(true);
    try {
      const res = await api.runWorkflow(selected.workflow_id);
      upsertWorkflow(res.workflow);
      const state = String(res.workflow.state).toUpperCase();
      if (state === "FAILED") {
        toast(res.workflow.error || "Workflow failed");
      } else {
        toast(`Run finished · ${res.workflow.state}`);
      }
    } catch (err) {
      toast(errMsg(err, "Run failed"));
    } finally {
      setBusy(false);
    }
  }

  async function onCancel() {
    if (!selected) return;
    setBusy(true);
    try {
      const res = await api.cancelWorkflow(selected.workflow_id);
      upsertWorkflow(res.workflow);
      toast(`Cancelled · ${res.workflow.state}`);
    } catch (err) {
      toast(errMsg(err, "Cancel failed"));
    } finally {
      setBusy(false);
    }
  }

  async function onCreate() {
    const name = createName.trim();
    if (!name) {
      toast("Name is required");
      return;
    }
    if (!draftSteps.length) {
      toast("Add at least one step");
      return;
    }
    const steps: WorkflowCreateStep[] = [];
    for (let i = 0; i < draftSteps.length; i++) {
      const draft = draftSteps[i];
      const cap = draft.capability_id.trim();
      if (!cap) {
        toast(`Step ${i + 1} needs a capability_id`);
        return;
      }
      const args = parseArguments(draft.argumentsText);
      if (!args.ok) {
        toast(`Step ${i + 1}: ${args.error}`);
        return;
      }
      steps.push({
        step_id: `step-${i}`,
        capability_id: cap,
        arguments: args.value,
      });
    }

    setBusy(true);
    try {
      const res = await api.createWorkflow({ name, steps });
      upsertWorkflow(res.workflow);
      setSelectedId(res.workflow.workflow_id);
      setCreateName("");
      setDraftSteps([newDraftStep(capabilities[0]?.id ?? "")]);
      setShowCreate(false);
      toast(`Created · ${res.workflow.name}`);
      await loadWorkflows(res.workflow.workflow_id);
    } catch (err) {
      toast(errMsg(err, "Create failed"));
    } finally {
      setBusy(false);
    }
  }

  async function onCreateSchedule() {
    const name = scheduleName.trim();
    const target = scheduleTarget.trim() || selected?.workflow_id || "";
    const interval = Number(scheduleInterval);
    if (!name || !target) {
      toast("Schedule name and target workflow id required");
      return;
    }
    if (!Number.isFinite(interval) || interval < 1) {
      toast("Interval must be a positive number of seconds");
      return;
    }
    setBusy(true);
    try {
      const res = await api.createSchedule({
        name,
        target_kind: "WORKFLOW",
        target_ref: target,
        interval_seconds: interval,
      });
      setSchedules((prev) => [res.schedule, ...prev]);
      setScheduleName("");
      toast(`Schedule created · ${res.schedule.name}`);
    } catch (err) {
      toast(errMsg(err, "Schedule create failed"));
    } finally {
      setBusy(false);
    }
  }

  async function onToggleSchedule(schedule: ScheduleRecord) {
    setBusy(true);
    try {
      const res =
        String(schedule.status).toUpperCase() === "ACTIVE"
          ? await api.pauseSchedule(schedule.schedule_id)
          : await api.resumeSchedule(schedule.schedule_id);
      setSchedules((prev) =>
        prev.map((s) => (s.schedule_id === res.schedule.schedule_id ? res.schedule : s)),
      );
      toast(`${res.schedule.name} · ${res.schedule.status}`);
    } catch (err) {
      toast(errMsg(err, "Schedule update failed"));
    } finally {
      setBusy(false);
    }
  }

  const counts = useMemo(() => {
    const byState = new Map<string, number>();
    for (const w of workflows) {
      const key = String(w.state).toUpperCase();
      byState.set(key, (byState.get(key) ?? 0) + 1);
    }
    return byState;
  }, [workflows]);

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Workflows Mode"
      searchPlaceholder="Search workflows, capabilities, schedules..."
      systemItems={["SYSTEMS OPERATIONAL", "LLM", "Neural", "Memory", "Tools"]}
      layout="wide"
      pageClass="lv-app--trading"
    >
      <main className="lv-main lv-tp-main">
        <TradingHero
          title="WORKFLOWS"
          kicker="DESIGN. AUTOMATE. ORCHESTRATE."
          quote="“Turn complex ideas into effortless execution.” — LEVIATHAN"
          image={tradingHeroes.workflows}
          rails={["AUTOMATE", "AMPLIFY", "ORCHESTRATE", "SCALE", "BEYOND"]}
          objectPosition="center 35%"
        />

        <section className="lv-wf-toolbar" aria-label="Workflow filters">
          <div className="lv-tp-tabs">
            {STATE_FILTERS.map((f) => (
              <button
                key={f}
                type="button"
                className={`lv-tp-chip${filter === f ? " is-active" : ""}`}
                onClick={() => setFilter(f)}
              >
                {f === "All" ? `All (${workflows.length})` : `${f} (${counts.get(f) ?? 0})`}
              </button>
            ))}
          </div>
          <input
            className="lv-tp-input grow"
            type="search"
            placeholder="Search workflows..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button
            type="button"
            className="lv-tp-btn"
            disabled={busy || loading}
            onClick={() => void loadWorkflows(selectedId)}
          >
            Refresh
          </button>
          <button
            type="button"
            className="lv-tp-btn lv-tp-btn--gold"
            onClick={() => {
              setShowCreate(true);
              if (!draftSteps[0]?.capability_id && capabilities[0]?.id) {
                setDraftSteps([newDraftStep(capabilities[0].id)]);
              }
            }}
          >
            + New Workflow
          </button>
        </section>

        {error ? (
          <p className="lv-tp-muted" role="alert" style={{ margin: "8px 0 0" }}>
            {error}
          </p>
        ) : null}

        <section className="lv-wf-workspace">
          <Panel title="Workflows">
            {loading ? (
              <p className="lv-tp-muted">Loading workflows…</p>
            ) : filtered.length === 0 ? (
              <div className="lv-wf-empty">
                <strong style={{ color: "var(--lv-text-bright)" }}>NO WORKFLOWS</strong>
                <p className="lv-tp-muted" style={{ marginTop: 6 }}>
                  {workflows.length === 0
                    ? "Create an ordered capability sequence to get started."
                    : "No workflows match this filter."}
                </p>
                {workflows.length === 0 ? (
                  <button
                    type="button"
                    className="lv-tp-btn lv-tp-btn--gold"
                    style={{ marginTop: 10 }}
                    onClick={() => setShowCreate(true)}
                  >
                    Create workflow
                  </button>
                ) : null}
              </div>
            ) : (
              <div className="lv-wf-trigger-list">
                {filtered.map((w) => (
                  <button
                    key={w.workflow_id}
                    type="button"
                    className={`lv-wf-trigger${selectedId === w.workflow_id ? " is-active" : ""}`}
                    onClick={() => setSelectedId(w.workflow_id)}
                  >
                    <span
                      className="ico"
                      style={{
                        background: "rgba(214,169,87,0.12)",
                        color: "var(--lv-gold-pale)",
                        border: "1px solid rgba(214,169,87,0.35)",
                      }}
                    >
                      {(w.name || "?").slice(0, 1).toUpperCase()}
                    </span>
                    <span>
                      <strong>{w.name}</strong>
                      <span>
                        {w.state} · {dash(w.steps?.length ?? 0)} steps
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </Panel>

          <Panel>
            {!selected ? (
              <div className="lv-wf-empty" style={{ padding: 16 }}>
                <strong style={{ color: "var(--lv-text-bright)" }}>Select a workflow</strong>
                <p className="lv-tp-muted" style={{ marginTop: 6 }}>
                  Ordered capability steps run through the shared Execution Gateway. There is no visual DAG editor yet.
                </p>
              </div>
            ) : (
              <>
                <div className="lv-wf-canvas-head">
                  <div>
                    <h2>{selected.name}</h2>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4, flexWrap: "wrap" }}>
                      <span className={`lv-tp-pill${statePillClass(String(selected.state))}`}>
                        {selected.state}
                      </span>
                      <span className="lv-tp-muted">{selected.workflow_id}</span>
                      <span className="lv-tp-muted">Updated {formatTs(selected.updated_at)}</span>
                    </div>
                    {selected.error ? (
                      <p className="lv-tp-muted" style={{ color: "#f87171", marginTop: 8 }}>
                        {selected.error}
                      </p>
                    ) : null}
                  </div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <button type="button" className="lv-tp-btn" disabled={busy} onClick={() => void refreshSelected()}>
                      Refresh
                    </button>
                    <button
                      type="button"
                      className="lv-tp-btn lv-tp-btn--accent"
                      disabled={busy || !canRun(String(selected.state))}
                      onClick={() => void onRun()}
                    >
                      Run
                    </button>
                    <button
                      type="button"
                      className="lv-tp-btn"
                      disabled={busy || !canCancel(String(selected.state))}
                      onClick={() => void onCancel()}
                    >
                      Cancel
                    </button>
                  </div>
                </div>

                <div className="lv-wf-canvas">
                  <div className="lv-wf-flow lv-wf-flow--linear">
                    {(selected.steps ?? []).length === 0 ? (
                      <p className="lv-tp-muted">This workflow has no steps.</p>
                    ) : (
                      (selected.steps ?? []).map((step, idx) => {
                        const result = (selected.step_results ?? []).find((r) => r.step_id === step.step_id);
                        const active = selectedStepId === step.step_id;
                        return (
                          <div key={step.step_id} className="lv-wf-step-row">
                            {idx > 0 ? <div className="lv-wf-link" /> : null}
                            <button
                              type="button"
                              className={`lv-wf-node${active ? " is-active" : ""}${result?.status === "COMPLETED" ? " is-store" : ""}${result?.status && result.status !== "COMPLETED" ? " is-notify" : ""}`}
                              onClick={() => setSelectedStepId(step.step_id)}
                            >
                              <div className="top">
                                <strong>
                                  {idx + 1}. {step.capability_id}
                                </strong>
                                <span className="dot" />
                              </div>
                              <small>
                                {step.step_id}
                                {result ? ` · ${result.status}` : selected.current_step === idx ? " · current" : ""}
                              </small>
                            </button>
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              </>
            )}
          </Panel>

          <Panel title="Step Inspector" className="lv-wf-inspector">
            {!selectedStep ? (
              <p className="lv-tp-muted">Select a step to inspect definition and results.</p>
            ) : (
              <>
                <div className="lv-wf-inspector-head">
                  <strong style={{ color: "var(--lv-text-bright)" }}>{selectedStep.capability_id}</strong>
                  <span className={`lv-tp-pill${selectedStepResult ? statePillClass(selectedStepResult.status === "COMPLETED" ? "COMPLETED" : "FAILED") : ""}`}>
                    {selectedStepResult?.status ?? "PENDING"}
                  </span>
                </div>
                <div className="lv-tp-field">
                  <label>Step ID</label>
                  <div className="lv-tp-muted">{selectedStep.step_id}</div>
                </div>
                <div className="lv-tp-field">
                  <label>Arguments</label>
                  <pre className="lv-wf-json">{JSON.stringify(selectedStep.arguments ?? {}, null, 2)}</pre>
                </div>
                <div className="lv-tp-field">
                  <label>Step result</label>
                  {selectedStepResult ? (
                    <pre className="lv-wf-json">{JSON.stringify(selectedStepResult, null, 2)}</pre>
                  ) : (
                    <p className="lv-tp-muted">No result yet — run the workflow to populate step_results.</p>
                  )}
                </div>
              </>
            )}
          </Panel>
        </section>

        {showCreate ? (
          <section className="lv-wf-bottom" style={{ gridTemplateColumns: "1fr" }}>
            <Panel
              title="Create workflow"
              action={
                <button type="button" className="lv-tp-btn" onClick={() => setShowCreate(false)}>
                  Close
                </button>
              }
            >
              <div className="lv-tp-field">
                <label htmlFor="wf-name">Name</label>
                <input
                  id="wf-name"
                  className="lv-tp-input"
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                  placeholder="e.g. Research digest"
                />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {draftSteps.map((step, idx) => (
                  <div key={step.key} className="lv-wf-draft-step">
                    <div className="lv-wf-draft-step-head">
                      <strong style={{ color: "var(--lv-text-bright)" }}>Step {idx + 1}</strong>
                      <button
                        type="button"
                        className="lv-tp-btn"
                        disabled={draftSteps.length <= 1}
                        onClick={() => setDraftSteps((prev) => prev.filter((s) => s.key !== step.key))}
                      >
                        Remove
                      </button>
                    </div>
                    <div className="lv-tp-field">
                      <label htmlFor={`wf-cap-${step.key}`}>Capability</label>
                      {capabilities.length > 0 ? (
                        <select
                          id={`wf-cap-${step.key}`}
                          className="lv-tp-select"
                          value={step.capability_id}
                          onChange={(e) =>
                            setDraftSteps((prev) =>
                              prev.map((s) => (s.key === step.key ? { ...s, capability_id: e.target.value } : s)),
                            )
                          }
                        >
                          <option value="">Select capability…</option>
                          {capabilities.map((cap) => (
                            <option key={cap.id} value={cap.id}>
                              {capabilityLabel(cap)}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          id={`wf-cap-${step.key}`}
                          className="lv-tp-input"
                          value={step.capability_id}
                          placeholder="capability_id e.g. knowledge.search"
                          onChange={(e) =>
                            setDraftSteps((prev) =>
                              prev.map((s) => (s.key === step.key ? { ...s, capability_id: e.target.value } : s)),
                            )
                          }
                        />
                      )}
                    </div>
                    <div className="lv-tp-field">
                      <label htmlFor={`wf-args-${step.key}`}>Arguments (JSON object)</label>
                      <textarea
                        id={`wf-args-${step.key}`}
                        className="lv-tp-textarea"
                        rows={4}
                        value={step.argumentsText}
                        onChange={(e) =>
                          setDraftSteps((prev) =>
                            prev.map((s) => (s.key === step.key ? { ...s, argumentsText: e.target.value } : s)),
                          )
                        }
                      />
                    </div>
                  </div>
                ))}
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                <button
                  type="button"
                  className="lv-tp-btn"
                  onClick={() =>
                    setDraftSteps((prev) => [...prev, newDraftStep(capabilities[0]?.id ?? "")])
                  }
                >
                  + Add step
                </button>
                <button
                  type="button"
                  className="lv-tp-btn lv-tp-btn--gold"
                  disabled={busy}
                  onClick={() => void onCreate()}
                >
                  Create
                </button>
              </div>
            </Panel>
          </section>
        ) : null}

        <section className="lv-wf-bottom lv-wf-bottom--2">
          <Panel title="Step results">
            {!selected ? (
              <p className="lv-tp-muted">Select a workflow to see step_results.</p>
            ) : (selected.step_results ?? []).length === 0 ? (
              <p className="lv-tp-muted">No step results yet.</p>
            ) : (
              <table className="lv-tp-table">
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Step</th>
                    <th>Capability</th>
                  </tr>
                </thead>
                <tbody>
                  {(selected.step_results ?? []).map((r) => (
                    <tr key={`${r.step_id}-${r.status}`}>
                      <td>
                        <span
                          className={`lv-tp-pill${r.status === "COMPLETED" ? " is-live" : " is-bad"}`}
                        >
                          {r.status}
                        </span>
                      </td>
                      <td>{r.step_id}</td>
                      <td>{r.capability_id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>

          <Panel title="Schedules">
            {schedulesError ? <p className="lv-tp-muted">{schedulesError}</p> : null}
            {schedules.length === 0 && !schedulesError ? (
              <p className="lv-tp-muted">No schedules.</p>
            ) : (
              schedules.map((s) => (
                <div key={s.schedule_id} className="lv-wf-schedule">
                  <strong>{s.name}</strong>
                  <label className="lv-wf-toggle">
                    <input
                      type="checkbox"
                      checked={String(s.status).toUpperCase() === "ACTIVE"}
                      disabled={busy}
                      onChange={() => void onToggleSchedule(s)}
                    />
                  </label>
                  <span className="lv-tp-muted">
                    {s.target_kind}:{s.target_ref} · {intervalLabel(s.interval_seconds)} · next{" "}
                    {formatTs(s.next_run_at)}
                  </span>
                  <span />
                </div>
              ))
            )}
            <div className="lv-wf-schedule-form">
              <input
                className="lv-tp-input"
                placeholder="Schedule name"
                value={scheduleName}
                onChange={(e) => setScheduleName(e.target.value)}
              />
              <input
                className="lv-tp-input"
                placeholder={selected ? `Target (${selected.workflow_id})` : "Target workflow id"}
                value={scheduleTarget}
                onChange={(e) => setScheduleTarget(e.target.value)}
              />
              <input
                className="lv-tp-input"
                placeholder="Interval seconds"
                value={scheduleInterval}
                onChange={(e) => setScheduleInterval(e.target.value)}
              />
              <button
                type="button"
                className="lv-tp-btn"
                disabled={busy}
                onClick={() => void onCreateSchedule()}
              >
                Add schedule
              </button>
            </div>
          </Panel>
        </section>
      </main>
    </AppShell>
  );
}
