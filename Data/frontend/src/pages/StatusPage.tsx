import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import type {
  HealthResponse,
  MasterGateReport,
  ReleaseGateReport,
  SecurityAuditReport,
} from "../types/api";

type LoadState = {
  health: HealthResponse | null;
  release: ReleaseGateReport | null;
  security: SecurityAuditReport | null;
  master: MasterGateReport | null;
  error: string | null;
};

export function StatusPage() {
  const [state, setState] = useState<LoadState>({
    health: null,
    release: null,
    security: null,
    master: null,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [health, release, security, master] = await Promise.all([
          api.health(),
          api.releaseGates(),
          api.securityAudit(),
          api.masterGates(),
        ]);
        if (cancelled) return;
        setState({
          health,
          release: release.report,
          security: security.report,
          master: master.report,
          error: null,
        });
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof ApiError ? err.message : "Failed to load operator status";
        setState((prev) => ({ ...prev, error: message }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const health = state.health;

  return (
    <AppShell activeMode="explore" searchPlaceholder="Operator status">
      <main className="lv-main">
        <section className="lv-panel lv-card" style={{ marginBottom: "1rem" }}>
          <div className="lv-card-head">
            <div className="lv-section-label">Operator Status</div>
            <span className="lv-online-count">
              {health?.ok ? "Control plane reachable" : "Waiting for health"}
            </span>
          </div>
          {state.error ? <p className="lv-muted">{state.error}</p> : null}
          {health ? (
            <div className="lv-world-stats">
              <div className="lv-world-stat">
                <span>Version</span>
                <strong>{health.version}</strong>
              </div>
              <div className="lv-world-stat">
                <span>LLM</span>
                <strong>{health.llm.available ? health.llm.model ?? "Ready" : "Offline"}</strong>
              </div>
              <div className="lv-world-stat">
                <span>Agents flag</span>
                <strong>{health.agents?.enabled ? "ON" : "OFF"}</strong>
              </div>
              <div className="lv-world-stat">
                <span>Approvals pending</span>
                <strong>{health.approvals?.pending ?? 0}</strong>
              </div>
              <div className="lv-world-stat">
                <span>Capabilities</span>
                <strong>{health.capabilities?.registered ?? "—"}</strong>
              </div>
              <div className="lv-world-stat">
                <span>Chaos</span>
                <strong>{health.chaos?.plan.enabled ? "ON" : "OFF"}</strong>
              </div>
            </div>
          ) : null}
        </section>

        <section className="lv-grid-2">
          <article className="lv-panel lv-card">
            <div className="lv-section-label">Master gates</div>
            <p>
              <strong>{state.master?.status ?? "…"}</strong>
              {state.master ? ` · phases ${state.master.phase_span}` : null}
            </p>
            <ul className="lv-agent-list">
              {(state.master?.checks ?? []).map((check) => (
                <li key={check.check_id} className="lv-agent-row" style={{ cursor: "default" }}>
                  <span>
                    <strong>{check.name}</strong>
                    <small>
                      {check.status} — {check.detail}
                    </small>
                  </span>
                </li>
              ))}
            </ul>
            <p className="lv-muted">Local readiness ≠ production certification.</p>
          </article>

          <article className="lv-panel lv-card">
            <div className="lv-section-label">Release gates</div>
            <p>
              <strong>{state.release?.ready ? "READY" : "NOT READY"}</strong>
            </p>
            <ul className="lv-agent-list">
              {(state.release?.checks ?? []).map((check) => (
                <li key={check.gate_id} className="lv-agent-row" style={{ cursor: "default" }}>
                  <span>
                    <strong>{check.name}</strong>
                    <small>
                      {check.passed ? "pass" : "fail"} · {check.severity} — {check.detail}
                    </small>
                  </span>
                </li>
              ))}
            </ul>
          </article>

          <article className="lv-panel lv-card">
            <div className="lv-section-label">Security posture</div>
            <p>
              <strong>
                {state.security
                  ? `${state.security.summary.passed}/${state.security.summary.total} passed`
                  : "…"}
              </strong>
            </p>
            <ul className="lv-agent-list">
              {(state.security?.findings ?? []).map((finding) => (
                <li key={finding.finding_id} className="lv-agent-row" style={{ cursor: "default" }}>
                  <span>
                    <strong>{finding.title}</strong>
                    <small>
                      {finding.passed ? "pass" : "fail"} · {finding.severity} — {finding.detail}
                    </small>
                  </span>
                </li>
              ))}
            </ul>
            <p className="lv-muted">Posture checks only — not a penetration test.</p>
          </article>
        </section>
      </main>
    </AppShell>
  );
}
