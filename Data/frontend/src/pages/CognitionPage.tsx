import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type { CognitionHealth, CognitionRunStatus } from "../types/api";

/**
 * Operator surface for Cognitive Runtime.
 * All values come from `/api/cognition/*` — no decorative fake status.
 */
export function CognitionPage() {
  const toast = useAppToast();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<CognitionHealth | null>(null);
  const [message, setMessage] = useState("");
  const [shadow, setShadow] = useState(true);
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<CognitionRunStatus | null>(null);
  const [events, setEvents] = useState<unknown[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.cognitionHealth();
      setHealth(res.cognition);
      if (typeof res.cognition.shadow_default === "boolean") {
        setShadow(res.cognition.shadow_default);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load cognition health");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function submit() {
    const text = message.trim();
    if (!text) {
      toast("Enter a task message");
      return;
    }
    setBusy(true);
    try {
      const result = await api.cognitionSubmit({ message: text, shadow, run: true });
      setRun(result);
      const ev = await api.cognitionEvents(result.run_id);
      setEvents(ev.events);
      toast(result.shadow ? "Shadow cognition completed" : `Cognition status: ${result.status}`);
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Cognition submit failed");
    } finally {
      setBusy(false);
    }
  }

  async function cancelRun() {
    if (!run?.run_id) return;
    setBusy(true);
    try {
      const result = await api.cognitionCancel(run.run_id);
      setRun(result);
      toast("Cancellation requested");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Cancel failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Cognition Mode"
      searchPlaceholder="Cognitive runtime operator..."
      layout="wide"
    >
      <main className="lv-main">
        <section className="lv-panel lv-card" style={{ marginBottom: "1rem" }}>
          <div className="lv-card-head">
            <div className="lv-section-label">Cognitive Runtime</div>
            <span className="lv-online-count">
              {health?.enabled ? `${health.active_runs} active` : "Feature disabled"}
            </span>
          </div>
          <p className="lv-muted" style={{ marginTop: 0 }}>
            Public orchestration status only — no private chain-of-thought. Neuro remains advisory.
            Side effects still require ExecutionGateway and Approvals.
          </p>
          {loading ? <p className="lv-muted">Loading…</p> : null}
          {error ? <p className="lv-error">{error}</p> : null}
          {health ? (
            <div className="lv-kv-grid" style={{ display: "grid", gap: "0.5rem", gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))" }}>
              <div>enabled: <strong>{String(health.enabled)}</strong></div>
              <div>shadow_default: <strong>{String(health.shadow_default)}</strong></div>
              <div>iterative: <strong>{String(health.iterative)}</strong></div>
              <div>belief: <strong>{String(health.belief_enabled)}</strong></div>
              <div>neuro: <strong>{String(health.neuro_enabled)}</strong></div>
              <div>delegation: <strong>{String(health.delegation_enabled)}</strong></div>
              <div>experience: <strong>{String(health.experience_learning)}</strong></div>
              <div>tracked_runs: <strong>{health.tracked_runs}</strong></div>
            </div>
          ) : null}
        </section>

        <section className="lv-panel lv-card" style={{ marginBottom: "1rem" }}>
          <div className="lv-section-label">Submit task</div>
          <textarea
            className="lv-input"
            rows={4}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Describe a task… (shadow mode does not replace chat answers)"
            style={{ width: "100%", marginTop: "0.5rem" }}
          />
          <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.75rem" }}>
            <input type="checkbox" checked={shadow} onChange={(e) => setShadow(e.target.checked)} />
            Shadow mode (plan/decide only — no user-visible answer replacement)
          </label>
          <div style={{ display: "flex", gap: "0.75rem", marginTop: "0.75rem" }}>
            <button className="lv-btn" type="button" disabled={busy || !health?.enabled} onClick={() => void submit()}>
              Run cognition
            </button>
            <button className="lv-btn lv-btn-ghost" type="button" disabled={busy || !run} onClick={() => void cancelRun()}>
              Cancel run
            </button>
            <button className="lv-btn lv-btn-ghost" type="button" disabled={busy} onClick={() => void load()}>
              Refresh health
            </button>
          </div>
          {!health?.enabled ? (
            <p className="lv-muted" style={{ marginTop: "0.75rem" }}>
              Enable with <code>LEVIATHAN_FEATURE_COGNITION=true</code>.
            </p>
          ) : null}
        </section>

        {run ? (
          <section className="lv-panel lv-card" style={{ marginBottom: "1rem" }}>
            <div className="lv-card-head">
              <div className="lv-section-label">Reasoning trace (public)</div>
              <span className="lv-online-count">{run.status}</span>
            </div>
            <div style={{ display: "grid", gap: "0.35rem" }}>
              <div>run_id: <code>{run.run_id}</code></div>
              <div>goal: {run.goal}</div>
              <div>domain: {run.domain}</div>
              <div>mode / strategy: {run.mode ?? "—"} / {run.strategy ?? "—"}</div>
              <div>uncertainty: {run.uncertainty ?? "—"}</div>
              <div>working_memory: {run.working_memory_count ?? 0}</div>
              <div>shadow: {String(!!run.shadow)}</div>
              {run.error ? <div className="lv-error">error: {run.error}</div> : null}
            </div>
            {run.plan?.steps?.length ? (
              <div style={{ marginTop: "1rem" }}>
                <div className="lv-section-label">Plan steps</div>
                <ol>
                  {run.plan.steps.map((step) => (
                    <li key={step.step_id}>
                      {step.objective} <span className="lv-muted">[{step.status}]</span>
                    </li>
                  ))}
                </ol>
              </div>
            ) : null}
            {run.actions?.length ? (
              <div style={{ marginTop: "1rem" }}>
                <div className="lv-section-label">Actions</div>
                <ul>
                  {run.actions.map((action, idx) => (
                    <li key={`${action.kind}-${idx}`}>
                      {action.kind}
                      {action.rationale ? <span className="lv-muted"> — {action.rationale}</span> : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {run.observations?.length ? (
              <div style={{ marginTop: "1rem" }}>
                <div className="lv-section-label">Observations</div>
                <ul>
                  {run.observations.map((obs, idx) => (
                    <li key={`${obs.kind}-${idx}`}>
                      [{obs.kind}] {obs.summary}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {events.length ? (
              <div style={{ marginTop: "1rem" }}>
                <div className="lv-section-label">Events ({events.length})</div>
                <pre className="lv-muted" style={{ maxHeight: 240, overflow: "auto", fontSize: 12 }}>
                  {JSON.stringify(events.slice(-20), null, 2)}
                </pre>
              </div>
            ) : null}
          </section>
        ) : null}
      </main>
    </AppShell>
  );
}
